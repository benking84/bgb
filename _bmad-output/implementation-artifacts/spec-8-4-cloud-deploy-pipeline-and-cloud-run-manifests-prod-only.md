---
title: 'Story 8.4: Cloud Deploy pipeline and Cloud Run manifests, prod only'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: 'efd6d984fd6eeaabe03214bf335395701ab0a847'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Commit the Story 8.4 changes (deploy/, terraform/main.tf, terraform/variables.tf, terraform/outputs.tf, tests/test_deploy_manifests.py, CI-CD-SETUP.md and this spec file). The run could not commit because Bash was denied.'
  - 'Run terraform -chdir=terraform fmt -check, then terraform init -backend=false and terraform validate on a machine that can reach registry.terraform.io, and fix anything reported. None of these ran.'
  - 'Run uv run --extra dev pytest tests/test_deploy_manifests.py and fix any failure. The tests did not run and match some main.tf text including spacing.'
  - 'Spike assumption A3 with a hand written release: run gcloud deploy releases create against pipeline bgb with --source=deploy and an image digest, confirm the render succeeds with the {{.KEY}} placeholders and two-file rawYaml (check the skaffold apiVersion), and that one rollout updates both the bgb service and the bgb-backup job. Record the outcome in CI-CD-SETUP.md. If the job is not updated, add a post-deploy hook running gcloud run jobs update.'
  - 'After the first rollout, compare gcloud run services describe bgb and gcloud run jobs describe bgb-backup with the configuration before cutover (only the image and the new service BGB_IAP_AUDIENCE variable may differ).'
  - 'Run terraform plan after the rollout and confirm no change to the service or job and no destroy or replace of the service, job, bucket or Firestore database. Add drifting fields to ignore_changes if needed.'
  - 'Apply Terraform and confirm the Cloud Deploy API accepts the empty BGB_IAP_AUDIENCE deploy parameter. If it rejects it, set iap_audience to a placeholder value until Story 5.1.'
  - 'Grant any missing access found on the first rollout: the Cloud Deploy artifacts bucket for bgb-deployer and roles/iam.serviceAccountUser for the Cloud Deploy service agent on bgb-deployer.'
deferred:
  - summary: >-
      The Story 8.4 acceptance criterion that cloudbuild.yaml passes the Skaffold config when it creates the release is not met here.
    evidence: |-
      The create-release step belongs to Story 8.5 and 8.3 forbade it. CI-CD-SETUP.md records the exact release command for 8.5 (--source=deploy).
    location: >-
      cloudbuild.yaml
    severity: medium
  - summary: >-
      The manifest test compares env var names, not values, and depends on terraform fmt spacing in main.tf.
    evidence: |-
      tests/test_deploy_manifests.py checks name sets and exact aligned text such as the 3600s timeout line, so a wrong value passes and a reformat fails.
    location: >-
      tests/test_deploy_manifests.py
    severity: low
  - summary: >-
      deploy_stage_order has no validation for empty or duplicate entries, and the missing-target check is a lifecycle precondition.
    evidence: |-
      An empty list gives a pipeline with no stages. Whether the precondition fires before an invalid index error is unconfirmed until terraform validate runs.
    location: >-
      terraform/main.tf, terraform/variables.tf
    severity: low (unverified)
---

<intent-contract>

## Intent

**Problem:** Terraform creates the Cloud Run service `bgb` and job `bgb-backup` with a bootstrap image and then ignores their templates (DEP-D1), but nothing yet deploys a real image or owns the runtime settings.

**Approach:** Add a Cloud Deploy delivery pipeline `bgb` and targets from a `deploy_targets` map (default: `prod` only), plus `deploy/skaffold.yaml`, `service.yaml` and `job.yaml` that reproduce the current runtime settings, with every environment specific value a deploy parameter filled from Terraform.

## Boundaries & Constraints

**Always:** Manifests reproduce the current Terraform runtime settings exactly (port 8080, cpu and memory limits, concurrency 80, timeouts, env vars, runtime service accounts, job command `python -m bgb run-due`, retries from `job_max_retries`, timeout from `job_timeout_hours`). Targets run as `bgb-deployer`, `requireApproval` false for prod. Deploy parameters include `BGB_OBJECT_RETENTION_DAYS` and `BGB_IAP_AUDIENCE`. Images are referenced by the placeholder `bgb`, never a tag. Existing `ignore_changes` on the service and job stays.

