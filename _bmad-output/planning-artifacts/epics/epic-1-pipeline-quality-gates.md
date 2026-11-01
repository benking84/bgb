# Epic 1: Testing and Quality Gates in the bgb Cloud Run Pipeline

**Status:** Draft for review
**Author:** Murat (TEA) with Ben
**Date:** 2026-10-31
**Scope:** bgb repository (`src/bgb`, `web/`, `terraform/`, `Dockerfile`, `cloudbuild.yaml`, `deploy/`)
**Builds on:** Epic 8 (deployment pipeline). **Cross epic dependency:** Epic 8 Stories 8.1 to 8.3 must land before Story 1.1, and Story 8.4 before Story 1.10. Epic 1 keeps its number because the test design, ATDD checklists and `epics.md` refer to it. This epic adds test stages to the pull request path of Epic 8's `cloudbuild.yaml`, and verification to its Cloud Deploy rollout.
**Revised:** 2026-10-31, to align with Epic 8 decisions DEP-D1 to DEP-D4 (tests run once on the PR; Cloud Deploy owns the release). Decision D5 and waiver W-001 are unchanged.

---

## 1. Goal

Every change to bgb passes through an automated pipeline that proves three things before it reaches users:

1. **Backups are correct.** Data written can be restored byte for byte, and nothing the index needs is lost by retention, compaction or a crash.
2. **The service is safe to expose.** The API that serves backed up Workspace content enforces auth and does not leak data.
3. **The deployed Cloud Run service and job actually work** in the target project before a Cloud Deploy rollout completes, with automatic rollback when they do not.

Every test that gates a change runs once, on the pull request (target under 15 minutes). A merge to `main` does not repeat them: it builds the image, releases it through Cloud Deploy, and runs only post deploy checks against the new revision (target under 15 minutes). The slow and exhaustive suites run nightly.

## 2. Current state (observed in the repo)

| Area | Today |
|---|---|
| Backend | Python 3.11+, FastAPI, about 20 pytest tests in `tests/` using in-memory index, volume store and secrets fakes |
| Frontend | Next.js 15 static export served by the API. No tests. ESLint configured |
| Image | One multi-stage `Dockerfile` (Node build, then Python 3.12 slim, runs as uid 10001). Used by both the Cloud Run service and the Cloud Run job |
| Infra | `terraform/` creates bucket, Firestore, Secret Manager, IAM, Cloud Run service (`ingress = INGRESS_TRAFFIC_ALL`), Cloud Run job (`run-due`) and Cloud Scheduler (every 15 minutes) |
| CI/CD | None. No pipeline config exists. Deploy is a manual `terraform apply` with an `image` variable. Epic 8 adds the Cloud Build triggers, the PR test step and the Cloud Deploy pipeline that this epic extends |
| Auth | `BGB_API_TOKEN` is optional. `allow_unauthenticated` can grant `allUsers` invoker. **Changing:** `epics.md` D7 makes IAP mandatory and removes the app token and the public option (Stories 5.1, 5.2) |
| GCP project | Requested in the landing zone as a **Demo** tier project, `aviato-prod-demo-baby-got-back` (one project, no Shared VPC, no Cloud Deploy pipeline, group editor access until 2026-11-30) |

## 3. Assumptions and open decisions

These are assumptions I made to write the epic. Each one changes stories if it is wrong.

