# Epic 8: Deployment Pipeline with Cloud Build and Cloud Deploy

**Status:** Draft for review
**Author:** Ben, with Claude
**Date:** 2026-10-31
**Scope:** bgb repository (`cloudbuild.yaml`, `deploy/`, `terraform/`, `README.md`, new `CI-CD-SETUP.md`)
**Reference pipeline:** `aviato-unified/astro-website`, branch `main`, commit `e86a883` (`cloudbuild.yaml` and `CI-CD-SETUP.md`)

---

## 1. Goal

A merge to `main` puts the new version of bgb into production with no manual steps. The pipeline is set up so a second environment can be added later as configuration, not a rewrite.

1. **Tests run once, on the pull request.** A PR cannot merge until the test step passes. A merge to `main` builds and releases. It does not run the tests again.
2. **One instance.** Cloud Deploy has a single target, `prod`, in project `aviato-prod-demo-baby-got-back`. The delivery pipeline, targets and manifests are parameterised per target, so `dev` or `staging` can be added as one more target.
3. **Keyless and reproducible.** Builds run as a dedicated service account with no key files or static tokens, on pinned images, and every release is traceable to a commit.

## 2. What we copy from astro-website, and what changes

| astro-website (observed) | bgb |
|---|---|
| Google Cloud Build is the only CI/CD path. One `cloudbuild.yaml`, with steps switched on or off by a substitution (`_DEPLOY_ENV`) | Same. One `cloudbuild.yaml`, with steps switched by `_MODE` (`pr` or `main`) |
| The test step (`npm run check && npm test`) runs only on the review build and is skipped on `main`, so reviewed releases deploy without running the tests a second time | Same principle. The test step runs only on the PR trigger. The `main` trigger skips it |
| Review happens on a `dev` branch and a second Hosting site | **Changed.** Review happens on the pull request. There is no `dev` branch or `dev` instance |
| Dedicated build service account `cloudbuild-deployer`, not the legacy Cloud Build account, with a table explaining every role | Same. `bgb-cloudbuild` runs builds and `bgb-deployer` runs Cloud Deploy rollouts. `CI-CD-SETUP.md` gives a reason for each role |
| `options.logging: CLOUD_LOGGING_ONLY`, so the build SA needs `roles/logging.logWriter` | Same |
| Builder images pinned to an exact version | Same, for every builder image |
| Guard script (`select-hosting-site.mjs`) refuses to put a non-production build on the production site | Same idea. A guard step refuses to create a release unless `_MODE=main` and the branch is `main` |
| Deploys with `firebase-tools deploy` | **Changed.** Builds a container image, pushes it to Artifact Registry, and creates a **Cloud Deploy** release that rolls out to the Cloud Run service and job |
| Bitbucket Cloud connection | **Changed.** bgb lives on GitHub (`benking84/bgb`), so it uses a 2nd gen GitHub connection |
| Triggers created by `gcloud` and the Cloud Build API, documented in `CI-CD-SETUP.md` | Terraform in this repo creates the triggers, service accounts and IAM. The only manual step is the GitHub OAuth handshake for the connection |
| Release labelled `Cloud Build <short sha>` | Cloud Deploy release named `sha-<short sha>`. The image is tagged with the full SHA and deployed by digest |

Not copied: search engine notification, Firebase Functions configuration and `noindex` handling. Those belong to a public website.

## 3. Decisions recorded

| ID | Decision | Source |
|---|---|---|
| DEP-D1 | **Cloud Deploy owns the running image and the Cloud Run runtime configuration** (image, env, resources, service account). Terraform owns the infrastructure around it. It creates the service and job once with a bootstrap image, then ignores their templates. This reverses the "Terraform is the only deployment path" line added to `README.md` in commit `e3b0171`, and matches Epic 1 decision D1, already decided "yes" on the same date. Cloud Deploy also owns runtime configuration, which goes further than Epic 1 D1 (image only). | Ben, 2026-10-31 |
| DEP-D2 | The only target is `prod`, in `aviato-prod-demo-baby-got-back`. | Ben, 2026-10-31 |
| DEP-D3 | Tests run on the PR trigger only. `main` builds, releases and deploys without running them again. | Ben, 2026-10-31 |
| DEP-D4 | Cloud Build, not GitHub Actions. This matches astro-website and Epic 1 D3. | Epic 1 D3, decided 2026-10-31 |