**Never:** Set `BGB_CORS_ORIGINS`. Add the `create-release` step, push, or guard steps to `cloudbuild.yaml` (Story 8.5). Change the Dockerfile. Write `sprint-status.yaml`. Hard code the project, region, bucket or service account emails in manifests.

</intent-contract>

## Code Map

- `terraform/main.tf` -- service `ui` (lines 196-249) and job `backup` (259-311) hold the runtime settings to copy; IAM for `bgb-deployer` exists (414-448); locals block at 16-41.
- `terraform/variables.tf` -- add `deploy_targets`, `deploy_stage_order`, `iap_audience`. `job_timeout_hours`, `job_max_retries`, `object_retention_days` already exist.
- `terraform/outputs.tf` -- add pipeline name and target ids.
- `src/bgb/runtime.py:33` -- only reader of `BGB_OBJECT_RETENTION_DAYS`; `BGB_IAP_AUDIENCE` is not read yet (Stories 4.5 and 5.1).
- `cloudbuild.yaml` -- PR path only today; release step belongs to Story 8.5. Not edited.
- `CI-CD-SETUP.md` -- has the Story 8.4 assumptions list; extend with the A3 spike, parameters, manual release and adding an environment.
- `tests/` -- pytest runs on the PR path; add a manifest test.

## Tasks & Acceptance

**Execution:**
- `terraform/variables.tf` -- add `deploy_targets` (map of objects with optional `project_id`, `region`, `require_approval`, `parameters`; default `{ prod = {} }`, so project and region fall back to `var.project_id` and `var.region`), `deploy_stage_order` (default `["prod"]`) and `iap_audience` (default empty) -- AC2, AC4
- `terraform/main.tf` -- add locals for base deploy parameters (project, region, bucket, job name, service and job accounts, retention days, IAP audience, job timeout seconds, retries), `google_clouddeploy_target` with `for_each`, and `google_clouddeploy_delivery_pipeline.bgb` with one stage per `deploy_stage_order` entry; targets execute as `bgb-deployer` -- AC2
- `terraform/outputs.tf` -- output `delivery_pipeline` and `deploy_targets` -- AC2
- `deploy/skaffold.yaml` -- Cloud Run deployer, `manifests.rawYaml` listing both manifests -- AC3
- `deploy/service.yaml`, `deploy/job.yaml` -- Cloud Run manifests with `{{.key}}` placeholders for every deploy parameter -- AC3, AC4
- `tests/test_deploy_manifests.py` -- assert fixed settings match, no CORS env, image is the placeholder, and every placeholder has a matching key in the Terraform parameter locals -- AC3
- `CI-CD-SETUP.md` -- document A3 spike steps and outcome placeholder, the parameters table, the exact release command Story 8.5 must run (`--skaffold-file`, `--source=deploy`), adding a second environment, and that the service and job `template` is bootstrap only under `ignore_changes` -- AC1, AC5, AC6

**Acceptance Criteria:**
- Given the Terraform, when read, then pipeline `bgb` and a target per `deploy_targets` entry exist, `prod` is the default, runs as `bgb-deployer`, and has `requireApproval` false.
- Given `deploy/`, when read, then `skaffold.yaml`, `service.yaml` and `job.yaml` exist, and the fixed runtime settings equal those in `terraform/main.tf`.
- Given the manifests, when searched, then `BGB_CORS_ORIGINS` is absent and `BGB_OBJECT_RETENTION_DAYS` and `BGB_IAP_AUDIENCE` come from deploy parameters.
- Given `CI-CD-SETUP.md`, when read, then it states how to add a second environment with no change to `cloudbuild.yaml`, and lists the A3 spike and post-rollout checks (`gcloud run services describe`, `gcloud run jobs describe`, `terraform plan` shows no service or job change) as operator actions.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 16 findings — high 0, medium 3, low 8, false 0, maybe-false 5
- note: one reviewer layer ran, reading files directly, because Bash was denied and no diff file could be written. The blind, verification-gap and intent layers did not run.
- findings:
  - `[medium]` `[patch]` CORS test asserts the raw text lacks `BGB_CORS_ORIGINS`, but the service.yaml comment contains it, so the test fails — the test now matches `name: BGB_CORS_ORIGINS`.
  - `[medium]` `[patch]` Release command passed `--source=deploy` with `--skaffold-file=deploy/skaffold.yaml`, a doubled path — flag removed from CI-CD-SETUP.md, default `skaffold.yaml` applies.
  - `[medium]` `[patch]` Docs advertised per-target `project_id` and `region`, but the pipeline resolves targets in its own location — docs now say to keep them at the pipeline's values.
  - `[low]` `[defer]` Env test compares names only — recorded in `deferred`.
  - `[low]` `[defer]` Tests depend on fmt spacing — recorded in `deferred`.
  - `[low]` `[reject]` Parameter test is one directional — a dead parameter is harmless and Terraform may hold extra keys.
  - `[low]` `[reject]` Skaffold test only checks strings — the file is three lines and the A3 spike is the real test.
  - `[low]` `[reject]` No tests for Terraform defaults — `terraform validate` and plan are the meaningful check.
  - `[low]` `[reject]` `deploy_targets` output order is cosmetic.
  - `[low]` `[defer]` No validation on `deploy_stage_order` — recorded in `deferred` as unverified.
  - `[maybe-false]` `[reject]` Unquoted `{{.KEY}}` is invalid YAML before substitution — Cloud Deploy substitutes text before parsing; unquoted is required for integer fields. The A3 spike settles it (operator action).
  - `[maybe-false]` `[reject]` Whole `{{.KEY}}` mechanism and one render for service plus job unverified — covered by the A3 spike operator action.
  - `[maybe-false]` `[defer]` Empty `BGB_IAP_AUDIENCE` parameter may be rejected by the API — listed as an operator action.
  - `[maybe-false]` `[reject]` Precondition ordering versus invalid index — merged with the `deploy_stage_order` deferral.
  - `[medium]` `[defer]` Release step passing the Skaffold config is Story 8.5 work — recorded in `deferred`.
  - `[maybe-false]` `[reject]` Empty string app behaviour — the app does not read the variable yet (Stories 4.5 and 5.1).

