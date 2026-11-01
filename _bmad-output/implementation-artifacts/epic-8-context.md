# Epic 8 Context: Deployment Pipeline with Cloud Build and Cloud Deploy

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A merge to `main` puts the new version of bgb into production with no manual steps. Tests run once, on the pull request. Builds are keyless and reproducible, every release traces to a commit, and the pipeline is parameterised so a second environment can be added later as configuration, not a rewrite.

## Stories

- Story 8.1: Terraform foundations for the pipeline
- Story 8.2: GitHub connection, triggers and branch protection
- Story 8.3: Pull request path: tests and checks, run once
- Story 8.4: Cloud Deploy pipeline and Cloud Run manifests, prod only
- Story 8.5: Main path: build once, push and create a release
- Story 8.6: Rollback, documentation and cutover

## Requirements & Constraints

- Tests and checks run only on the PR build. A merge to `main` builds, pushes and releases without re-running tests.
- A PR must pass its check and be up to date with `main` before merging (branch protection), because `main` does not retest.
- One target only: `prod`, in project `aviato-prod-demo-baby-got-back`. Region comes from the Terraform `region` variable (default `us-central1`).
- Builds run as dedicated service accounts with no keys or static tokens. Builder and base images are pinned to exact versions. Deploys never use a `latest` tag.
- Fork PRs need maintainer approval (comment) before the build runs with project credentials.
- No API token exists. IAP is mandatory. `BGB_CORS_ORIGINS` is development only and must not be set in production.
- Rollback must be one command and tested once. A manual fallback deploy is documented with a warning that it skips PR tests.
- Post-deploy smoke tests, canary and automatic rollback belong to Epic 1 (Story 1.10). This epic only provides the rollback mechanism.
- The Demo tier project enables no APIs and group editor access ends 2026-11-30. The landing zone `owner_until` date must be extended before Story 8.1 is applied, or nobody can apply Terraform afterwards.

## Technical Decisions

- Cloud Deploy owns the running image and Cloud Run runtime configuration (image, env, resources, service account). Terraform owns surrounding infrastructure. It creates the service `bgb` and job `bgb-backup` once with a public bootstrap image, then ignores their templates via `lifecycle { ignore_changes }` (narrowest set that works), with a comment recording the decision. This reverses the earlier README line that Terraform is the only deploy path.
- Cloud Build only, no GitHub Actions. One `cloudbuild.yaml` with steps switched by substitution `_MODE` (`pr` or `main`, default `main`). Steps: install-deps (`uv sync --frozen`, `npm ci`), test-pr-only, build-image, guard-release, create-release.
- PR step runs `uv run pytest`, `ruff check` and `ruff format --check` on `src` and `tests`, `npm run lint` and `npm run build` in `web/`, `terraform fmt -check`, and `terraform init -backend=false` then `terraform validate`. The image is built on PRs but not pushed. Epic 1 will add further test stages to the `_MODE=pr` path of this same file.
- Main path: image pushed as `${_REGION}-docker.pkg.dev/${PROJECT_ID}/bgb/bgb:${COMMIT_SHA}`. Digest is read and written to `/workspace/image-digest`. Release `sha-${SHORT_SHA}` on pipeline `bgb` references the image by `@sha256:` digest, with commit SHA and build ID as annotations. `guard-release` fails unless `_MODE=main` and `$BRANCH_NAME` is `main`. Set `options.logging: CLOUD_LOGGING_ONLY` and a build timeout.
- The Dockerfile must install Python dependencies from `uv.lock` (for example `uv sync --frozen --no-dev`) instead of unpinned `pip install .`, so the main image uses the versions the PR tested.
- Service accounts: `bgb-cloudbuild` (runs builds, needs `roles/logging.logWriter`) and `bgb-deployer` (Cloud Deploy execution, `roles/iam.serviceAccountUser` on the runtime SA only, can deploy the service and job). Each role gets a documented reason in `CI-CD-SETUP.md`.
- Terraform enables Cloud Build, Artifact Registry, Cloud Deploy, IAM Credentials, Container Scanning and Cloud Quotas APIs, grants the runtime SA Cloud Quotas viewer (for Story 10.2 quota pacing), and creates Artifact Registry repo `bgb` with a cleanup policy keeping the last 20 tagged images. Outputs: registry path, deployer SA email, runtime SA email, bucket, job name.
- Triggers via a 2nd gen GitHub connection to `benking84/bgb` (only the OAuth handshake is manual, then imported into Terraform): `bgb-pr` on PRs to `main`, `bgb-main` on pushes to `^main$`.
- Cloud Deploy: delivery pipeline `bgb` with a serial pipeline of one stage (`prod`), targets created with `for_each` over a `deploy_targets` map variable (project, region, `requireApproval`, parameters). `requireApproval` is false for prod. `deploy/` holds `skaffold.yaml`, `service.yaml`, `job.yaml`. Anything environment specific is a deploy parameter, filled from Terraform outputs.
- Manifests must reproduce current Terraform runtime settings exactly: port 8080, CPU and memory limits, concurrency 80, timeouts (job timeout from `job_timeout_hours`), env vars, runtime service account, job command `python -m bgb run-due`, retries from `job_max_retries`.
- Deploy parameters include `BGB_OBJECT_RETENTION_DAYS` (must equal the bucket retention period), `BGB_IAP_AUDIENCE`, bucket, job name and project ID.
- Assumption to verify first in Story 8.4: Cloud Deploy's Cloud Run deployer can update both service and job in one release. Fallback is a post-deploy hook running `gcloud run jobs update`.
- After a Cloud Deploy rollout, `terraform plan` must show no changes to the service or job, and no destroy or replace of the service, job, bucket or Firestore database.

## Cross-Story Dependencies

- Order: 8.1, then 8.2 and 8.3, then 8.4, then 8.5, then 8.6.
- Epic 1 depends on this epic: Stories 8.1 to 8.3 land before Story 1.1, and Story 8.4 before Story 1.10 (which becomes Cloud Deploy verification and canary on `prod`). Epic 1 Story 1.9 scanning stays on the PR path.
- Epic 1 PR time budget is 15 minutes. Record the Story 8.3 PR build time as the baseline.
- Story 8.1's quota permission serves Story 10.2. Story 8.4's `BGB_OBJECT_RETENTION_DAYS` and `BGB_IAP_AUDIENCE` parameters serve Stories 4.x and 5.1 (retention and IAP audience).
- Story 8.6 owns the README Deploy section update (Terraform for infrastructure, Cloud Build and Cloud Deploy for the image, manual `terraform apply -var image=...` as bootstrap only) and the manual fallback via `gcloud deploy releases create`.