## 4. Assumptions and risks

| # | Assumption or risk | Mitigation, or impact if wrong |
|---|---|---|
| A1 | **The merged commit must be the tested commit.** Because `main` does not test again, a PR that is behind `main` could merge a combination of changes that was never tested. | Branch protection on `main` requires the PR check and requires branches to be up to date before merging (Story 8.2). |
| A2 | The image built on `main` is a rebuild of tested source, not the image the PR built. astro-website works the same way. | Accepted, once dependencies are locked. Builder and base images are pinned and the web build uses `package-lock.json`. The Python build does not yet: the Dockerfile runs `pip install .` with no lock, so Story 8.5 makes it install from the committed `uv.lock`, and Story 8.3 fails a PR whose lock is out of date. Promoting the PR image is a later option. |
| A3 | Cloud Deploy's Cloud Run deployer can roll out both the service and the job from one release. | Verify at the start of Story 8.4. If it cannot, a Cloud Deploy post-deploy hook updates the job image with `gcloud run jobs update`. |
| A4 | The region comes from the Terraform `region` variable (default `us-central1`). Triggers, Artifact Registry and the delivery pipeline all use it. | None. If prod should run in `australia-southeast1` like astro-website, set the variable. |
| A5 | The Demo tier project enables no APIs, and group editor access ends on 2026-11-30 (from Epic 1, section 7). | Story 8.1 enables the APIs in Terraform. The landing zone `owner_until` date must be extended, or the tier raised, before that date. Otherwise nobody can apply Terraform afterwards. |
| A6 | The Demo tier landing zone does not provide a Cloud Deploy pipeline for this project (from Epic 1). | This epic creates the pipeline in the project itself, through Terraform. If the landing zone team wants Cloud Deploy in a separate CICD project, that is a Startup or Enterprise tier change, and the Story 8.4 targets move. |
| A7 | Post-deploy smoke tests, canary job runs and automatic rollback on failure stay in Epic 1 (Story 1.10). This epic provides the rollback mechanism, not automated verification. | If wanted sooner, add Cloud Deploy `verify: true` with a health check container to Story 8.4. |

## 5. Pipeline design

### 5.1 Triggers

| Trigger | Event | `_MODE` | Runs |
|---|---|---|---|
| `bgb-pr` | Pull request opened or updated against `main` | `pr` | Install, tests and checks, image build (not pushed) |
| `bgb-main` | Push to `main` | `main` (default) | Install, image build and push, guard, Cloud Deploy release |

Both triggers run `cloudbuild.yaml` as `bgb-cloudbuild`, in the prod project, in `var.region`.

### 5.2 Steps in `cloudbuild.yaml`

```
                    PR (_MODE=pr)                 main (_MODE=main)
1 install-deps      uv sync, npm ci               uv sync, npm ci
2 test-pr-only      pytest, ruff, web lint,       skipped
                    web build, tf fmt/validate
3 build-image       docker build                  docker build, push :$COMMIT_SHA
4 guard-release     skipped                       fail unless branch is main
5 create-release    skipped                       gcloud deploy releases create sha-$SHORT_SHA
                                                  --images bgb=<image>@<digest>
```

### 5.3 Cloud Deploy

```
release sha-<short sha>  ──►  delivery pipeline "bgb"
                                 serialPipeline:
                                   stages: [ prod ]          ◄── later: [ dev, prod ]
                                                │
                                    target "prod" (aviato-prod-demo-baby-got-back)
                                    deployParameters: bucket, job name, project, ...
                                                │
                                    Cloud Run service "bgb"  +  Cloud Run job "bgb-backup"
```

- Terraform creates the targets from a `deploy_targets` map variable. The default map has one entry, `prod`. A later environment adds an entry (project, region, approval flag, parameters) and, if needed, a matching Skaffold profile.
- Runtime values that differ per target (bucket name, job name, project ID, API token secret) come from target `deployParameters`. Terraform fills them from its own resources, so each value has one source.
- `requireApproval` is off for `prod` while it is the only target, so a merge deploys with no one in the loop. It is a per target flag for later.

