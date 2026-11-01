---
title: 'Story 8.5: Main path: build once, push and create a release'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: 'c89ab4f8bd30713d3ea8e956c15c581b56f9ad42'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Commit the Story 8.5 changes (cloudbuild.yaml, Dockerfile, tests/test_cloudbuild.py, CI-CD-SETUP.md and this spec file). The run could not commit because Bash was denied.'
  - 'Run uv run --extra dev pytest tests/test_cloudbuild.py tests/test_deploy_manifests.py and fix any failure. Nothing was run.'
  - 'Run uv run --extra dev ruff check src tests and ruff format --check src tests, and format tests/test_cloudbuild.py if needed.'
  - 'Run docker build . locally and confirm the image starts with python -m bgb serve, so the uv venv copied from the pybuild stage works in the runtime stage.'
  - 'Confirm the builder tag gcr.io/google.com/cloudsdktool/cloud-sdk:502.0.0-slim resolves and that gcloud deploy releases create accepts --annotations. Change the pin if either fails.'
  - 'On the first merge to main, confirm read-digest finds RepoDigests after the push, that $BRANCH_NAME is main on the push trigger, and that gcloud deploy releases list --delivery-pipeline=bgb shows sha-SHORT_SHA with commit-sha and build-id annotations.'
deferred:
  - summary: >-
      Re-running a main build for the same commit fails at create-release because the release name sha-SHORT_SHA already exists.
    evidence: |-
      The release name is derived only from SHORT_SHA, as the story specifies. Documented in CI-CD-SETUP.md.
    location: >-
      cloudbuild.yaml
    severity: low
---

<intent-contract>

## Intent

**Problem:** A merge to `main` runs `cloudbuild.yaml` with every step skipped, so nothing is built, pushed or released. The Dockerfile also runs an unpinned `pip install .`, so the image on `main` can differ from what the PR tested (risk A2).

**Approach:** Add main-path steps to `cloudbuild.yaml`: build and push the image tagged by commit SHA, read its digest, guard the release, and create a Cloud Deploy release on pipeline `bgb` that references the image by digest. Make the Dockerfile install from `uv.lock`.

## Boundaries & Constraints

**Always:** Image path is `${_REGION}-docker.pkg.dev/${PROJECT_ID}/bgb/bgb:${COMMIT_SHA}`. Never use `latest`. Release name `sha-${SHORT_SHA}`, image passed as `bgb=<image>@sha256:<digest>`, annotations carry commit SHA and build ID, source is `deploy/`. `guard-release` fails unless `_MODE` and `$BRANCH_NAME` are both `main`. Main path runs no tests. PR path keeps building without pushing. Builder images pinned to exact versions with a comment on why. `options.logging: CLOUD_LOGGING_ONLY` and a build timeout stay.

**Never:** Run tests on `main`. Push from a PR build. Change Terraform, `deploy/` manifests, triggers or IAM. Write `sprint-status.yaml`.

</intent-contract>

## Code Map

- `cloudbuild.yaml` -- `_MODE` switch, PR steps, `build-image` currently PR only (`bgb:pr-check`). Add `_REGION`, push, digest, guard and release.
- `Dockerfile` -- Python stage runs `pip install .` (unlocked). Replace with a uv build stage using `uv.lock`.
- `CI-CD-SETUP.md` -- lines ~91-96 describe `main` as skip only; line ~135 has the release command; assumptions list mentions 8.5. Update.
- `terraform/main.tf:359` -- Artifact Registry repo `bgb`; `bgb-cloudbuild` already has writer and `clouddeploy.releaser`; no change.
- `tests/test_deploy_manifests.py` -- text based test style, no YAML dependency; add `tests/test_cloudbuild.py` the same way.

## Tasks & Acceptance