## Design Notes

The Cloud Deploy placeholder syntax and multi-resource Skaffold support could not be checked against current docs here (web access denied). The files use `{{.key}}` and a two-file `rawYaml`; the first rollout settles both. The service gains `BGB_IAP_AUDIENCE`, which the current Terraform service lacks, so the described config differs from today by that one variable (empty until Story 5.1). The job keeps `BGB_OBJECT_RETENTION_DAYS`; the service does not set it today and is left as is.

## Verification

**Commands:**
- `terraform -chdir=terraform fmt -check` -- expected: exit 0
- `uv run --extra dev pytest tests/test_deploy_manifests.py` -- expected: pass

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** Added Cloud Deploy delivery pipeline `bgb` and `google_clouddeploy_target` per `deploy_targets` entry (default `prod`, runs as `bgb-deployer`, no approval) in Terraform, with `deploy_stage_order`, `iap_audience` and a `base_deploy_parameters` local. Added `deploy/skaffold.yaml`, `service.yaml` and `job.yaml` reproducing the current runtime settings, with every environment value as a `{{.KEY}}` deploy parameter. `BGB_CORS_ORIGINS` is not set. The service also sets `BGB_IAP_AUDIENCE` (empty until Story 5.1).

**Files changed:**
- `terraform/main.tf`, `terraform/variables.tf`, `terraform/outputs.tf` -- targets, pipeline, parameters, outputs.
- `deploy/skaffold.yaml`, `deploy/service.yaml`, `deploy/job.yaml` -- new manifests.
- `tests/test_deploy_manifests.py` -- text checks tying manifests to Terraform.
- `CI-CD-SETUP.md` -- parameters, release command for Story 8.5, second environment, operator actions.

**Review findings:** 16 rows from one reviewer layer. Patched 3 medium (CORS test matched its own comment, doubled `--skaffold-file` path in the release command, per-target project and region claim). Deferred 5 (release step passing Skaffold config is Story 8.5, test weaknesses, stage order validation, empty parameter acceptance). Rejected 8 with reasons in the Review Triage Log.

**Follow-up review recommended:** false. Three medium patches, no high; all were documentation or test fixes.

**Verification:** Files read by hand only. Not run: `terraform fmt -check` (the implementing subagent could not run it either), `terraform validate`, pytest, any release or rollout. Bash was denied during verification. The A3 spike (one release updating both service and job) is not done, so the A3 check, the post-rollout describe checks and the `terraform plan` check are operator actions.

**Residual risks:**
- `{{.KEY}}` syntax, `skaffold/v4beta7` and two-file `rawYaml` were not checked against current docs (web access denied).
- The story AC that `cloudbuild.yaml` passes the Skaffold config is deferred to Story 8.5.
- The review ran one layer, not four, so findings may be missed.

**Operator actions owed:** see `operator_actions` in the frontmatter.