## 6. Stories

Stories are listed in dependency order.

---

### Story 8.1: Terraform foundations for the pipeline

**As** the bgb team, **we want** Terraform to create the registry, APIs, service accounts and IAM for the pipeline, **so that** the pipeline can be rebuilt from this repo and keeps working after group editor access ends.

**Acceptance criteria**
- `terraform apply` enables the Cloud Build, Artifact Registry, Cloud Deploy, IAM Credentials and Container Scanning APIs in `aviato-prod-demo-baby-got-back`, in addition to the APIs already enabled.
- An Artifact Registry Docker repository `bgb` exists in `var.region`.
- Two service accounts exist, with no keys: `bgb-cloudbuild` (runs builds) and `bgb-deployer` (Cloud Deploy execution). Each has only the roles listed in `CI-CD-SETUP.md`, with a reason for each role, as in the astro-website role table. `bgb-cloudbuild` has `roles/logging.logWriter`.
- `bgb-deployer` can act as the runtime service account (`roles/iam.serviceAccountUser` on that account only), and can deploy the `bgb` service and `bgb-backup` job.
- `google_cloud_run_v2_service.ui` and `google_cloud_run_v2_job.backup` use `lifecycle { ignore_changes = [template] }`, or the narrowest set of fields that lets Cloud Deploy own image, env and resources. The `image` variable defaults to a public bootstrap image, so a fresh apply does not need a built image.
- A plan against the existing deployment shows no destroy or replace of the service, job, bucket or Firestore database.

**Tasks**
- [ ] Add the APIs to `google_project_service.required`.
- [ ] Add `google_artifact_registry_repository.bgb` with a cleanup policy that keeps the last 20 tagged images.
- [ ] Add the two service accounts and their IAM bindings.
- [ ] Add the `lifecycle` blocks and the bootstrap image default, with a comment next to them that records DEP-D1.
- [ ] Add the outputs later stories need: registry path, deployer SA email, runtime SA email, bucket, job name.

---

### Story 8.2: GitHub connection, triggers and branch protection

**As** a reviewer, **I want** every PR to get a Cloud Build check and every merge to start a release, **so that** nothing reaches `main` untested and nothing on `main` waits for a manual deploy.

**Acceptance criteria**
- A 2nd gen Cloud Build connection to GitHub links `benking84/bgb`. The one console step (OAuth authorisation) is documented in `CI-CD-SETUP.md`. Everything after it is Terraform.
- Trigger `bgb-pr` fires on pull requests to `main`, runs `cloudbuild.yaml` with `_MODE=pr` as `bgb-cloudbuild`, and reports a status check on the PR.
- Trigger `bgb-main` fires on pushes to `^main$` and runs `cloudbuild.yaml` with `_MODE=main` as `bgb-cloudbuild`.
- Branch protection on `main` requires the `bgb-pr` check to pass and requires the branch to be up to date before merging (risk A1).
- PR builds from outside contributors need a comment from a maintainer before they run, so a fork cannot run the build with project credentials without approval.

**Tasks**
- [ ] Create the connection in the console, then import it into Terraform (`google_cloudbuildv2_connection`, `google_cloudbuildv2_repository`).
- [ ] Add `google_cloudbuild_trigger.pr` and `google_cloudbuild_trigger.main`.
- [ ] Set branch protection in GitHub and record the settings in `CI-CD-SETUP.md`.
- [ ] Confirm with `gcloud builds triggers list` and one test PR.

---

### Story 8.3: Pull request path: tests and checks, run once

**As** the team, **we want** all tests to run on the PR build, **so that** review is backed by evidence and `main` does not need to repeat them.

**Acceptance criteria**
- `cloudbuild.yaml` has a `test-pr-only` step, modelled on astro-website's `test-dev-only` step. It runs only when `_MODE=pr` and prints a clear skip message otherwise.
- On a PR, the step runs `uv run pytest`, `ruff check` and `ruff format --check` on `src` and `tests`, `npm run lint` and `npm run build` in `web/`, and `terraform fmt -check` and `terraform validate` (after `terraform init -backend=false`).
- The image builds on PRs to check the Dockerfile, and is not pushed.
- Any failing command fails the build and the PR check.
- A `main` build log shows the test step skipped, and no test command runs on `main`.
- Builder images are pinned to exact versions, with a comment on why each image was chosen (as astro-website does for Debian over Alpine).
- PR build time is recorded in the story notes as the baseline for Epic 1's 15 minute PR budget.

