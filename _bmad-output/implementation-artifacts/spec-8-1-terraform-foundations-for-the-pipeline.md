---
title: 'Story 8.1: Terraform foundations for the pipeline'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: '1703f812e370186e49079cfc0ff3aaf36c52129b'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Extend the Demo project owner_until date (2026-11-30) with the landing zone owners before applying, per epics.md D10.'
  - 'If an Artifact Registry repository named bgb already exists in aviato-prod-demo-baby-got-back, import it: terraform import google_artifact_registry_repository.bgb projects/aviato-prod-demo-baby-got-back/locations/REGION/repositories/bgb.'
  - 'Run terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate on a machine that can reach registry.terraform.io, and fix anything it reports. This was not run here because the sandbox blocked the provider download.'
  - 'Run terraform plan against the existing deployment with the real variables and confirm no destroy or replace of the Cloud Run service, the job, the bucket or the Firestore database.'
  - 'Run terraform apply, then confirm the six APIs are enabled, the bgb repository exists, and the bgb-cloudbuild and bgb-deployer service accounts exist with no keys.'
deferred:
  - summary: >-
      The Cloud Deploy service agent may need roles/iam.serviceAccountUser on bgb-deployer.
    evidence: |-
      Edge-case reviewer raised it from Cloud Deploy documentation recall; nothing in the repo settles it. The first rollout in Story 8.4 shows whether it is needed. Recorded in CI-CD-SETUP.md.
    location: >-
      terraform/main.tf, bgb-deployer bindings
    severity: medium (unverified)
  - summary: >-
      Cloud Deploy may write labels, annotations or traffic settings that Terraform then reports as drift on the service and job.
    evidence: |-
      ignore_changes covers template, client and client_version only. A terraform plan after the first rollout (Story 8.4) shows whether more fields are needed. Recorded in CI-CD-SETUP.md.
    location: >-
      terraform/main.tf, lifecycle blocks
    severity: medium (unverified)
  - summary: >-
      bgb-cloudbuild may need storage access for the Cloud Deploy artifacts bucket when it creates a release.
    evidence: |-
      Already listed as an assumption in CI-CD-SETUP.md. The first main build in Story 8.5 shows whether releases fail with a storage 403.
    location: >-
      terraform/main.tf, bgb-cloudbuild bindings
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** The pipeline in Epic 8 has no registry, no build or deploy identities, and the APIs it needs are not enabled. Terraform also owns the Cloud Run image and runtime config, which would fight Cloud Deploy (DEP-D1).

**Approach:** Extend `terraform/` with the APIs, an Artifact Registry repo, `bgb-cloudbuild` and `bgb-deployer` accounts with least-privilege IAM, a Cloud Quotas viewer grant, and `ignore_changes` on the service and job templates with a public bootstrap image default.

## Boundaries & Constraints

**Always:** No service account keys. Every role is the narrowest scope that works (resource level over project level). Existing resources are not destroyed or replaced. Match the style of `terraform/main.tf`. Record DEP-D1 in a comment beside the lifecycle blocks. Document each role and its reason in `CI-CD-SETUP.md`.

**Never:** Triggers, GitHub connection, Cloud Deploy pipeline, `cloudbuild.yaml`, Dockerfile or README changes (Stories 8.2 to 8.6). Do not run `terraform apply`. Do not touch `sprint-status.yaml`.

</intent-contract>

## Code Map

- `terraform/main.tf` -- `local.services` (line 30) lists enabled APIs; `local.app_accounts` maps `run`/`ui` to the two app SAs; `google_cloud_run_v2_service.ui` (line 191, runs as `bgb-ui`) and `google_cloud_run_v2_job.backup` (line 247, runs as `bgb-run`) use `var.image` and carry the template to be ignored.
- `terraform/variables.tf` -- `image` has no default; needs a public bootstrap default.
- `terraform/outputs.tf` -- already outputs `backup_job` (full path), `bucket`, `runtime_service_account`, `ui_service_account`; add registry path and the two pipeline SAs.
- `CI-CD-SETUP.md` -- does not exist; Story 8.6 expands it. Create it now with the service account and role table only.

## Tasks & Acceptance

