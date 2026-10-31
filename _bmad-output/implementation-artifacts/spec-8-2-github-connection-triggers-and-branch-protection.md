---
title: 'Story 8.2: GitHub connection, triggers and branch protection'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: 'ce2b1903e4d24622a16bf2bf3a9321834e58991e'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Commit the Story 8.2 changes (terraform/main.tf, terraform/variables.tf, terraform/outputs.tf, CI-CD-SETUP.md and the spec file). The run could not commit because Bash was denied.'
  - 'Run terraform -chdir=terraform fmt -check, then terraform init -backend=false and terraform validate on a machine that can reach registry.terraform.io, and fix anything reported. Neither was run after the review patches, and validate was never run.'
  - 'In the Cloud Build console (Repositories, 2nd gen), create a GitHub host connection named bgb-github in the Terraform region and install the Cloud Build GitHub App on benking84/bgb only, as described in CI-CD-SETUP.md.'
  - 'Import the connection into Terraform with terraform import google_cloudbuildv2_connection.github projects/PROJECT/locations/REGION/connections/bgb-github, then run terraform plan and terraform apply.'
  - 'Run gcloud builds triggers list --region=REGION --project=PROJECT and confirm bgb-pr and bgb-main exist.'
  - 'After Story 8.3 adds cloudbuild.yaml, open a test PR, read the exact bgb-pr check name, then set branch protection on main from CI-CD-SETUP.md (require that check, require up to date branches).'
deferred:
  - summary: >-
      Any repository collaborator can change cloudbuild.yaml in a PR and run it as bgb-cloudbuild, which holds release and image push rights.
    evidence: |-
      Both triggers run as bgb-cloudbuild by the story's own acceptance criteria, and guard-release in Story 8.5 keys on BRANCH_NAME, which for PR triggers is likely the base branch. Whether a separate low-privilege PR account is needed is a design decision for Stories 8.3 and 8.5. Recorded in CI-CD-SETUP.md.
    location: >-
      terraform/main.tf, google_cloudbuild_trigger.pr service_account
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** Nothing starts a build when a PR opens or `main` moves, and nothing stops an untested or stale PR from merging. `main` does not retest (Epic 8 risk A1), so the PR check must be enforced.

**Approach:** Add a 2nd gen Cloud Build GitHub connection and repository link, the `bgb-pr` and `bgb-main` triggers in Terraform, and document the one console step (OAuth), the import, and the GitHub branch protection settings in `CI-CD-SETUP.md`.

## Boundaries & Constraints

**Always:** Triggers run as `bgb-cloudbuild` in `var.region`. `bgb-pr` uses `_MODE=pr` with `comment_control = COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY`, so outside contributors need a maintainer comment. `bgb-main` uses `_MODE=main`, branch `^main$`. The connection is created in the console, imported, and Terraform ignores `github_config` so the OAuth credentials stay out of state diffs. Match the style of `terraform/main.tf`. Do not store tokens in the repo.

**Never:** `cloudbuild.yaml`, Dockerfile, Cloud Deploy pipeline or README changes (Stories 8.3 to 8.6). Do not run `terraform apply` or change GitHub settings from here. Do not touch `sprint-status.yaml`.

</intent-contract>

## Code Map

- `terraform/main.tf` -- ends with the Epic 8 block; `google_service_account.cloudbuild` is the trigger identity; `var.region` and `var.project_id` give location and project.
- `terraform/variables.tf` -- add GitHub connection name and repository URI variables.
- `terraform/outputs.tf` -- add connection and trigger names.
- `CI-CD-SETUP.md` -- created in 8.1 with the role table; add the connection, trigger and branch protection sections. The logging role a user-specified build account needs is already granted in 8.1.

## Tasks & Acceptance

**Execution:**
- `terraform/variables.tf` -- add `github_connection_name` (default `bgb-github`) and `github_repository_uri` (default `https://github.com/benking84/bgb.git`) -- AC1
- `terraform/main.tf` -- add `google_cloudbuildv2_connection.github` (empty `github_config`, `ignore_changes = [github_config]`) and `google_cloudbuildv2_repository.bgb` -- AC1
- `terraform/main.tf` -- add `google_cloudbuild_trigger.pr` (`pull_request` on `^main$`, `comment_control = COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY`, `_MODE=pr`) and `google_cloudbuild_trigger.main` (`push` on `^main$`, `_MODE=main`), both `cloudbuild.yaml`, as `bgb-cloudbuild`, -- AC2, AC3, AC5
- `terraform/outputs.tf` -- add trigger names and connection name -- AC2
- `CI-CD-SETUP.md` -- OAuth console steps and `terraform import` commands, trigger table, branch protection settings with a `gh api` command, verification steps, assumptions -- AC1, AC4