**Tasks**
- [ ] Write the `install-deps` and `test-pr-only` steps. `install-deps` uses `uv sync --frozen`, so a `uv.lock` that does not match `pyproject.toml` fails the PR.
- [ ] Add `ruff` to the `dev` extra in `pyproject.toml` if it is missing. Fix or baseline existing findings so the gate starts green.
- [ ] Add pip and npm caching only if PR builds take longer than 10 minutes.

**Note:** Epic 1 adds more test stages (coverage, emulator integration, Playwright, image scanning). They go into the `_MODE=pr` path of this file, which keeps the rule that `main` does not test again.

---

### Story 8.4: Cloud Deploy pipeline and Cloud Run manifests, prod only

**As** the team, **we want** a Cloud Deploy delivery pipeline with one `prod` target that rolls out the service and the job together, **so that** releases deploy the same way every time and new environments are a configuration change.

**Acceptance criteria**
- Assumption A3 is checked first: a manual release proves Cloud Deploy updates both the `bgb` service and the `bgb-backup` job. The result is recorded in the story notes.
- Terraform creates delivery pipeline `bgb` and its targets from a `deploy_targets` variable. The default contains only `prod` (project `aviato-prod-demo-baby-got-back`, `var.region`, `requireApproval = false`), running as `bgb-deployer`.
- `deploy/` contains `skaffold.yaml`, `service.yaml` and `job.yaml`. Every value that differs per environment is a deploy parameter, not a literal. The manifests reproduce the current Terraform runtime settings exactly: port 8080, CPU and memory limits, concurrency 80, timeouts, env vars, runtime service account, job command `python -m bgb run-due`, and `max_retries = 0`.
- `cloudbuild.yaml` passes the Skaffold config when it creates the release.
- After the first rollout, `gcloud run services describe bgb` and `gcloud run jobs describe bgb-backup` match their configuration before cutover, except for the image.
- `CI-CD-SETUP.md` documents adding a second environment as: add a `deploy_targets` entry, add a Skaffold profile if needed, add the stage to the pipeline order. No change to `cloudbuild.yaml`.
- `terraform plan` after a Cloud Deploy rollout shows no changes to the service or job.

**Tasks**
- [ ] Spike A3 with a hand written release.
- [ ] Add `google_clouddeploy_delivery_pipeline.bgb` and `google_clouddeploy_target` with `for_each`.
- [ ] Write the manifests, and map Terraform outputs to target `deploy_parameters`.
- [ ] Either remove the runtime settings now in the manifests from the Terraform `template` blocks, or keep them as bootstrap values under `ignore_changes`. Note which in the README.

---

### Story 8.5: Main path: build once, push and create a release

**As** the team, **we want** each merge to produce one image and one Cloud Deploy release, **so that** what runs in production is traceable to a single commit.

**Acceptance criteria**
- On `main`, the image is built once and pushed as `${_REGION}-docker.pkg.dev/${PROJECT_ID}/bgb/bgb:${COMMIT_SHA}`. Deploys never use a `latest` tag.
- The build reads the pushed digest, and the release references the image by `@sha256:` digest.
- A `guard-release` step fails the build if `_MODE` is not `main` or `$BRANCH_NAME` is not `main`, so a misconfigured trigger cannot release. This follows astro-website's site guard.
- `gcloud deploy releases create sha-${SHORT_SHA}` creates the release on delivery pipeline `bgb`, with the commit SHA and build ID as annotations.
- When two merges land close together, two releases are created and the later one ends up deployed.

**Tasks**
- [ ] Change the Dockerfile to install Python dependencies from `uv.lock` (for example `uv sync --frozen --no-dev`) instead of an unpinned `pip install .`, so the image built on `main` uses the versions the PR tested (A2).
- [ ] Write the `build-image`, `guard-release` and `create-release` steps.
- [ ] Write the digest to `/workspace/image-digest` for the release step.
- [ ] Set `options.logging: CLOUD_LOGGING_ONLY` and a build timeout.