| # | Assumption | Impact if wrong |
|---|---|---|
| A1 | **CI runs on Google Cloud Build**, triggered from the GitHub repo `benking84/bgb` through the Cloud Build GitHub app. This matches the landing zone, which already uses Cloud Build. | **Decided (D3, 2026-10-31): Cloud Build.** |
| A2 | **One GCP project** (the Demo project) holds both a CI test area and the running service. Isolation inside it uses a separate CI bucket, a separate named Firestore database and a separate Cloud Run job. | A Demo project is time boxed and is not a production landing zone. Before real customer data, move to Startup or Enterprise tier, which gives a CICD project. Epic 8 builds Cloud Deploy targets from a `deploy_targets` variable, so that move is a configuration change. |
| A3 | Terraform stays the owner of infrastructure, and the pipeline owns **which image revision serves traffic**. This needs `lifecycle { ignore_changes }` on the image fields in Terraform. | **Decided (D1, 2026-10-31): the pipeline owns the image.** Epic 8 DEP-D1 goes further: Cloud Deploy owns the image and the Cloud Run runtime configuration. Epic 8 Story 8.6 updates the README. |
| A4 | No test Google Workspace tenant or OU exists yet. | **Decided (D2, 2026-10-31): none for now.** Live source tests are deferred out of Story 1.11. Connector coverage relies on recorded responses (Story 1.6). Accepted risk: a change on Google's side (API behaviour, export formats, quota errors) is first seen when a real backup fails, so Story 1.11 alerts on failed production runs. |
| A5 | No contract testing (Pact). The web UI and the API ship in the same image and deploy together, so there is no independent consumer and provider boundary. Drift between `web/src/lib/types.ts` and the API is caught by an OpenAPI type check instead (Story 1.7). | If another team starts consuming the bgb API, revisit and add consumer driven contracts. |
| A6 | Playwright is the UI E2E runner. TEA config has `tea_use_playwright_utils: true`, but the package is not installed yet, so Story 1.8 installs `@playwright/test` and `@seontechnologies/playwright-utils` and writes the suite in that style. | None expected. |

## 4. Pipeline design

### 4.1 Triggers

| Trigger | Cloud Build config | Runs stages | Time budget |
|---|---|---|---|
| Pull request to `main` (trigger `bgb-pr`, Epic 8 Story 8.2) | `cloudbuild.yaml` with `_MODE=pr` | 1 to 5 (P0 and P1 only) | 15 minutes |
| Push to `main` (trigger `bgb-main`, Epic 8 Story 8.2) | `cloudbuild.yaml` with `_MODE=main` | No test stages. Build, push and release (Epic 8 Story 8.5), then stage 6 inside the Cloud Deploy rollout | 15 minutes |
| Nightly (Cloud Scheduler calls a manual trigger) | `ci/cloudbuild-nightly.yaml` | Full regression (P0 to P3), restore drill, performance, burn-in | 90 minutes |

### 4.2 Stages

```
 Pull request (_MODE=pr): every gating test, run once
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│1 Static      │→│2 Unit        │→│3 Integration │→│4 Build image │→│5 E2E on the  │→ PR check
│  lint, types,│ │  pytest,     │ │  Firestore + │ │  (not pushed)│ │  PR image    │
│  tf validate,│ │  coverage    │ │  GCS emulator│ │  scan,       │ │  (Playwright)│
│  secrets scan│ │              │ │  API, data   │ │  structure   │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

 Merge to main (_MODE=main): no test stage is repeated
┌──────────────┐ ┌──────────────┐ ┌──────────────────────────────┐
│ Build, push  │→│ Cloud Deploy │→│6 Verify the new revision     │→ complete rollout
│ by digest    │ │ release to   │ │  smoke tests and canary job, │   or roll back
│ (Story 8.5)  │ │ prod (8.4)   │ │  run by Cloud Deploy         │
└──────────────┘ └──────────────┘ └──────────────────────────────┘
```

Principles applied throughout:

- **Test once, on the PR.** Stages 1 to 5 run only on the pull request. `main` builds the release image once and Cloud Deploy deploys that `@sha256:` digest. The `main` image is a rebuild of tested source (Epic 8, A2), and branch protection requires PRs to be up to date before merging (Epic 8, A1).
- **Post deploy checks are not repeated tests.** Stage 6 checks the deployed revision in the real project (smoke tests and a canary job). It does not re-run stages 1 to 5.
- **Lowest test level that proves the behaviour.** Dedup, retention and cron logic are unit tests. Index and storage behaviour are integration tests against emulators. Only user journeys are browser tests.
- **Failures keep their evidence.** Each stage uploads JUnit XML, coverage and Playwright traces to a CI artifacts bucket, keyed by build ID and commit SHA, even when the stage fails.
- **Flakiness is a defect.** A test that fails then passes on retry is reported as flaky, not green (Story 1.12).

### 4.3 Test priorities

Every test is tagged with a priority. Gates are defined by priority, not by test count.

