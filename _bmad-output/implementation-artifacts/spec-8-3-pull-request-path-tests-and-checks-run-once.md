---
title: 'Story 8.3: Pull request path: tests and checks, run once'
type: 'feature'
created: '2026-10-31'
status: 'awaiting-operator'
baseline_revision: 'a34e05a86a2eab2abf13240aef16aab072934947'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
operator_actions:
  - 'Run uv lock in the repo root and commit the updated uv.lock. ruff was added to the dev extra, and until the lock includes it uv sync --locked fails every PR build.'
  - 'Run uv run --extra dev ruff check src tests and uv run --extra dev ruff format --check src tests, then fix or baseline findings so the gate starts green. Neither was run.'
  - 'Run uv run --extra dev pytest and (cd web && npm ci && npm run lint && npm run build) to confirm the PR checks pass locally. None of these were run in this session.'
  - 'Confirm each pinned builder tag resolves: ghcr.io/astral-sh/uv:0.13.6-python3.12-bookworm-slim, node:22.12.0-bookworm-slim, hashicorp/terraform:1.14.6, gcr.io/cloud-builders/docker:24.0.9. Change any that do not exist.'
  - 'Run terraform -chdir=terraform init -backend=false and terraform validate on a machine with provider access, and consider committing terraform/.terraform.lock.hcl.'
  - 'After Story 8.2 is applied, open a test PR, confirm bgb-pr runs all steps and fails on a deliberate error, merge and confirm bgb-main shows every step skipped, then record the PR build time in CI-CD-SETUP.md as the Epic 1 baseline.'
  - 'Commit the Story 8.3 changes (cloudbuild.yaml, pyproject.toml, CI-CD-SETUP.md and this spec file) if the run could not.'
deferred:
  - summary: >-
      terraform init resolves provider versions fresh on every PR build because no .terraform.lock.hcl is committed.
    evidence: |-
      terraform/ holds no lock file and .gitignore excludes only .terraform/. A new provider release could change validate results with no repo change. Pre-existing from Story 8.1; fix is to commit the lock file after an init with provider access.
    location: >-
      terraform/, cloudbuild.yaml test-pr-only-terraform
    severity: low
  - summary: >-
      The four builder image tags were not pulled, so one may not exist.
    evidence: |-
      Versions were taken from local tool versions and known release lines. A missing tag fails every PR build at the first pull. Settled by pulling or running the first real build.
    location: >-
      cloudbuild.yaml
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** The `bgb-pr` and `bgb-main` triggers from Story 8.2 point at a `cloudbuild.yaml` that does not exist. Nothing runs the tests, lint or Terraform checks, and `main` must not retest.

**Approach:** Add `cloudbuild.yaml` with a `_MODE` substitution (`pr` or `main`, default `main`). In `pr` mode it installs locked dependencies, runs Python, web and Terraform checks, and builds the image without pushing it. In `main` mode every test step prints a skip message and runs nothing.

## Boundaries & Constraints

**Always:** Builder images pinned to exact versions, each with a comment on why. `uv sync --locked` so a `uv.lock` that disagrees with `pyproject.toml` fails the PR. Any failing command fails the build. `options.logging: CLOUD_LOGGING_ONLY` and a build `timeout`. Record the PR build time baseline in the story notes once a real build exists.

**Never:** Pushing images, `guard-release`, `create-release` or Cloud Deploy (Stories 8.4 and 8.5). Dockerfile changes (Story 8.5). Terraform trigger changes. Branch protection. `sprint-status.yaml`. Caching, unless PR builds exceed 10 minutes.

</intent-contract>

## Code Map

- `terraform/main.tf` -- triggers `bgb-pr` and `bgb-main` already pass `_MODE` as `pr` and `main`; the file must declare both substitutions.
- `pyproject.toml` -- `dev` extra holds `httpx` and `pytest`; `ruff` is missing. `uv.lock` has no `ruff` entry, so the lock must be regenerated.
- `web/package.json` -- scripts `lint` (`eslint`) and `build` (`next build`); `web/package-lock.json` exists for `npm ci`.
- `terraform/` -- `main.tf`, `variables.tf`, `outputs.tf`; no `.terraform.lock.hcl`.
- `Dockerfile` -- two stage build, built on PRs only to check it.
- `CI-CD-SETUP.md` -- add a section on the PR path, builders and the baseline.

## Tasks & Acceptance

**Execution:**
- `cloudbuild.yaml` -- new; steps `validate-mode`, `install-deps-python`, `install-deps-web`, `test-pr-only`, `test-pr-only-web`, `test-pr-only-terraform`, `build-image`; substitution `_MODE`; logging and timeout -- AC1 to AC6
- `pyproject.toml` -- add `ruff` to the `dev` extra -- AC2
- `CI-CD-SETUP.md` -- document modes, builders and why, the lock refresh, and the baseline placeholder -- AC7