---

### Story 8.6: Rollback, documentation and cutover

**As** the person on call, **I want** to know how a version reached production and how to undo it, **so that** a bad release can be fixed with one command.

**Acceptance criteria**
- `CI-CD-SETUP.md` exists and follows the structure of astro-website's version. It covers the architecture diagram, triggers table, service accounts with a reason for each role, the GitHub connection step, running a trigger by hand, finding which release is live, troubleshooting the first build, and adding an environment.
- Rollback is documented and tested once: `gcloud deploy targets rollback prod --delivery-pipeline=bgb` returns the service and job to the previous release.
- The `README.md` "Deploy" section is updated: Terraform creates the infrastructure, and Cloud Build and Cloud Deploy deploy the image (DEP-D1). The manual `terraform apply -var image=...` path is described as bootstrap only.
- A manual fallback deploy is documented (`gcloud deploy releases create` from a workstation with a given digest), with the same warning astro-website gives: it skips the PR tests.
- The first merge after cutover deploys to production with no manual step, and the live revision's image digest matches the release.

**Tasks**
- [ ] Write `CI-CD-SETUP.md`.
- [ ] Update `README.md`.
- [ ] Do the cutover: apply Terraform, merge a no-op change, confirm the rollout, roll back, then roll forward again.

---

## 7. Dependencies and order

| Order | Stories | Result |
|---|---|---|
| 1 | 8.1 | Registry, service accounts and IAM exist, and Terraform no longer fights the pipeline |
| 2 | 8.2, 8.3 | Every PR is tested and merges are gated |
| 3 | 8.4 | Cloud Deploy can roll out to prod |
| 4 | 8.5 | Merges create releases automatically |
| 5 | 8.6 | Documented, rollback tested, cut over |

## 8. Alignment with the quality gates plan

Epic 1 (quality gates) was written before these decisions. It was revised on 2026-10-31 to match them. It keeps its number, so it depends on this epic: Stories 8.1 to 8.3 land before Story 1.1, and Story 8.4 before Story 1.10. The table records what changed.

| Epic 1 location | Conflict | Resolution, applied 2026-10-31 |
|---|---|---|
| Section 4.1 and Story 1.1 | `main` runs stages 1 to 7, repeating the PR tests, from separate `ci/cloudbuild-pr.yaml` and `ci/cloudbuild-main.yaml` files | Tests run on PR only (DEP-D3). Epic 1 adds stages to the `_MODE=pr` path of the single `cloudbuild.yaml`. The trigger and service account work in Story 1.1 moves to Stories 8.1 and 8.2 |
| Story 1.9 | The image is built and pushed for every commit, including PRs | PRs build the image without pushing it, and `main` pushes it (Story 8.5). Scanning and structure tests stay in 1.9, on the PR path |
| Story 1.10 | Deploys with `gcloud run deploy --no-traffic` and `update-traffic` | Deploys go through Cloud Deploy (Story 8.4). Story 1.10 becomes Cloud Deploy verification and canary on the `prod` target, plus automatic rollback |
| Section 3 A3, D1, and the README task in Story 1.10 | D1 gives the pipeline the image only, and Story 1.10 documents a `gcloud run deploy` fallback | Cloud Deploy also owns runtime configuration (DEP-D1). The README update and the manual fallback move to Story 8.6, using `gcloud deploy releases create` |
| Story 1.11 | The nightly build runs the full suite against the CI area | No conflict. A nightly run is not a repeat test of a merge |

## 9. Open questions

| ID | Question | Recommendation |
|---|---|---|
| Q1 | Should Cloud Deploy also own `BGB_API_TOKEN`, as a Secret Manager reference in the manifest? Epic 1 Story 1.7 wants the pipeline to refuse a public service with no token. | Yes. Add a `bgb-api-token` secret in Story 8.1 and reference it in `service.yaml`. |
| Q2 | Who extends the Demo project `owner_until` date (2026-11-30), or raises the tier? | Ben to raise it with the landing zone owners before Story 8.1 is applied. |