| Priority | Meaning for bgb | Examples | Gate |
|---|---|---|---|
| P0 | Data loss, data exposure, or a backup that cannot be restored | Restore byte equality, SHA-256 verify, compaction keeps referenced blocks, API auth, rebuild after crash | 100% pass on every PR, and in stage 6 on every rollout. No retries allowed |
| P1 | Core journeys and integration points | Gmail incremental scan, Drive export, retention policy math, run now from UI, Scheduler to job invocation | 100% pass on every PR. One retry allowed, and a retry pass is reported as flaky |
| P2 | Secondary features and edge cases | Chat space with external members reported as skipped, settings page validation, large shared drive pagination | Nightly. Failures open a ticket, do not block |
| P3 | Cosmetic and low risk | Formatting helpers, empty states | Nightly when time allows |

Python tests use pytest markers (`@pytest.mark.p0` and so on, plus `integration` and `live`). Playwright tests use tags in the title (`@p0`).

## 5. Stories

Stories are ordered by dependency. All of them build on Epic 8 Stories 8.1 to 8.3 (Terraform foundations, triggers, PR test step). Stories 1.1 to 1.5 give a useful PR gate on their own and should land first.

---

### Story 1.1: Test pipeline foundation: artifacts, markers and CI access

**As** the bgb team, **we want** a place for test evidence, a shared tagging scheme for tests, and least privilege access to the CI test area, **so that** every later story in this epic has somewhere to run and report.

**Priority:** P0 enabler

**Depends on:** Epic 8 Stories 8.1 (service accounts, Artifact Registry), 8.2 (triggers, branch protection) and 8.3 (the `_MODE=pr` test step).

**Acceptance criteria**
- Test results and logs for every build are stored in `gs://<project>-ci-artifacts/<build-id>/` with a 30 day lifecycle rule.
- `bgb-cloudbuild` (Epic 8 Story 8.1) gains only the extra roles this epic needs: object admin on the CI bucket and the CI artifacts bucket, and `roles/datastore.user` scoped by IAM condition to the CI Firestore database. No new build service account is created.
- pytest markers `p0`, `p1`, `p2`, `p3`, `integration` and `live` are registered with `--strict-markers`, so an unknown marker fails the run.
- The `_MODE=pr` path of `cloudbuild.yaml` uploads JUnit XML from the test step to the artifacts bucket, even when the step fails.

**Tasks**
- [ ] Add to `terraform/`: the CI artifacts bucket and the extra `bgb-cloudbuild` bindings.
- [ ] Add the pytest markers to `pyproject.toml`.
- [ ] Add a pip and npm cache restore step to the `_MODE=pr` path if PR builds approach the 15 minute budget.
- [ ] Add a "Tests and quality gates" section to `CI-CD-SETUP.md` (created in Epic 8 Story 8.6).
- [ ] Confirm the landing zone grants needed for this (see section 7) are requested.

---

### Story 1.2: Static analysis and infrastructure checks (Stage 1)

**As** a reviewer, **I want** formatting, typing, Terraform and secret problems caught in the first two minutes, **so that** review time goes on behaviour, not style.

**Priority:** P1

**Acceptance criteria**
- Stage 1 fails on: ruff lint or format errors, mypy errors in `src/bgb`, ESLint errors, `tsc --noEmit` errors, `terraform fmt -check` or `terraform validate` failures, tflint findings, checkov high severity findings, or a committed secret.
- Stage 1 completes in under 2 minutes with a warm cache.
- Existing findings at adoption are either fixed or listed in a baseline file with an owner, so the gate starts green and only new findings fail.

