---
title: 'Story 8.6: Rollback, documentation and cutover'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: '1296a61a613ab45f978101441a9936ff38e80aa8'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Commit the Story 8.6 changes (CI-CD-SETUP.md, README.md, tests/test_ci_cd_docs.py and this spec file). The run could not commit because Bash was denied.'
  - 'Run uv run --extra dev pytest tests/test_ci_cd_docs.py tests/test_cloudbuild.py tests/test_deploy_manifests.py and fix any failure. Nothing was run.'
  - 'Run uv run --extra dev ruff check src tests and ruff format --check src tests, and format tests/test_ci_cd_docs.py if needed.'
  - 'Complete the Epic 8 operator actions from Stories 8.1 to 8.5 first: extend the landing zone owner_until date, authorise and import the GitHub connection, terraform apply, enable branch protection.'
  - 'Perform the cutover checklist in CI-CD-SETUP.md: merge a no-op change to main, confirm bgb-main creates release sha-SHORT_SHA and rolls out to prod with no manual step, and confirm the service and job image digests match the release.'
  - 'Test the rollback once with gcloud deploy targets rollback prod --delivery-pipeline=bgb --region=REGION --project=PROJECT, confirm the service and job return to the previous release digest, then roll forward. Fix the commands in CI-CD-SETUP.md if gcloud output or flags differ.'
  - 'Record every outcome in the cutover checklist table in CI-CD-SETUP.md, and record the PR build time baseline.'
deferred: []
---

<intent-contract>

## Intent

**Problem:** `CI-CD-SETUP.md` is a set of per-story drafts with no architecture overview, no rollback, no manual fallback, no "which release is live" or first-build troubleshooting. The README "Deploy" section still says Terraform with a `:latest` image is the only deployment path, which contradicts DEP-D1.

**Approach:** Restructure `CI-CD-SETUP.md` into one operator guide, update the README Deploy section, and write the cutover runbook (apply, no-op merge, rollout check, rollback, roll forward). The cutover needs GCP and GitHub access, so the agent writes it and an operator performs and records it.

## Boundaries & Constraints

**Always:** Rollback command is `gcloud deploy targets rollback prod --delivery-pipeline=bgb --region=REGION --project=PROJECT`. The manual fallback uses `gcloud deploy releases create` with an image given as `@sha256:` digest, never `latest`, and carries a warning that it skips the PR tests. README states Terraform owns infrastructure, Cloud Build and Cloud Deploy own the image and runtime configuration, and `terraform apply -var image=...` is bootstrap only. Mark everything not run in this session as unverified. Keep the existing facts in `CI-CD-SETUP.md` (service account table, triggers, branch protection, builder pins, assumptions); reorganise, do not drop.

**Never:** Claim the rollback was tested or that cutover happened. Change Terraform, `cloudbuild.yaml`, `deploy/`, triggers or IAM. Write `sprint-status.yaml`. Set `BGB_CORS_ORIGINS` or add an API token in any example.

</intent-contract>

## Code Map

- `CI-CD-SETUP.md` -- existing per-story sections (service accounts, GitHub connection and triggers, PR path, main path, Cloud Deploy and parameters, second environment, assumptions, DEP-D1). Reorganise and add the missing sections.
- `README.md:71` -- "Deploy" section; first paragraph and the `terraform apply -var image=$IMAGE` block (`IMAGE=...:latest`) need rewording as bootstrap only.
- `cloudbuild.yaml` -- trigger modes, release name `sha-${SHORT_SHA}`, annotations `commit-sha` and `build-id` (read only, for documenting).
- `deploy/` and `terraform/variables.tf` -- `deploy_targets`, `deploy_stage_order`, pipeline `bgb`, target `prod` (read only).
- `tests/test_cloudbuild.py` -- text based test style; add `tests/test_ci_cd_docs.py` the same way.

## Tasks & Acceptance