**Execution:**
- `terraform/main.tf` -- add `cloudbuild`, `clouddeploy`, `iamcredentials`, `containerscanning`, `cloudquotas` APIs to `local.services` -- AC1
- `terraform/main.tf` -- add `google_artifact_registry_repository.bgb` (DOCKER, `var.region`, cleanup policies: KEEP most recent 20 tagged versions, DELETE other tagged versions) -- AC3
- `terraform/main.tf` -- add `bgb-cloudbuild` and `bgb-deployer` accounts; bind: cloudbuild gets `logging.logWriter`, `clouddeploy.releaser` (project), `artifactregistry.writer` (repo), `serviceAccountUser` on `bgb-deployer`; deployer gets `clouddeploy.jobRunner` (project), `run.developer` on the `bgb` service and `bgb-backup` job, `artifactregistry.reader` (repo), `serviceAccountUser` on both app SAs only -- AC4, AC5
- `terraform/main.tf` -- grant `roles/cloudquotas.viewer` to the runtime SA -- AC2
- `terraform/main.tf` -- add `lifecycle { ignore_changes = [template, client, client_version] }` to the service and job with a DEP-D1 comment -- AC6
- `terraform/variables.tf` -- default `image` to `us-docker.pkg.dev/cloudrun/container/hello` -- AC6
- `terraform/outputs.tf` -- add registry path, cloudbuild and deployer SA emails, service name, job id -- task 5
- `CI-CD-SETUP.md` -- service account and role table with a reason per role, plus the assumptions to verify in 8.4/8.5 -- AC4

**Acceptance Criteria:**
- Given the Terraform in `terraform/`, when `terraform fmt -check` and `terraform validate` run, then both pass.
- Given the diff, when read, then no key resources exist and no resource is replaced by a rename or `for_each` change.
- Given an operator with project access, when they run `terraform plan` against the existing deployment, then it shows no destroy or replace of the service, job, bucket or Firestore database (operator verification).

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 30 findings — high 0, medium 3, low 13, false 9, maybe-false 5
- note: the first launch of the edge-case and verification-gap layers could not read the diff in the system temp directory and reported nothing reviewable; both were relaunched with the diff in the scratchpad and only the relaunch reports are logged. The intent-alignment layer is descriptive and filed no defects.
- findings:
  - `[medium]` `[patch]` Blind: delete policy has no age condition, so tagged images beyond the newest 20 go at once — added `older_than = "2592000s"` (30 days) and renamed the policy `delete-old-tagged`.
  - `[medium]` `[patch]` Edge: same defect (deployed or rollback image removed once 20 newer builds exist) — fixed by the same change.
  - `[medium]` `[patch]` Verification gap: same defect, and `cleanup_policy_dry_run = false` makes it live — fixed by the same change; dry run left off because the AC requires the policy.
  - `[low]` `[reject]` Blind: no untagged cleanup rule — the AC covers tagged images only, and digests are deployed from tagged builds; adding a rule adds scope.
  - `[low]` `[reject]` Edge: same untagged point — same reason.
  - `[low]` `[patch]` Edge: KEEP policy counts all tag states — the provider does not allow a tag filter on `most_recent_versions`; documented in `CI-CD-SETUP.md`.
  - `[low]` `[patch]` Verification gap: same KEEP count point — same documentation fix.
  - `[low]` `[patch]` Edge: doc claim "narrowest scope that works" overstated for project-only roles — reworded in `CI-CD-SETUP.md`.
  - `[false]` `[reject]` Blind: `ignore_changes` hides every runtime setting — that is DEP-D1 and the AC ("or the narrowest set that lets Cloud Deploy own image, env and resources"); recorded in the doc.
  - `[false]` `[reject]` Edge: same claim about silent no-op edits — same refutation.
  - `[false]` `[reject]` Verification gap: same claim — same refutation.
  - `[maybe-false]` `[defer]` Blind: deployer cannot read the Cloud Deploy artifacts bucket or act for the service agent — settled by the first rollout in Story 8.4; deferred as medium (unverified).
  - `[maybe-false]` `[defer]` Edge: Cloud Deploy service agent actAs on `bgb-deployer` — same, deferred.
  - `[maybe-false]` `[defer]` Edge: `bgb-cloudbuild` storage access for the Cloud Deploy bucket — settled by the first main build in Story 8.5; deferred.
  - `[maybe-false]` `[defer]` Edge: labels, annotations or traffic need `ignore_changes` — settled by a plan after the first rollout; deferred.
  - `[false]` `[reject]` Blind: hello bootstrap image may fail the service and the scheduled job — the hello image serves on `$PORT` (8080), so the service starts; the job failure is accepted in the spec's Design Notes.
  - `[false]` `[reject]` Edge: first apply fails because the hello revision is never ready — same refutation.
  - `[low]` `[reject]` Blind: pause the scheduler until the first release — out of the story's task list, and the failure window is accepted in the spec.
  - `[low]` `[reject]` Edge: add validation that rejects the hello default — added guard for a case the operator controls; not worth the complexity.
  - `[low]` `[reject]` Edge: a stale `-var image=` is ignored silently — follows from DEP-D1; the variable description now says so.
  - `[false]` `[reject]` Blind: `for_each` map uses values known only after apply — keys are static, so `for_each` is valid at plan time.
  - `[false]` `[reject]` Blind: scanning API enabled with nothing using it — the AC lists Container Scanning explicitly.
  - `[false]` `[reject]` Blind: quota viewer is granted early — the AC grants it in this story.
  - `[low]` `[reject]` Blind: outputs lack descriptions — the existing outputs have none; cosmetic.
  - `[low]` `[reject]` Edge: `backup_job` and `backup_job_id` overlap — the spec asks for the job id output; the existing one is the full path. Harmless.
  - `[low]` `[reject]` Blind: `CI-CD-SETUP.md` lacks rollback, approvals and log retention — those belong to Story 8.6, which expands this file.
  - `[low]` `[reject]` Blind: no tests or validation — the repo has no Terraform test harness; recorded as a residual risk and an operator action.
  - `[maybe-false]` `[defer]` Edge: the `bgb` repository may already exist and need an import — settled by the first plan; moved to operator actions and the doc.
  - `[false]` `[reject]` Edge: quota grant has no `depends_on` on the API — IAM bindings do not need the API enabled, and the account is created in the same apply.
  - `[low]` `[reject]` Verification gap: no automated Terraform checks exist in the repo — config only; the checks are `fmt` and `validate`, with `validate` owed to the operator.

