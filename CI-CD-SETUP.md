# CI/CD setup

Draft for review. Story 8.6 expands this file. It currently records the service accounts and roles created by Terraform in Story 8.1.

No service account has a key. Each role is granted at the narrowest scope the role supports. Cloud Deploy, logging and quota roles can only be granted on the project.

## Service accounts and roles

| Account | Role | Scope | Reason |
| --- | --- | --- | --- |
| bgb-cloudbuild | roles/logging.logWriter | Project | Write build logs (builds use CLOUD_LOGGING_ONLY). |
| bgb-cloudbuild | roles/clouddeploy.releaser | Project | Create Cloud Deploy releases from the main build. |
| bgb-cloudbuild | roles/artifactregistry.writer | Repository bgb | Push images. No access to other repositories. |
| bgb-cloudbuild | roles/iam.serviceAccountUser | Service account bgb-deployer | Creating a release makes Cloud Deploy run as the deployer. |
| bgb-deployer | roles/clouddeploy.jobRunner | Project | Execute Cloud Deploy render and deploy jobs. |
| bgb-deployer | roles/run.developer | Service bgb | Update the service revision. |
| bgb-deployer | roles/run.developer | Job bgb-backup | Update the backup job. |
| bgb-deployer | roles/artifactregistry.reader | Repository bgb | Read the image being deployed. |
| bgb-deployer | roles/iam.serviceAccountUser | Service accounts bgb-ui and bgb-run only | The service runs as bgb-ui and the job as bgb-run, so deploying them requires acting as each. |
| bgb-run | roles/cloudquotas.viewer | Project | Read quota usage for pacing (Story 10.2). |

## GitHub connection and triggers

Draft for review. Terraform creates the repository link and both triggers. The manual steps are the OAuth handshake, importing the connection, and the GitHub branch protection setting. Terraform ignores `github_config`, so plans do not show it, but the imported connection metadata is still held in Terraform state. Restrict who can read the state. No token is stored in the repo.

Order matters. Do not run `terraform apply` before step 1 and the import in step 2, or Terraform creates a second, unauthorised connection. Do not enable branch protection (step 4) until Story 8.3 has added `cloudbuild.yaml`, or the required `bgb-pr` check fails on every PR and blocks all merges, including the Story 8.3 PR.

### 1. Authorise the connection (console, once)

1. Open Cloud Build, Repositories (2nd gen), in project `PROJECT` and region `REGION` (the Terraform `region`, default `us-central1`).
2. Create host connection, choose GitHub, and name it `bgb-github`. If you use another name, set `github_connection_name` and use that name in the import commands below.
3. Complete the GitHub OAuth flow and install the Cloud Build GitHub App on `benking84/bgb` only.

### 2. Import and apply

```
cd terraform
terraform import google_cloudbuildv2_connection.github projects/PROJECT/locations/REGION/connections/bgb-github
terraform plan
terraform apply
```

If the repository link was also created in the console, import it too: `terraform import google_cloudbuildv2_repository.bgb projects/PROJECT/locations/REGION/connections/bgb-github/repositories/bgb`. Otherwise Terraform creates it.

### 3. Triggers

| Trigger | Event | Branch | `_MODE` | Build file | Runs as |
| --- | --- | --- | --- | --- | --- |
| bgb-pr | Pull request | `^main$` | pr | cloudbuild.yaml | bgb-cloudbuild |
| bgb-main | Push | `^main$` | main | cloudbuild.yaml | bgb-cloudbuild |

`bgb-pr` uses `COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY`. Owners and collaborators build without a comment. For anyone else, including Dependabot, a maintainer reviews the code and comments `/gcbrun` before the build runs with project credentials. Until that comment, the required `bgb-pr` check stays pending and the PR cannot merge.

The PR build runs the `cloudbuild.yaml` from the PR branch as `bgb-cloudbuild`, so anyone allowed to run it can change what it does. Keep the list of repository collaborators short.

### 4. Branch protection (GitHub setting, not Terraform)

`main` does not retest, so the PR check must be enforced. On `main`, require:

- A pull request before merging.
- Status check `bgb-pr` to pass. The exact check name is shown on the first test PR and may include the trigger and project, so confirm it before saving.
- Branches to be up to date before merging (strict).

Example, run by a repository admin (confirm the context name first):

```
gh api -X PUT repos/benking84/bgb/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["bgb-pr"] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

This replaces any existing protection on `main`. Review current settings first with `gh api repos/benking84/bgb/branches/main/protection`.

Approvals are set to 0 because the repository has one maintainer, so the required check is the gate. `enforce_admins` is true so the owner cannot skip it. If Cloud Build or the GitHub App is down and a fix must merge, an admin can temporarily turn off `enforce_admins` in the branch protection settings, merge, and turn it back on. A merge made this way skips the PR tests.

### 5. Verify (operator)

1. `gcloud builds triggers list --region=REGION --project=PROJECT` shows `bgb-pr` and `bgb-main`.
2. Open a test PR to `main` and confirm the `bgb-pr` check appears and blocks merging until it passes and the branch is up to date.
3. `cloudbuild.yaml` arrives in Story 8.3. Until then the triggers cannot run a useful build, so expect failures if applied earlier.

## Assumptions to verify

- Story 8.2: `terraform validate` was not run (no provider access). Confirm the provider version supports `google_cloudbuildv2_*` and `repository_event_config`.
- Story 8.2: the trigger `service_account` uses the full path `projects/PROJECT/serviceAccounts/EMAIL`. Confirm on the first plan.
- Story 8.2: GitHub shows the check under a name derived from the trigger. Confirm the exact name before enabling branch protection.
- Story 8.4: resource level `run.developer` is enough for Cloud Deploy to update both the service and the job. If not, widen the scope and record why.
- Story 8.4: the deployer may need access to the Cloud Deploy artifacts bucket. Confirm the required grant on the first rollout.
- Story 8.4: Cloud Deploy's Cloud Run deployer can update both service and job in one release. The fallback is a post-deploy hook.
- Story 8.5: `bgb-cloudbuild` needs no further roles to create a release. Confirm on the first main build.
- Story 8.4: the Cloud Deploy service agent may need `roles/iam.serviceAccountUser` on `bgb-deployer`. Confirm on the first rollout.
- Story 8.4: Cloud Deploy may add labels, annotations or traffic settings to the service and job. If `terraform plan` shows drift after a rollout, add those fields to `ignore_changes`.
- Artifact Registry: the KEEP policy keeps the 20 newest versions of any tag state, because the provider does not allow a tag filter on `most_recent_versions`. Tagged versions older than 30 days are deleted unless they are among the newest 20.
- If a repository named `bgb` already exists in the project, import it before the first apply: `terraform import google_artifact_registry_repository.bgb projects/PROJECT/locations/REGION/repositories/bgb`.
- A fresh apply uses the bootstrap image, which has no `python`, so the scheduled job fails until the first release. This is accepted.

## Decision DEP-D1

Cloud Deploy owns the running image and Cloud Run runtime configuration. Terraform creates the service and job once, then ignores `template`, `client` and `client_version`.