**Execution:**
- `CI-CD-SETUP.md` -- add an architecture diagram (text or Mermaid: PR, Cloud Build `bgb-pr`, merge, `bgb-main`, Artifact Registry, Cloud Deploy `bgb`, target `prod`, Cloud Run service `bgb` and job `bgb-backup`); a triggers table; running a trigger by hand (`gcloud builds triggers run bgb-main --branch=main --region=REGION`); finding the live release (`gcloud deploy targets describe prod`, `gcloud deploy releases list`, `gcloud run services describe` image digest compared to the release); rollback; manual fallback with the skip-PR-tests warning; troubleshooting the first build; adding an environment; a cutover checklist with outcome fields left "not yet recorded" -- AC1-4
- `README.md` -- rewrite Deploy intro and example so Terraform creates infrastructure with a bootstrap image, Cloud Build and Cloud Deploy deploy later images, and link to `CI-CD-SETUP.md`; drop `:latest` from the example -- AC3
- `tests/test_ci_cd_docs.py` -- text checks: required headings exist, rollback command string present, fallback uses `releases create` and `@sha256:` and the warning, README links `CI-CD-SETUP.md`, mentions bootstrap, and has no `:latest` -- AC1-4

**Acceptance Criteria:**
- Given `CI-CD-SETUP.md`, when read, then it covers the architecture diagram, triggers table, service accounts with a reason per role, the GitHub connection step, running a trigger by hand, finding the live release, troubleshooting the first build and adding an environment.
- Given the guide, when an operator needs to undo a release, then one documented command returns the service and job to the previous release, and the guide says this was not yet tested and lists the test steps.
- Given the README, when read, then Deploy describes the split of ownership (DEP-D1) and calls manual `terraform apply -var image=...` bootstrap only.
- Given the manual fallback section, when read, then it shows `gcloud deploy releases create` with a digest and warns that it skips the PR tests.
- Given the cutover checklist, when the operator runs it, then the first merge deploys to production with no manual step and the live revision digest matches the release (operator action, not verifiable in the repo).

## Spec Change Log

## Review Triage Log

## Design Notes

astro-website's `CI-CD-SETUP.md` is not available in this repository, so structure follows the story's section list. Cloud Deploy rollback creates a new rollout of the previous release's rendered manifests on the target. Terraform ignores service and job templates, so a rollback does not drift Terraform.

## Verification

**Commands:**
- `uv run --extra dev pytest tests/test_ci_cd_docs.py tests/test_cloudbuild.py tests/test_deploy_manifests.py` -- expected: pass
- `uv run --extra dev ruff check src tests && uv run --extra dev ruff format --check src tests` -- expected: pass

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** `CI-CD-SETUP.md` is now one operator guide with an architecture diagram, triggers table, service account roles with reasons, GitHub connection steps, running a trigger by hand, finding the live release, rollback, manual fallback (digest only, warns that it skips the PR tests), first build troubleshooting, adding an environment and a cutover checklist. The README Deploy section now splits ownership per DEP-D1 and calls `terraform apply -var image=...` bootstrap only.

**Files changed:**
- `CI-CD-SETUP.md` -- restructured and extended; existing facts kept.
- `README.md` -- Deploy section rewritten, `:latest` removed, links the guide.
- `tests/test_ci_cd_docs.py` -- text checks on headings, commands, warnings and README wording.

**Review:** No review layers were run. Bash and the review harness were not available in this session (Bash denied in don't-ask mode), so the diff was not staged and no reviewer subagents were launched. The orchestrator read the three delivered files directly and found no defect. Patches applied: 0. Deferred: 0. Rejected: 0.

**Follow-up review recommended:** true. Risk: the docs, tests and gcloud commands were never executed, and no independent review ran.

**Verification:** None run. pytest and ruff were blocked (sandbox cache write, then Bash denied). Tests were checked only by reading them against the document text.

**Residual risks:** gcloud flags and `--format` fields are from memory. The rollback is untested and the cutover has not happened, so the final acceptance criterion is owed by an operator. Nothing was committed.
