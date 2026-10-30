# bgb

bgb ("baby got back") backs up Google Workspace. Files are split into fixed-size blocks, identical blocks are stored once, volumes are compressed, and each object and restored file is checked with SHA-256. Versions follow a retention policy. Restore rebuilds a file from its block list.

Gmail and Google Drive (including shared drives) are the sources that matter. Contacts uses the same plugin interface. Google Keep is registered and refused, because Keep has no supported Workspace API. Backup bytes go to Cloud Storage. Job config, run history, and the block index go to Firestore. Workspace credentials go to Secret Manager. Cloud Storage and Firestore encrypt data at rest. There is no application-level encryption key.

The design is described in [REVIEW.md](REVIEW.md).

## Run it locally

Python 3.11+ and Node 22.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python3 -m pytest

cd web
npm install
npm run dev
```

In another shell, from the repo root:

```bash
python3 -m bgb serve --host 127.0.0.1 --port 8741
```

Open http://127.0.0.1:8742. The UI talks to the API at `http://127.0.0.1:8741` (see `web/.env.development`).

With no Google credentials, choose **Load the Northwind sample**. That job uses fixture mail, Drive, and contacts, and still runs the real engine: dedup, compressed volumes under `data/volumes`, and a JSON index at `data/index.json`. The first run stores the shared handbook once. The second run uploads no new blocks.

```bash
python3 -m bgb run --job-id northwind
python3 -m bgb verify --job-id northwind --full
python3 -m bgb restore --job-id northwind --fileset FILESET_ID --path PATH --dest ./restored.bin
python3 -m bgb run-due
```

Set `BGB_API_TOKEN` to require `Authorization: Bearer` on the API. The settings page can store that token in the browser.

## Workspace access

Create a service account. In the Admin console, under Security → Access and data control → API controls → Domain-wide delegation, authorize that account's client id for these scopes:

| Purpose | Scope |
| --- | --- |
| Gmail | `https://www.googleapis.com/auth/gmail.readonly` |
| Drive, including shared drives the impersonated user can see | `https://www.googleapis.com/auth/drive.readonly` |
| Contacts | `https://www.googleapis.com/auth/contacts.readonly` |
| List users when a job selects "every user" | `https://www.googleapis.com/auth/admin.directory.user.readonly` |

Set the admin email in Settings. Backups impersonate each selected user. Shared drives are listed once as that admin, so the admin (or the user you put first, if admin email is empty) must be able to see the drives you want copied. Google Docs, Sheets, Slides, and Drawings are exported to Office or PNG. Forms, shortcuts, and other Docs types are skipped and reported on the run.

Two ways to hold the service account:

- **Keyless (preferred on Cloud Run).** Use the Cloud Run runtime service account itself. Terraform grants it `roles/iam.serviceAccountTokenCreator` on itself. Put its email in Settings → service account email. Domain-wide delegation must authorize that account's client id.
- **JSON key.** Store the key as a Secret Manager version of `bgb-workspace-sa` (Terraform creates the secret). The key is used only to mint delegated tokens.

OAuth is for a single user, without admin delegation. Create an OAuth client, then:

```bash
python3 -m bgb oauth-url --client-id CLIENT_ID --redirect-uri http://localhost:8765
python3 -m bgb oauth-exchange --client-id CLIENT_ID --client-secret CLIENT_SECRET \
  --redirect-uri http://localhost:8765 --code AUTH_CODE
```

Set auth mode to OAuth and list that one user on the job. Scopes are Gmail, Drive, and Contacts read-only. There is no Directory scope, so "every user" is rejected.

## Deploy

Create the GCP project yourself. Terraform does not create it. Build a container image that Cloud Run can pull, then apply `terraform/`. That is the only deployment path. It enables APIs and creates the bucket, Firestore, Secret Manager secret, IAM, Cloud Run service, Cloud Run job, and Cloud Scheduler job.

```bash
export PROJECT=your-project REGION=us-central1
export BUCKET=your-unique-bucket
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT}/bgb/bgb:latest

terraform -chdir=terraform init
terraform -chdir=terraform apply \
  -var project_id=$PROJECT \
  -var region=$REGION \
  -var bucket_name=$BUCKET \
  -var image=$IMAGE
```

The image value is an input. The container listens on `$PORT` and serves the API and the exported UI. The backup job uses the same image and runs `python -m bgb run-due`. Cloud Scheduler calls that job every 15 minutes. "Run now" in the UI starts the same job.

Optional Cloud KMS key on the bucket, off unless you set it:

```bash
terraform -chdir=terraform apply \
  -var project_id=$PROJECT \
  -var region=$REGION \
  -var bucket_name=$BUCKET \
  -var image=$IMAGE \
  -var kms_key_name=projects/$PROJECT/locations/$REGION/keyRings/RING/cryptoKeys/KEY
```

When `kms_key_name` is empty, the bucket uses Google-managed encryption. When it is set, Terraform enables the Cloud KMS API and grants the Cloud Storage service agent and the runtime service account `roles/cloudkms.cryptoKeyEncrypterDecrypter` on that key.

The Firestore `(default)` database can only be created once per project. If it already exists, import it before apply:

```bash
terraform -chdir=terraform import google_firestore_database.default projects/$PROJECT/databases/'(default)'
```

After apply, authorize domain-wide delegation for the runtime service account and open the service URL. The service requires authentication unless `allow_unauthenticated=true`. If you use a JSON key instead of keyless delegation, add it as a version of `bgb-workspace-sa`.

| Variable | Meaning |
| --- | --- |
| `project_id` | Existing GCP project |
| `region` | Cloud Run, bucket, and Scheduler region (default `us-central1`) |
| `bucket_name` | Globally unique Cloud Storage bucket |
| `image` | Container image Cloud Run pulls |
| `firestore_location` | Firestore location (default `nam5`) |
| `kms_key_name` | Optional CMEK key for the bucket |
| `allow_unauthenticated` | When true, the UI service is public |

Local overrides, if you point a machine at a real project:

| Variable | Meaning |
| --- | --- |
| `BGB_USE_GCP=1` | Firestore, Cloud Storage, and Secret Manager |
| `BGB_INDEX` | `firestore` (default when GCP is on) or `file` |
| `BGB_VOLUMES` | `gcs` or `file` |
| `BGB_GCS_BUCKET` | bucket name |
| `BGB_GCS_PREFIX` | object prefix, default `bgb` |
| `GOOGLE_CLOUD_PROJECT` | project id |
| `BGB_CLOUD_RUN_JOB` | full job name, `projects/.../locations/.../jobs/bgb-backup` |
| `BGB_DATA_DIR` | local index, volumes, and secrets (default `./data`) |
| `BGB_API_TOKEN` | optional bearer token |
| `PORT` | listen port |

Volumes are buffered in memory. Keep the volume size at or under 128 MiB. The default is 50 MiB. Block size defaults to 100 KiB.

## Tests

```bash
python3 -m pytest
```

The suite covers dedup, compression, retention (including the smart bucket policy), compaction, restore, verify, index rebuild, Gmail history (including an expired history id), Drive export and shared drives, Contacts sync, and the HTTP API against the sample workspace. Google APIs are mocked. Firestore and Cloud Storage are not integration-tested here. The local JSON index implements the same operations the engine uses.