**Execution:**
- `Dockerfile` -- build the virtualenv in a uv image stage with `uv sync --locked --no-dev --no-editable`, copy it into the runtime stage and put it on `PATH` -- AC image uses locked versions
- `cloudbuild.yaml` -- add `_REGION` (default `us-central1`), `build-image` push path on main, `read-digest`, `guard-release`, `create-release`; the guard runs before any push -- AC1-4
- `tests/test_cloudbuild.py` -- text checks: no `latest`, image path, `@sha256:`, guard conditions, release flags and annotations, no test command outside `_MODE != pr` skip guards -- AC1-4
- `CI-CD-SETUP.md` -- document the main path, builder image table additions, two close merges behaviour, and unverified items -- AC5

**Acceptance Criteria:**
- Given `_MODE=main` on branch `main`, when the build runs, then the image is built once, pushed as `...:${COMMIT_SHA}`, and the release references it by `@sha256:` digest read after the push.
- Given `_MODE` is not `main` or `$BRANCH_NAME` is not `main`, when the build runs, then `guard-release` fails before any push or release.
- Given a release, when created, then it is named `sha-${SHORT_SHA}` on pipeline `bgb` with commit SHA and build ID annotations.
- Given two merges close together, when both builds finish, then two releases exist and Cloud Deploy rolls out the later one last.
- Given the Dockerfile, when read, then Python dependencies install from `uv.lock`, not an unpinned `pip install .`.

## Spec Change Log

## Review Triage Log

### 2026-10-31 Review pass
- verdicts: no subagent review layers ran. Bash was denied, so no diff file could be written. The author read `cloudbuild.yaml` and `Dockerfile` directly against the acceptance criteria.
- note: `guard-release` skips on `_MODE=pr` (otherwise every PR build would fail it) and fails any main build unless `_MODE` and `$BRANCH_NAME` are both `main`. This is a reading of the story, not a stated rule.
- note: `$BRANCH_NAME` is a Cloud Build substitution, so it is substituted before the shell runs. Correct as written.

## Design Notes

The guard runs right after `validate-mode`, before install and build, so a misconfigured trigger never pushes. Cloud Build substitutes `${...}`; shell variables use `$$`. Steps share `/workspace`, so the digest file passes between steps. Cloud Deploy queues rollouts per target in release order, so the later release is deployed last.

## Verification

**Commands:**
- `uv run --extra dev pytest tests/test_cloudbuild.py tests/test_deploy_manifests.py` -- expected: pass
- `uv run --extra dev ruff check src tests && uv run --extra dev ruff format --check src tests` -- expected: exit 0

**Manual checks (if no CLI):**
- First `main` build: `gcloud deploy releases list --delivery-pipeline=bgb` shows `sha-<short sha>` with annotations.

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** `cloudbuild.yaml` now has a main path: `guard-release` (before any install or push), `build-image` (push as `${_REGION}-docker.pkg.dev/${PROJECT_ID}/bgb/bgb:${COMMIT_SHA}` on main, check-only on PR), `read-digest` (writes `/workspace/image-digest`) and `create-release` (`sha-${SHORT_SHA}` on pipeline `bgb`, `--source=deploy`, image by `@sha256:` digest, `commit-sha` and `build-id` annotations). The Dockerfile builds its virtualenv from `uv.lock` in a uv stage and copies it into the runtime stage. `_REGION` defaults to `us-central1`.

**Files changed:** `cloudbuild.yaml`, `Dockerfile`, `tests/test_cloudbuild.py` (new), `CI-CD-SETUP.md`, this spec.

**Verification:** Nothing was run. Bash was denied in this session (pytest, ruff, docker build, commit). Files were read by hand only. Review was a single author read, not the multi-layer review.

**Residual risks:** the `cloud-sdk:502.0.0-slim` tag, `--annotations` flag, `RepoDigests` after push, and the venv carrying over between Dockerfile stages are unverified. Re-running a build for the same commit fails at `create-release`.

**Follow-up review recommended:** true, because no tests ran and review was reduced.

**Operator actions owed:** see `operator_actions` in the frontmatter.