## Design Notes

- The service runs as `bgb-ui` and the job as `bgb-run`, so `bgb-deployer` needs `serviceAccountUser` on both. The AC says "the runtime service account"; both app accounts are read as that, and no other account.
- A fresh apply uses the hello image, which has no `python`, so the scheduled job fails until the first release. Accepted; Cloud Deploy replaces it in 8.5.
- Resource-level `run.developer` and the deploy artifacts bucket access are assumptions for Story 8.4 to verify (Epic 8 A3).

## Verification

**Commands:**
- `terraform -chdir=terraform fmt -check` -- expected: no output, exit 0
- `terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate` -- expected: Success

**Manual checks (if no CLI):**
- Operator runs `terraform plan` with real variables and confirms no destroy or replace of existing resources.

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** Terraform now enables the Cloud Build, Cloud Deploy, IAM Credentials, Container Scanning and Cloud Quotas APIs, creates the `bgb` Artifact Registry repository, and creates the `bgb-cloudbuild` and `bgb-deployer` service accounts with scoped IAM. The runtime account can read quotas. The service and job ignore `template`, `client` and `client_version` (DEP-D1), and `image` defaults to a public bootstrap image.

**Files changed:**
- `terraform/main.tf` -- APIs, registry with cleanup policies, two service accounts and their bindings, quota viewer, lifecycle blocks.
- `terraform/variables.tf` -- `image` defaults to the Cloud Run hello image.
- `terraform/outputs.tf` -- registry path, cloudbuild and deployer emails, service name, job id.
- `CI-CD-SETUP.md` -- new draft with the role table, reasons and assumptions.
- `_bmad-output/implementation-artifacts/epic-8-context.md` -- compiled epic context.

**Review findings:** 30 reported. Patches applied: 4 (age condition on the delete cleanup policy, KEEP count behaviour documented, role scope wording, plus the registry import note). Deferred: 3 unverified IAM and drift questions for Stories 8.4 and 8.5. Every rejected finding and its reason is in the Review Triage Log.

**Follow-up review recommended:** false. No high finding was patched and fewer than two mediums were patched as separate causes.

**Verification:**
- `terraform -chdir=terraform fmt -check` passed, before and after the review patches.
- `terraform init -backend=false` failed: the sandbox blocked registry.terraform.io, so `terraform validate` did not run. This is owed to the operator.
- The no destroy or replace plan check needs project access and was not run.

**Residual risks:**
- The Terraform has not been validated against the provider schema. The cleanup policy blocks and the `client` and `client_version` ignore entries are the likeliest places for an error.
- The IAM grants for Cloud Deploy and the artifacts bucket are assumptions until Story 8.4 and 8.5 run a real rollout.
- A fresh apply uses the hello image, so the scheduled backup job fails until the first release.
- Only `terraform fmt` and a manual diff read checked the change.

**Operator actions owed:** see `operator_actions` in the frontmatter.