**Tasks**
- [ ] Add `ruff` and `mypy` to the `dev` extra in `pyproject.toml` with config. Fix or baseline existing findings.
- [ ] Add a `typecheck` script (`tsc --noEmit`) to `web/package.json`.
- [ ] Add `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, `tflint` and `checkov` steps. Reuse the landing zone `.tflint.hcl` and `.checkov.yaml` as a starting point.
- [ ] Add `gitleaks` (or `trufflehog`) for secret scanning on the diff.
- [ ] Add dependency vulnerability checks: `pip-audit` and `npm audit --omit=dev --audit-level=high`.
- [ ] Add a checkov rule review for `ingress = INGRESS_TRAFFIC_ALL`, and a check that no `allUsers` invoker binding exists (IAP is mandatory, `epics.md` D7), so any exception is explicit and suppressed with a reason rather than silent.

---

### Story 1.3: Unit test layer and coverage gate (Stage 2)

**As** the team, **we want** the pure logic of the backup engine covered by fast unit tests, **so that** most regressions are caught in seconds without any cloud dependency.

**Priority:** P0

**Acceptance criteria**
- `pytest -m "not integration and not live"` runs in under 60 seconds.
- Coverage is reported per module. The gate starts at the measured baseline and ratchets: a PR may not lower coverage of `engine.py`, `retention.py`, `volume.py`, `storage.py`, `schedule.py` or `index/`.
- Each risk listed in the tasks below has at least one P0 or P1 test with a name that states the rule it checks.

**Tasks**
- [ ] Add `pytest-cov` and `pytest-xdist`. Emit JUnit XML and `coverage.xml` to the artifacts bucket.
- [ ] Measure the current baseline and record it in `ci/coverage-baseline.json`. Do not invent a target before the baseline exists.
- [ ] Tag the existing 20 tests by priority.
- [ ] Add or confirm unit tests for these rules, taken from the README and REVIEW.md:
  - Fixed size block split and dedup: identical blocks are stored once, across files and across runs (P0).
  - SHA-256 is checked on every stored object and every restored file, and a single flipped byte fails the check (P0).
  - Block lists shard at 400 hashes, so a file with 401+ blocks round trips (P0).
  - Retention always keeps the newest version, for count, age and bucket policies such as `1W:1D,4W:1W,12M:1M`, with 30 day months and 365 day years (P0).
  - Compaction rewrites a volume only when 25% or more of its blocks are unreferenced, and never drops a referenced block (P0).
  - Volume size cap of 128 MiB is enforced and the default is 50 MiB (P1).
  - UTC cron evaluation in `schedule.py`, including run-due boundaries at minute 0, 15, 30 and 45 (P1).
- [ ] Add property based tests with `hypothesis` for split, dedup and restore round trip over random data and random file sizes, including 0 bytes and exact block size multiples (P0).

---

### Story 1.4: Integration tests against GCP emulators (Stage 3)

**As** the team, **we want** the Firestore index and Cloud Storage volume store tested against emulators, **so that** behaviour that differs from the in-memory fakes (document limits, transactions, listing) is caught before deploy.

**Priority:** P0

**Deferred by D5:** the emulator harness is deferred and the R-001 Firestore tests are written and skipped (waiver W-001). The Story 1.10 canary job against real Firestore stays mandatory.

**Acceptance criteria**
- Stage 3 starts the Firestore emulator and a fake GCS server as background containers on the Cloud Build network, and the integration suite connects through `FIRESTORE_EMULATOR_HOST` and `STORAGE_EMULATOR_HOST`.
- A single **shared behaviour suite** runs against every implementation of each interface: `MemoryIndex` and the Firestore index, `MemoryVolumeStore`, the local directory store and the GCS store. A behaviour the fake has and the real store does not is a failing test.
- Stage 3 completes in under 4 minutes.

**Tasks**
- [ ] Add a `docker-compose.test.yml` (also used locally) with the Firestore emulator (`google-cloud-cli:emulators` image) and `fsouza/fake-gcs-server`.
- [ ] Confirm `bgb` honours the emulator environment variables. If the GCS client is built with explicit credentials that bypass `STORAGE_EMULATOR_HOST`, add a small injection point.
- [ ] Write parametrised fixtures in `tests/conftest.py` that yield each index and store implementation, and move the interface level assertions into shared test modules.
- [ ] Add Firestore specific tests: a file whose block list exceeds one shard stays under the 1 MiB document limit; a backup larger than 500 writes completes (P0).
- [ ] Add API integration tests using FastAPI `TestClient` over the emulator backed runtime, covering every route in `src/bgb/api/app.py` at least once (P1). Requests carry an IAP signed header made with a test key, accepted only because the test patches the verifier's Google key fetch in-process (`epics.md` Story 5.1, D11). No runtime setting can do this.
- [ ] Run the existing demo journey (`/api/demo/seed`, run, list filesets, download content) against emulators, not only memory (P0).

---

### Story 1.5: Data integrity and recovery suite (P0 gate)

**As** a customer trusting bgb with Workspace data, **I want** every build to prove that backups restore and survive failure, **so that** a regression cannot silently corrupt or lose backups.

**Priority:** P0. This is the most important story in the epic.

**Acceptance criteria**
- All tests in this story are P0 and run on every PR (Stage 3) against emulators.
- Each scenario asserts on bytes and SHA-256, not only on status codes.

**Tasks**
- [ ] **Round trip:** back up the Northwind fixture, restore every file, compare bytes and hashes with the source.
- [ ] **Second run dedup:** a second unchanged run uploads zero new blocks (already in `test_api.py`; promote to P0 and run against emulators).
- [ ] **Crash between upload and index write:** inject a failure after a volume is uploaded but before the index records it. Then run `bgb rebuild` and assert that the index is reconstructed and every file restores.
- [ ] **Corruption detection:** flip one byte in a stored volume. `bgb verify --full` must fail and name the affected volume.
- [ ] **Missing object detection:** delete a volume from the bucket. `verify` must report it.
- [ ] **Retention plus compaction:** run several versions, apply retention, compact, then restore every remaining version byte for byte.
- [ ] **Incremental correctness:** change, add and delete files between runs (Gmail history id path, Drive change set path, Contacts sync token path). The latest fileset must match the source exactly, and older filesets must still restore.
- [ ] **Index is a cache:** delete the index entirely, run `rebuild`, and assert the result equals the index before deletion.

---

### Story 1.6: Source plugin tests with recorded Google API responses

**As** the team, **we want** the Gmail, Drive and Contacts plugins tested against realistic API responses, **so that** pagination, export and error handling are proven without live credentials on every PR.

**Priority:** P1

**Acceptance criteria**
- Plugin tests run offline in Stage 2 or 3 using recorded responses stored under `tests/fixtures/google/`. Recordings contain no real user data.
- Error paths are covered: HTTP 429 and 5xx with backoff, 401 on an expired token, 403 on a user without delegation, 404 for a deleted item mid scan.

**Tasks**
- [ ] Choose a recording approach for `google-api-python-client` (its `HttpMockSequence`, or `vcrpy`), and add a scrubbing step for email addresses, IDs and tokens.
- [ ] Gmail: first full scan, then incremental via history id; expired history id falls back to a full scan (P1).
- [ ] Drive: My Drive, shared drives listed once as the admin, Docs/Sheets/Slides/Drawings exported to Office or PNG, Forms and shortcuts skipped and reported on the run (P1).
- [ ] Contacts: one JSON per person, sync token followed, expired token falls back to full sync (P1).
- [ ] "Every user" job: Directory listing used under service account mode, and rejected under OAuth mode (P1).
- [ ] Keyless signing path: delegation JWT is signed through the IAM Credentials API when no JSON key exists (P1, mocked).

---

### Story 1.7: API security and API to UI type checks

**As** the owner of a service that serves backed up mail and files, **I want** auth and input handling tested on every route, **so that** no change can expose Workspace data.

**Priority:** P0

**Acceptance criteria**
- Every route except `/api/health` returns 401 without a valid IAP signed header (`X-Goog-IAP-JWT-Assertion`), and with a header that fails signature, expiry or audience checks (`epics.md` Story 5.1, D7). The test enumerates routes from the FastAPI app, so a new route is covered automatically and a new unauthenticated route fails the build unless it is on an explicit allow list.
- The file content endpoint rejects path traversal and paths outside the fileset.
- The TypeScript types used by the web UI are generated from, or checked against, the FastAPI OpenAPI schema. A breaking API change fails the PR.

**Tasks**
- [ ] Add a parametrised auth test over `app.routes` (P0).
- [ ] Add negative tests for `/api/jobs/{job_id}/filesets/{fileset_id}/content`: `..`, absolute paths, encoded separators, another job's fileset (P0).
- [ ] Add tests that secrets (service account key, OAuth refresh token) and the IAP signed header never appear in any API response or log line (P0).
- [ ] Export the OpenAPI schema in CI and generate types with `openapi-typescript`. Fail if `web/src/lib/types.ts` differs from the generated output, or replace the hand written types with the generated ones (P1).
- [ ] Add a production configuration check: the Cloud Deploy verification in Story 1.10 fails the rollout when the service is publicly invokable or IAP is not enabled on it (P0).
- [ ] Add an image check: the shipped image contains no development entry point and no test key material (`epics.md` D11) (P0).

---

### Story 1.8: UI end to end tests with Playwright (Stage 5)

**As** a user, **I want** the core journeys in the web UI tested in a real browser, **so that** the static export behaves correctly for every API response it can get.

**Priority:** P1

**Acceptance criteria**
- Playwright runs against the static export built in Stage 4, with the API mocked at the network layer (`interceptNetworkCall`), including a signed-in identity and an expired session (401). IAP is never weakened for tests (`epics.md` D11): there is no auth bypass in the image. The real image and API together are covered in-process by Story 1.4 and, through real IAP, by Story 1.10's post-deploy checks.
- Mocked responses are generated from or checked against the OpenAPI schema (Story 1.7), so mocks cannot drift from the real API.
- Tests are written with `@seontechnologies/playwright-utils` fixtures (`apiRequest`, `interceptNetworkCall`, `recurse`, `log`), per the TEA configuration. Any vanilla Playwright usage carries a `playwright-utils deviation` comment with a reason.
- P0 and P1 journeys run on PRs in under 4 minutes. Traces, screenshots and video are kept on failure only.

**Tasks**
- [ ] Run the TEA framework workflow (`TF`) to install `@playwright/test` and `@seontechnologies/playwright-utils` in `web/`, with config and fixtures.
- [ ] Journeys:
  - Load the Northwind sample, run now, see the run complete (P0).
  - Browse a fileset and download a file; downloaded bytes equal the fixture (P0).
  - Sign-in: the header shows the signed-in user, and an expired session shows the sign-in-again page, not a blank page (P0, `epics.md` Story 5.3).
  - Create a job with all sources selected in demo mode and see a fileset for each (P1, owned by Epic 9 Story 9.6).
  - Retention and schedule fields validate input (P2).
- [ ] Use API calls for setup (seed, run) and the browser only for the behaviour under test.
- [ ] Use role and label selectors. Add `data-testid` only where no accessible name exists.
- [ ] Add `npm run test:e2e` and a step in the `_MODE=pr` path of `cloudbuild.yaml` that starts the PR image, waits on `/api/health`, then runs Playwright.

---

### Story 1.9: Container image scan and structure tests on the PR image (Stage 4)

**As** the team, **we want** the image checked on every PR before it can merge, **so that** what `main` releases is built from source whose image already passed these checks.

**Priority:** P1

**Acceptance criteria**
- On PRs, the image built by Epic 8 Story 8.3 is scanned and structure tested. It is not pushed. On `main`, no scan or structure test runs again (Epic 8 DEP-D3); Artifact Registry continuous scanning reports on pushed images instead.
- The PR build fails on critical vulnerabilities with a fix available (Trivy).
- Container structure tests confirm: runs as uid 10001, `PORT` honoured, `BGB_WEB_ROOT` contains the exported UI, `python -m bgb --help` works, no `.env`, `data/` or `node_modules` in the image.
- A smoke test starts the PR image locally and gets 200 from `/api/health` and from `/` (the UI). Story 1.8 reuses the running container.

**Tasks**
- [ ] Add a `container-structure-test` config under `ci/`.
- [ ] Add a Trivy scan step with a `.trivyignore` that requires a reason per entry.
- [ ] Generate an SBOM for the PR image and store it with the build artifacts.
- [ ] Turn on Artifact Registry vulnerability scanning for the `bgb` repository, with findings for released images sent to the alerts group (Story 1.12).

---

### Story 1.10: Verify each rollout in Cloud Deploy, with automatic rollback (Stage 6)

**As** the team, **we want** each new revision checked in the real project before the rollout completes, **so that** a bad deploy does not stay in production and is rolled back without anyone acting.

**Priority:** P0

**Depends on:** Epic 8 Story 8.4 (delivery pipeline and `prod` target). **Decision D1 (resolved), extended by Epic 8 DEP-D1:** Cloud Deploy owns the image and runtime configuration.

**Acceptance criteria**
- The `prod` target's rollout runs verification as part of Cloud Deploy, not as a separate Cloud Build step. The new revision is checked before it takes all traffic, using a Cloud Deploy canary strategy for Cloud Run or an equivalent verify then promote phase. The chosen mechanism is recorded in the story notes.
- Smoke tests run against the new revision through real IAP, as a dedicated smoke-test service account with IAP access only (`epics.md` Story 5.2): health, a signed-in request succeeds, a request with no sign-in is refused by IAP at the edge, and the production configuration check from Story 1.7. The app's own header check is covered by unit tests, because IAP always adds the header for requests that reach the app. They are new post deploy checks, not a repeat of stages 1 to 5.
- A **canary job execution** runs `python -m bgb run-due` from a separate Cloud Run job, `bgb-backup-ci`, using the release image against the CI bucket and CI Firestore database, and must complete.
- If any check fails, the rollout fails, traffic and the production `bgb-backup` job stay on (or return to) the previous release, and the evidence is attached to the rollout.
- A failed rollout or automatic rollback emails the alerts group (Story 1.12).

**Tasks**
- [ ] Add to `terraform/`: CI bucket, named Firestore database `bgb-ci`, and the `bgb-backup-ci` job, which Cloud Deploy updates with the release image. **Never write test data into the production bucket or database.**
- [ ] Write `ci/smoke/` tests (pytest with `httpx`, P0) that take the base URL and an ID token for the IAP audience as input, packaged as the Cloud Deploy verification container, running as the smoke-test service account.
- [ ] Add the canary or phased strategy and `verify: true` to the `prod` target in the delivery pipeline (Epic 8 Story 8.4).
- [ ] Add automatic rollback on failed verification (Cloud Deploy automation or a rollback step), and test it with a deliberately failing release.
- [ ] Keep it working when more targets are added: verification is defined per target in `deploy_targets`.

---

### Story 1.11: Nightly regression, restore drill, performance and alerting

**As** the team, **we want** slower and more realistic checks run every night, **so that** we catch problems that do not show up with fixtures.

**Priority:** P1

**Decision D2 (resolved):** no test Workspace for now, so live source tests are deferred (see "Deferred" below).

**Acceptance criteria**
- The nightly build runs the full P0 to P3 suite and reports pass rate and flaky tests.
- **Production run failures alert the team:** owned by `epics.md` Epic 6 (D5), which alerts on failed, stuck and warning runs through the Story 1.12 channel. This story does not add its own failed-run alert, so each problem sends one email.
- **Restore drill:** weekly, restore a full fileset from the CI bucket into a scratch location and run `bgb verify --full`.
- **Performance:** a backup of a generated data set (for example 5 GB with 30% duplicate blocks) completes within the 2 GiB job memory limit and records duration, throughput and peak memory. A regression of more than 20% against the trailing 7 day median opens a ticket.
- **API load:** a short k6 run against the live service checks p95 latency of list and summary endpoints with realistic fileset sizes.

**Tasks**
- [ ] Add `ci/cloudbuild-nightly.yaml` and its Cloud Scheduler trigger.
- [ ] Write a data generator for the performance set and store results as JSON in the artifacts bucket.
- [ ] Add k6 scripts under `ci/perf/`.
- [ ] ~~Add a log based metric and alert policy on failed `bgb-backup` executions~~ Moved to `epics.md` Story 6.2 (D5). Keep only the nightly regression and restore drill alerts here.
- [ ] Email the nightly summary to the alerts group (Story 1.12).

**Deferred until a test Workspace exists (D2)**
- Live backup of a seeded test OU (Gmail, Drive including one shared drive, Contacts) from the `bgb-backup-ci` job, with restore and byte comparison of a sample.
- Seeding script for the test OU, and the CI delegation credential in Secret Manager, readable only by `bgb-cloudbuild` and the CI job runtime SA.
- Refreshing the recorded responses in Story 1.6 from the live tenant, so recordings do not drift from Google's real behaviour.

---

### Story 1.12: Quality gate policy, reporting and flakiness control

**As** the team, **we want** clear and enforced rules for what blocks a release, **so that** gates are trusted and not bypassed.

**Priority:** P1

**Acceptance criteria**
- A written gate policy (section 4.3) lives in `ci/QUALITY-GATES.md` and is enforced by a final pipeline step that reads the JUnit results, not by convention.
- **Burn in:** on PRs, new or changed test files run 10 times. Any failure blocks the PR.
- **Flaky tests:** a test that passes only on retry is marked flaky in the report. A flaky P0 test blocks the build. A flaky P1 test is moved to a quarantine list with an owner and a 7 day fix window, and still runs nightly.
- **Waivers:** a P1 failure can be waived only by a code owner, with a reason and expiry recorded in the PR. P0 failures cannot be waived.
- Build summaries show, per stage: tests run, failed, flaky, duration, coverage change.

**Tasks**
- [ ] Write `ci/QUALITY-GATES.md`.
- [ ] Add a gate evaluation script that reads JUnit XML and the quarantine list and returns pass or fail.
- [ ] Add the burn in step for changed tests (pytest `--count` via `pytest-repeat`, Playwright `--repeat-each`).
- [ ] Add `ci/quarantine.yaml` with owner and expiry per entry. The gate fails when an entry has expired.
- [ ] Set up email alerts (D4) to `bgb-admins@aviato.consulting`. Create a Cloud Monitoring email notification channel for that group; `epics.md` Epic 6 uses the same channel. Cloud Build has no built in email, so deploy the Cloud Build SMTP notifier (Cloud Run service subscribed to the `cloud-builds` Pub/Sub topic) filtered to failed main and nightly builds, rollbacks, and the gate step reporting an expired quarantine entry. Confirm the group accepts mail from outside the domain or from the SMTP sender used.
- [ ] Add a Looker Studio or simple dashboard over the artifacts bucket for pass rate and flaky trends (optional, P3).

---

## 6. Dependencies and order

| Order | Stories | Result |
|---|---|---|
| 0 | Epic 8 Stories 8.1 to 8.3, and 8.4 before Story 1.10 | Pipeline, triggers, PR test step and Cloud Deploy exist |
| 1 | 1.1, 1.2, 1.3 | PR gate with static analysis and unit tests |
| 2 | 1.4, 1.5, 1.7 | P0 data integrity and security gate on every PR |
| 3 | 1.9, 1.8 | PR image scanned and tested, UI journeys covered |
| 4 | 1.10 | Every rollout verified, with automatic rollback |
| 5 | 1.6, 1.11, 1.12 | Source realism, nightly depth, gate governance and alerting |

## 7. Landing zone and access needs

- The Demo project grants the Workspace groups `roles/editor` until 2026-11-30. The CI service account, triggers and Artifact Registry should be created by Terraform in this repo, not by hand, so they survive that date. Someone must extend `owner_until` in the landing zone or move to a Startup or Enterprise tier before then.
- The Demo tier enables no APIs. Epic 8 Story 8.1 enables the pipeline APIs (Cloud Build, Artifact Registry, Cloud Deploy, IAM Credentials, Container Scanning) in `terraform/`. This epic needs no further APIs beyond those already enabled for the service.
- A production deployment holding customer Workspace data should not run in a Demo tier project. Recommend raising the tier before the first real tenant.

## 8. Decisions needed

| ID | Question | Recommendation |
|---|---|---|
| D1 | May the pipeline own the Cloud Run image (with Terraform ignoring it), to allow no traffic canary deploys and rollback? | **Decided 2026-10-31: yes.** Terraform owns infrastructure, the pipeline owns revisions. Extended by Epic 8 DEP-D1: Cloud Deploy also owns runtime configuration. |
| D2 | Is there a test Google Workspace tenant or OU for nightly live tests? | **Decided 2026-10-31: none for now.** Live tests deferred; production run failures alert instead. Revisit before the first customer tenant. |
| D3 | Cloud Build or GitHub Actions? | **Decided 2026-10-31: Cloud Build.** |
| D4 | Where should nightly summaries and gate failures be posted? | **Decided 2026-10-31 (Ben): email to `bgb-admins@aviato.consulting`**, the same group that has console access (`epics.md` D8). |
| D5 | Must the Firestore index tests (R-001) run against the emulator before the epic proceeds? | **Decided 2026-10-31 (Ben): no.** R-001 is accepted as derisked (waiver W-001 in `_bmad-output/test-artifacts/test-design-epic-1.md`). The tests are written and skipped, and the emulator harness in Story 1.4 is deferred. The Story 1.10 canary job against real Firestore stays mandatory. |

All decisions are now recorded. Remaining risk to watch: the Demo tier expiry on 2026-11-30 (section 7).
