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

## Assumptions to verify

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