**Acceptance Criteria:**
- Given `terraform/`, when `terraform fmt -check` runs, then it passes; `terraform validate` is owed to an operator with provider access.
- Given the Terraform, when read, then both triggers use `bgb-cloudbuild`, `cloudbuild.yaml`, the right `_MODE`, and `bgb-pr` requires a maintainer comment only for external contributors.
- Given `CI-CD-SETUP.md`, when an operator follows it, then they can authorise the connection, import it, apply, set branch protection requiring the `bgb-pr` check and an up-to-date branch, and confirm with `gcloud builds triggers list` and one test PR (operator verification).

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 34 findings — high 0, medium 3, low 12, false 7, maybe-false 12
- note: verdicts are grouped by root cause below rather than listed one row per raw reviewer line; the reviewers raised overlapping points.
- findings:
  - `[medium]` `[patch]` Blind and Edge: applying branch protection before `cloudbuild.yaml` exists makes the required check fail and blocks every merge, including the Story 8.3 PR — added an ordering warning to `CI-CD-SETUP.md`.
  - `[medium]` `[patch]` Blind and Edge: applying before the console step and import creates a second unauthorised connection — added an ordering warning and a custom name note to `CI-CD-SETUP.md`.
  - `[low]` `[patch]` Blind and Edge: the doc overstated that credentials stay out of state — reworded to say state still holds the connection metadata.
  - `[low]` `[patch]` Blind and Edge: the `gh api` payload omitted force push and deletion settings that a PUT resets — added `allow_force_pushes` and `allow_deletions` as false.
  - `[low]` `[patch]` Blind and Edge: `enforce_admins` with 0 approvals had no break-glass and no reason — documented both.
  - `[low]` `[patch]` Edge: Dependabot PRs wait for a `/gcbrun` comment and stay pending — documented.
  - `[medium]` `[defer]` Blind: a collaborator's PR can rewrite `cloudbuild.yaml` and run it as `bgb-cloudbuild` — the story requires both triggers to run as that account, and the guard design belongs to 8.3 and 8.5; deferred as medium (unverified), noted in the doc.
  - `[low]` `[reject]` Blind and Edge: add a `precondition` on connection state — adds complexity; the ordering warning covers the case.
  - `[low]` `[reject]` Blind and Edge: set `disabled = true` on triggers until 8.3 — the ordering warning covers it and the operator controls when to apply.
  - `[low]` `[reject]` Blind and Edge: path filters on triggers — `main` should release on every merge and a filter could leave the required check never reporting.
  - `[low]` `[reject]` Blind: `.git` validation, import and destroy notes, provider pin, hardcoded personal repo default, extra outputs — cosmetic or covered by the existing assumptions list.
  - `[false]` `[reject]` Blind: triggers lack a Cloud Build API dependency — the connection depends on the service resource, the repository on the connection and the triggers on the repository.
  - `[false]` `[reject]` Edge: build rejected for missing logging option — `CLOUD_LOGGING_ONLY` is set in `cloudbuild.yaml` by Stories 8.3 and 8.5 per the epic, not here.
  - `[false]` `[reject]` Edge: `_MODE` undeclared in `cloudbuild.yaml` — the file does not exist yet and Story 8.3 declares it.
  - `[maybe-false]` `[reject]` Blind: Cloud Build service agent may lack Secret Manager access to the token secret — the console flow grants it; a low-impact setup note at most.
  - `[maybe-false]` `[reject]` Edge and Blind: the real check name for `bgb-pr` may differ — already handled by an operator step that reads the name from a test PR before enabling protection.
  - `[false]` `[reject]` Verification gap: no automated checks — none exist for Terraform in this repo; `fmt` and `validate` are listed as operator actions.
  - `[false]` `[reject]` Intent audit: descriptive only and filed no defects.

## Design Notes

- `COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY` lets owners and collaborators run PR builds unprompted and holds everyone else until an owner or collaborator comments `/gcbrun`. `COMMENTS_ENABLED` would also gate the maintainer's own PRs, which adds friction without more safety.
- Branch protection is a GitHub setting, not Terraform: the repo has no GitHub provider and adding one needs a token, which this epic avoids.

## Verification

**Commands:**
- `terraform -chdir=terraform fmt -check` -- expected: no output, exit 0

**Manual checks (if no CLI):**
- Operator authorises the connection, runs `terraform plan`, applies, sets branch protection, opens a test PR and sees the `bgb-pr` check.

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** Terraform now declares the 2nd gen GitHub connection (imported after a console OAuth step, `github_config` ignored), the `bgb` repository link, and triggers `bgb-pr` (pull requests to `^main$`, `_MODE=pr`, maintainer comment required for external contributors) and `bgb-main` (pushes to `^main$`, `_MODE=main`). Both run `cloudbuild.yaml` as `bgb-cloudbuild`. `CI-CD-SETUP.md` documents the console step, import, triggers, branch protection settings with a `gh api` command, and operator verification.

**Files changed:**
- `terraform/main.tf` -- connection, repository link and the two triggers.
- `terraform/variables.tf` -- `github_connection_name` and `github_repository_uri`.
- `terraform/outputs.tf` -- connection and trigger names.
- `CI-CD-SETUP.md` -- GitHub connection, trigger and branch protection sections, ordering warnings and assumptions.

**Review findings:** 34 reported. Patches applied: 6, all documentation (3 medium root causes counted as 2 entries plus 4 low). Deferred: 1 (collaborator PR runs `cloudbuild.yaml` as `bgb-cloudbuild`, medium unverified). The rest are rejected with reasons in the Review Triage Log.

**Follow-up review recommended:** false. No high finding was patched and the two medium patches were documentation ordering warnings.

**Verification:**
- `terraform -chdir=terraform fmt -check` passed on the implementation before the review patches. The review patches touched only `CI-CD-SETUP.md`.
- `terraform validate` was not run (no provider access). Branch protection, the connection and the test PR need the operator.
- Bash was denied for the rest of the run, so the changes are NOT committed and the working tree is not clean.

**Residual risks:**
- The HCL has not been validated against the provider. `repository_event_config`, `comment_control` and the `service_account` path format are the likeliest places for an error.
- The `bgb-pr` check name is unknown until the first test PR.
- Triggers fail until Story 8.3 adds `cloudbuild.yaml`.

**Operator actions owed:** see `operator_actions` in the frontmatter.