**Acceptance Criteria:**
- Given `_MODE=pr`, when the build runs, then `uv run pytest`, `ruff check` and `ruff format --check` on `src` and `tests`, `npm run lint` and `npm run build` in `web/`, and `terraform fmt -check` and `terraform validate` after `terraform init -backend=false` all run, and any failure fails the build.
- Given `_MODE=pr`, when the image step runs, then the Dockerfile is built and nothing is pushed.
- Given `_MODE=main`, when the build runs, then each test step prints a skip message and no test command runs.
- Given `cloudbuild.yaml`, when read, then every builder image carries an exact version and a comment saying why.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 17 findings — high 0, medium 2, low 10, false 3, maybe-false 2
- note: the four reviewers raised about 30 raw lines; rows are grouped by root cause because they overlapped heavily.
- findings:
  - `[medium]` `[patch]` Blind and Edge: default `_MODE=main` makes a mistyped or missing value skip every step and pass the required check — added a `validate-mode` step that fails on anything but `pr` or `main`, and documented it.
  - `[medium]` `[defer]` Blind, Edge, Verification gap and Intent: `ruff` is in `pyproject.toml` but not `uv.lock`, so `uv sync --locked` fails the first PR build — cannot be fixed here because `uv lock` was denied; listed first in `operator_actions` (not a code patch).
  - `[maybe-false]` `[defer]` Blind and Edge: pinned image tags unverified, `cloud-builders/docker:24.0.9` and Node 22.12.0 least certain — deferred as medium unverified; a pull or the first build settles it.
  - `[low]` `[defer]` Edge and Verification gap: no `.terraform.lock.hcl`, provider versions float — pre-existing from 8.1; deferred.
  - `[low]` `[reject]` Blind and Edge: `terraform fmt -check` without `-recursive` — `terraform/` has three flat files and no modules.
  - `[maybe-false]` `[reject]` Blind and Edge: serial steps may exceed the 15 minute budget; no step timeouts; web built twice — the story says to add caching only if builds exceed 10 minutes, and the baseline is owed to the first real build.
  - `[false]` `[reject]` Blind: BuildKit-only Dockerfile syntax — the Dockerfile uses none.
  - `[false]` `[reject]` Blind and Intent: triggers do not set `_MODE` — `terraform/main.tf` lines 500 to 502 and 522 to 524 set `pr` and `main`.
  - `[low]` `[reject]` Blind: no `[tool.ruff]` configuration — defaults are acceptable for a gate that starts green after an operator run.
  - `[low]` `[reject]` Edge: skip guard precedes `set -euo pipefail` — each step runs one command or sets it before the commands.
  - `[low]` `[reject]` Edge: spec lists `_REGION` but the file has none — unused until 8.5; the spec Execution line was updated and the unused substitution removed.
  - `[low]` `[reject]` Edge: Dockerfile floating tags differ from pinned CI tags — Dockerfile changes belong to Story 8.5.
  - `[low]` `[reject]` Verification gap: integration tests skip without the emulator, so a green PR does not cover Firestore — Epic 1 adds emulator integration to this path.
  - `[low]` `[reject]` Blind and Intent: no automated test of `cloudbuild.yaml` — YAML parse was checked once; a real build is the meaningful test.
  - `[low]` `[reject]` Intent: `main` mode still pulls images before skipping — the story requires a skip message per step.
  - `[false]` `[reject]` Intent: `ruff` in `pyproject.toml` is out of scope — the epic task requires it.
  - `[low]` `[reject]` Intent: `install` and `build-image` steps lack `set -e` — each runs a single command whose exit code propagates.

## Design Notes

Each Cloud Build step has one image, so the single `test-pr-only` step in the epic is split by toolchain (Python, web, Terraform). All carry the `test-pr-only` id prefix and the same skip guard. The epic says `uv sync --frozen`, but only `--locked` fails on a stale lock, which is the stated intent, so the file uses `--locked`.

## Verification

**Commands:**
- `python -c "import yaml,sys; yaml.safe_load(open('cloudbuild.yaml'))"` -- expected: exit 0
- `terraform -chdir=terraform fmt -check` -- expected: exit 0

## Auto Run Result

Status: awaiting-operator

Draft for review.

**Summary:** Added `cloudbuild.yaml` with `_MODE` (`pr` or `main`, default `main`). Steps: `validate-mode`, `install-deps-python`, `install-deps-web`, `test-pr-only` (pytest, ruff check, ruff format check), `test-pr-only-web` (lint, build), `test-pr-only-terraform` (fmt, init without backend, validate) and `build-image` (no push). In `main` mode every step prints a skip message. Builders are pinned with a reason each, logging is `CLOUD_LOGGING_ONLY`, timeout 20 minutes. `ruff` added to the `dev` extra. `CI-CD-SETUP.md` documents the path, builders and the baseline placeholder.

**Files changed:**
- `cloudbuild.yaml` -- new PR and main path.
- `pyproject.toml` -- `ruff>=0.8` in the `dev` extra.
- `CI-CD-SETUP.md` -- Pull request path section and assumptions.

**Review findings:** 17 grouped rows. Patched 1 (medium: `validate-mode` step). Deferred 3 (stale `uv.lock` as an operator action, unverified image tags, missing Terraform lock file). 13 rejected with reasons in the Review Triage Log.

**Follow-up review recommended:** false. One medium patch and no high.

**Verification:**
- `cloudbuild.yaml` parsed as YAML (Ruby) and listed its steps before the `validate-mode` patch. The re-parse after the patch was blocked, so the patched file has not been parsed.
- `terraform -chdir=terraform fmt -check` exited 0.
- Not run: pytest, ruff, `npm run lint`, `npm run build`, `terraform validate`, the Docker build, `uv lock`, any Cloud Build run. Shell commands that install or run tests were denied.

**Residual risks:**
- `uv.lock` lacks `ruff`, so the first PR build fails until `uv lock` is committed.
- Existing code has never been checked with ruff and may fail the gate.
- Builder image tags are unpulled.
- The PR build time baseline is unrecorded.

**Operator actions owed:** see `operator_actions` in the frontmatter.
