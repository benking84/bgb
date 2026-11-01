---
workflowStatus: 'completed'
totalSteps: 5
stepsCompleted: ['step-01-detect-mode', 'step-02-load-context', 'step-03-risk-and-testability', 'step-04-coverage-plan', 'step-05-generate-output']
lastStep: 'step-05-generate-output'
nextStep: ''
lastSaved: '2026-10-31'
inputDocuments:
  - _bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md
  - README.md
  - REVIEW.md
  - terraform/main.tf
  - src/bgb/api/app.py
  - tests/
  - _bmad/tea/config.yaml
  - resources/knowledge/risk-governance.md
  - resources/knowledge/probability-impact.md
  - resources/knowledge/test-levels-framework.md
  - resources/knowledge/test-priorities-matrix.md
  - resources/knowledge/nfr-criteria.md
---

# Test Design: Epic 1 - Testing and Quality Gates in the bgb Cloud Run Pipeline

**Date:** 2026-10-31
**Author:** Ben (prepared with Murat, TEA)
**Status:** Draft for review

---

## Executive Summary

**Scope:** Full epic-level test design for Epic 1. It decides what the pipeline must prove, at which level, and what blocks a release. It does not change the epic's stage design.

**Baseline measured for this design (2026-10-31, Python 3.12):** 20 tests, all passing in 1.7 s, 66% line coverage. Coverage is strong where the in-memory fakes are used (engine 89%, volume 91%, memory index 90%, Gmail 96%, Drive 92%, Contacts 100%) and weak or absent on the code that runs in production: `index/firestore.py` 0%, `cli.py` 0% (the Cloud Run job entry point), `googleapi.py` 23%, `storage.py` 41% (GCS store), `runtime.py` 45%, `secretstore.py` 51%.

**Risk Summary:**

- Total risks identified: 17
- High-priority risks (≥6): 8, one of which scores 9 (BLOCK)
- Critical categories: DATA (production index and store untested), SEC (backup content served by an optionally authenticated, publicly reachable API), OPS (no deploy safety today)

**Coverage Summary:**

- P0 scenarios: 49 (~70 to 110 hours)
- P1 scenarios: 58 (~45 to 75 hours)
- P2/P3 scenarios: 19 (~11 to 23 hours)
- Pipeline build work outside test writing (Stories 1.1, 1.2, 1.9, 1.10, 1.12): ~40 to 70 hours
- **Total effort**: ~165 to 280 hours (~4 to 7 weeks for one engineer)

**Decision 2026-10-31 (Ben):** R-001 is accepted as sufficiently derisked. Its acceptance tests are written and proven against the in-memory and file indexes, and the Firestore runs are assumed to pass. See "Decisions and Waivers" below.

**The headline finding:** the existing tests prove the backup engine works on its fakes. They do not prove it works on Firestore and Cloud Storage, which is what production uses. Closing that gap (R-001, R-003, R-005) is the first priority, ahead of UI or deploy work.

---

## Not in Scope

| Item | Reasoning | Mitigation |
|---|---|---|
| **Live Google Workspace backups** | Decision D2: no test tenant or OU for now | Recorded responses (Story 1.6) plus alerting on failed production runs (Story 1.11). Tracked as R-007 |
| **Consumer driven contract tests (Pact)** | Web UI and API ship in one image and deploy together; no independent consumer | OpenAPI to TypeScript drift check (R-014) |
| **Penetration testing of the deployed service** | Not a pipeline activity | Automated auth and input tests (R-002); recommend a separate review before the first customer tenant |
| **Sustained load and scale testing** | No traffic or tenant size thresholds exist yet | Nightly performance baseline and short k6 run (R-011); thresholds marked UNKNOWN |
| **Google Keep** | No supported API; source is refused by design | One P2 test that the refusal is clear (R-017) |
| **Disaster recovery across regions** | Single region design in `terraform/` | Document only |

---

## Risk Assessment

Scores use probability (1 to 3) × impact (1 to 3). 9 = BLOCK, 6 to 8 = MITIGATE, 4 to 5 = MONITOR, 1 to 3 = DOCUMENT. Owners are roles because named owners are not yet assigned.

### High-Priority Risks (Score ≥6)

| Risk ID | Category | Description | Probability | Impact | Score | Mitigation | Owner | Timeline |
|---|---|---|---|---|---|---|---|---|
| R-001 | DATA | **The production index is untested.** `index/firestore.py` has 0% coverage, yet production sets `BGB_INDEX=firestore` (terraform/main.tf). REVIEW.md names two Firestore specific hazards: block lists sharded at 400 hashes to stay under the 1 MiB document limit, and backups larger than one 500 write transaction. A defect here loses index entries while every current test passes on `MemoryIndex`. | 3 | 3 | **9 BLOCK** | Shared behaviour suite run against every index implementation on the Firestore emulator; explicit shard and large backup tests; restore byte equality on emulators | Dev (bgb) | Before first production tenant (milestone 2, epic section 6) |
| R-002 | SEC | **Backed up mail and files are served by an API that can be public and unauthenticated.** `BGB_API_TOKEN` is optional and only checked when set (app.py `token_gate`); Cloud Run ingress is `INGRESS_TRAFFIC_ALL`; `allow_unauthenticated` can grant `allUsers` invoker; CORS allows `*`. | 2 | 3 | 6 | Enumerated auth test over every route; path and cross-job negative tests on the content endpoint; secret leakage tests; promotion refused when public and tokenless | Dev (bgb) | Milestone 2 |
| R-003 | DATA | **Crash between volume upload and index write.** REVIEW.md states a crash can upload a volume before the index records it, and that `bgb rebuild` recovers from volumes. Rebuild is only tested on memory and local stores. | 2 | 3 | 6 | Fault injected crash test then rebuild then full restore, on emulators; index delete and rebuild equality | Dev (bgb) | Milestone 2 |
| R-005 | TECH | **The GCS volume store behaves differently from the local store.** `storage.py` is at 41%; the GCS paths (list, get, delete, missing object) are not exercised. Verify depends on bucket listing (README). | 2 | 3 | 6 | Shared behaviour suite for every volume store on `fake-gcs-server`; verify detects corruption and missing objects on GCS | Dev (bgb) | Milestone 2 |
| R-006 | TECH | **Google auth and delegation can break every backup at once.** `googleapi.py` is at 23%. It holds JWT signing for domain-wide delegation, the keyless path via the runtime account (README), and OAuth refresh. | 2 | 3 | 6 | Unit tests for token minting on all three paths with mocked IAM Credentials and OAuth endpoints; error mapping tests | Dev (bgb) | Milestone 5 |
| R-007 | BUS | **Google side changes go undetected.** With no live tests (D2), a change in API behaviour, export formats or quota responses is first seen in a real run. Drive skips and reports unsupported types (README), so a partial backup can look successful. | 2 | 3 | 6 | Recorded response suite including error paths; alert on failed or partially failed production runs within 30 minutes (Story 1.11); revisit D2 before first tenant | Dev (bgb), Ben | Milestone 5; D2 review before first tenant |
| R-008 | OPS | **A bad image reaches users.** There is no CI today and deploy is a manual `terraform apply` (README). The Cloud Run job runs `python -m bgb run-due` from `cli.py`, which has 0% coverage. | 2 | 3 | 6 | Build once by digest; container structure tests; no-traffic tagged revision with smoke tests; canary job execution; automatic rollback (Story 1.10); CLI `run-due` tests | Dev (bgb) | Milestone 4 |
| R-012 | OPS | **The Demo tier project expires on 2026-11-30.** Workspace groups lose `roles/editor` on that date (landing zone YAML), and the Demo tier enables no APIs. Manual setup made under group access becomes unmanageable. | 3 | 2 | 6 | Create all CI resources through `terraform/` (Story 1.1); extend `owner_until` or move to Startup or Enterprise tier before the date | Ben | 2026-11-23 (one week before expiry) |

### Medium-Priority Risks (Score 3-5)

| Risk ID | Category | Description | Probability | Impact | Score | Mitigation | Owner |
|---|---|---|---|---|---|---|---|
| R-010 | OPS | Image ownership drift after D1: if `ignore_changes` is missing or removed, a manual `terraform apply` silently rolls the service back to the image variable | 2 | 2 | 4 | Plan check that shows no image diff after a pipeline deploy; README update (Story 1.10) | Dev (bgb) |
| R-011 | PERF | Volumes are packed in memory up to 128 MiB (README) inside a 2 GiB job with a 4 hour timeout (terraform/main.tf). Large shared drives could exhaust memory or time | 2 | 2 | 4 | Volume cap unit tests; nightly performance dataset recording peak memory and duration | Dev (bgb) |
| R-013 | TECH | Flaky tests, or emulator behaviour that differs from real services, erode trust in the gate until people bypass it | 2 | 2 | 4 | Burn-in of changed tests, quarantine with expiry, canary job against real services (Story 1.12) | Dev (bgb) |
| R-014 | TECH | `web/src/lib/types.ts` is hand written; an API change can break the UI without a failing test (there are no UI tests) | 2 | 2 | 4 | OpenAPI to TypeScript drift check; two P0 E2E journeys | Dev (bgb) |
| R-015 | SEC | No dependency or image vulnerability scanning exists | 2 | 2 | 4 | Trivy, `pip-audit`, `npm audit` gates (Stories 1.2, 1.9) | Dev (bgb) |
| R-016 | OPS | Alert email to the approvers group (D4) is rejected or filtered, so failures go unseen | 2 | 2 | 4 | Nightly heartbeat email and a synthetic failure alert test | Ben |
| R-004 | DATA | Retention or compaction drops a still referenced block, making a version unrecoverable. Logic is covered on fakes (`test_retention_then_compact_drops_unreferenced_blocks`) | 1 | 3 | 3 | Repeat the scenario on emulators and restore every surviving version | Dev (bgb) |
| R-009 | DATA | Smoke or canary tests write into the production bucket or database, or the CI account can | 1 | 3 | 3 | Separate CI bucket, named Firestore database and CI job; negative IAM tests | Dev (bgb) |

### Low-Priority Risks (Score 1-2)

| Risk ID | Category | Description | Probability | Impact | Score | Action |
|---|---|---|---|---|---|---|
| R-017 | BUS | A user selects Google Keep and gets an unclear failure | 1 | 1 | 1 | Document; one P2 test |

Residual risk after mitigation: R-007 stays at MONITOR level while D2 is "none for now", because recordings cannot detect a change Google has not yet made. R-012 is resolved only by a landing zone change, not by tests.

### Risk Category Legend

- **TECH**: Technical/Architecture (flaws, integration, scalability)
- **SEC**: Security (access controls, auth, data exposure)
- **PERF**: Performance (SLA violations, degradation, resource limits)
- **DATA**: Data Integrity (loss, corruption, inconsistency)
- **BUS**: Business Impact (UX harm, logic errors, revenue)
- **OPS**: Operations (deployment, config, monitoring)

---

## NFR Planning

**Purpose:** Capture thresholds, planned validation, and evidence for a later `nfr-assess`. This is not an evidence audit.

| NFR Category | Requirement / Threshold | Risk Link | Planned Validation | Evidence Needed |
|---|---|---|---|---|
| Security | Every `/api` route except `/api/health` returns 401 without the right bearer token when `BGB_API_TOKEN` is set (app.py) | R-002 | Enumerated API test over `app.routes` | JUnit report |
| Security | No promotion when the service is publicly invokable and `BGB_API_TOKEN` is unset (epic Story 1.7) | R-002 | Pipeline configuration check | Build log |
| Security | No critical vulnerabilities with an available fix in the image (epic Story 1.9) | R-015 | Trivy, `pip-audit`, `npm audit` | Scan reports, SBOM |
| Data integrity | Every restored file matches source bytes and SHA-256 (README) | R-001, R-003, R-004, R-005 | Integration tests on emulators; canary job; weekly restore drill | JUnit report, drill log |
| Performance | PR pipeline under 10 minutes, main under 25, nightly under 90 (epic 4.1) | R-013 | Cloud Build durations | Build history |
| Performance | Backup job within 2 GiB memory and 14,400 s timeout (terraform/main.tf) | R-011 | Nightly performance dataset | Results JSON with peak memory and duration |
| Performance | Regression alert at more than 20% over trailing 7 day median (epic Story 1.11) | R-011 | Nightly comparison | Trend file |
| Performance | API p95 latency for list and summary endpoints | R-011 | k6 against tagged revision | k6 summary |
| Reliability | Failed production run alerts the approvers group within 30 minutes (epic Story 1.11) | R-007, R-016 | Synthetic failing CI job execution | Alert incident record, received email |
| Reliability | Scheduler triggers `run-due` every 15 minutes; job has `max_retries = 0` (terraform/main.tf) | R-008 | Canary job execution; CLI exit code tests | Job execution logs |
| Maintainability | Line coverage does not fall below the 66% baseline; per module ratchet (epic Story 1.3) | R-001, R-005, R-006 | `pytest-cov` gate | `coverage.xml` |

**Unknown thresholds (clarification needed, no values guessed):**

- API p95 latency target for list and summary endpoints: **UNKNOWN**.
- Size of the performance dataset that represents a real tenant (the epic's 5 GB is an example): **UNKNOWN**.
- Recovery point objective (how stale a backup may be before it is a failure): **UNKNOWN**. Scheduling every 15 minutes is a mechanism, not a target.
- Skipped item threshold that turns a successful run into a "partially failed" alert: **UNKNOWN**.

---

## Entry Criteria

- [ ] Epic 1 decisions D1 to D4 recorded (done 2026-10-31)
- [ ] Required APIs enabled in `aviato-prod-demo-baby-got-back` (Cloud Build, Artifact Registry, Run, Firestore, Storage, Secret Manager, Scheduler, IAM Credentials, Container Scanning)
- [ ] Firestore emulator and `fake-gcs-server` run in Cloud Build and locally (`docker-compose.test.yml`)
- [ ] Northwind fixture usable against emulators, not only memory
- [ ] CI bucket, named Firestore database `bgb-ci` and `bgb-backup-ci` job exist before Story 1.10 tests run

## Exit Criteria

- [ ] All P0 tests passing on PR and main builds
- [ ] All P1 tests passing, or failures waived by a code owner with reason and expiry
- [x] R-001 (score 9) waived by Ben on 2026-10-31; see "Decisions and Waivers"
- [ ] All other high risks mitigated or waived
- [ ] Coverage of `index/firestore.py`, `storage.py`, `googleapi.py` and `cli.py` raised from the baseline, with the ratchet active
- [ ] One successful end to end main build: deploy without traffic, smoke, canary, promote, final smoke
- [ ] One deliberate failed deploy that rolls back automatically

---

## Test Coverage Plan

Test levels follow `test-levels-framework.md`. "Integration" means real code against the Firestore emulator and `fake-gcs-server`, which is the lowest level that can establish behaviour the in-memory fakes do not have. "Deploy" means checks run against the tagged Cloud Run revision or job in the project.

### P0 (Critical)

**Criteria**: Critical business, security, data-integrity, or compliance impact with no safe workaround.

| Requirement | Test Level | Risk Link | Test Count | Owner | Notes |
|---|---|---|---|---|---|
| Index shared behaviour suite: jobs, runs, filesets, entries, block lookups, all index implementations | Integration | R-001 | 10 | DEV | Parametrised fixture yields `MemoryIndex` and Firestore index; one assertion set |
| Block list over 400 hashes, and a backup over 500 writes, on Firestore | Integration | R-001 | 2 | DEV | Directly from REVIEW.md limits |
| Northwind backup then restore, bytes and SHA-256 equal, on emulators | Integration | R-001 | 2 | DEV | Promotes the existing `test_api` journey off memory |
| Split, dedup and restore round trip over random data and sizes | Unit | R-001 | 3 | DEV | `hypothesis`; 0 bytes and exact block multiples |
| Crash after volume upload and before index write, then rebuild and restore all | Integration | R-003 | 2 | DEV | Fault injection on the store or index write |
| Index deleted, `rebuild` result equals the original index | Integration | R-003 | 1 | DEV | "Index is a cache of remote state" (README) |
| Volume store shared behaviour suite: put, get, list, delete, missing object | Integration | R-005 | 6 | DEV | Memory, local directory and GCS store |
| `verify --full` reports a flipped byte and a missing object on the GCS store | Integration | R-005 | 2 | DEV | Existing corrupt volume test covers memory only |
| Retention then compaction, then restore every surviving version | Integration | R-004 | 2 | DEV | Repeats the existing unit scenario on real stores |
| Token gate over every `/api` route: missing, wrong, correct token | API | R-002 | 3 | DEV | Route list read from `app.routes`; health on an explicit allow list |
| Content endpoint rejects `..`, absolute, encoded separators, another job's fileset | API | R-002 | 4 | DEV | |
| Secrets never appear in API responses or log lines | API | R-002 | 2 | DEV | Key JSON, refresh token, API token |
| Promotion refused when the service is public and tokenless | Deploy | R-002 | 1 | DEV | Pipeline check reads live IAM and env |
| Smoke on the tagged revision: health, auth, seed, run, restore, verify | API (deployed) | R-008 | 5 | DEV | CI stores only |
| Canary `bgb-backup-ci` job execution on the new digest | Deploy | R-008 | 1 | DEV | Real Firestore and GCS; catches emulator gaps (R-013) |
| Automatic rollback when post-promotion smoke fails | Deploy | R-008 | 1 | DEV | Verified by a deliberately broken revision |
| UI: load Northwind, run, browse, download file with bytes equal to the fixture | E2E | R-001, R-014 | 2 | DEV | Only journey where the static export and API must work together |

**Total P0**: 49 tests, ~70 to 110 hours (includes the emulator harness and fault injection)

### P1 (High)

**Criteria**: Core, frequent, or complex behavior with material user reach and a limited workaround.

| Requirement | Test Level | Risk Link | Test Count | Owner | Notes |
|---|---|---|---|---|---|
| Delegated token minting: JSON key, keyless via IAM Credentials, OAuth refresh | Unit | R-006 | 4 | DEV | Mock HTTP endpoints |
| Google API error mapping and backoff: 401, 403, 429, 5xx | Unit | R-006, R-007 | 6 | DEV | |
| Recorded response scenarios: Gmail history expiry fallback, Drive shared drive as admin and exports, Contacts token expiry, item deleted mid scan | Integration | R-007 | 8 | DEV | Extends 6 existing source tests; scrubbed recordings |
| "Every user" uses Directory under service account; rejected under OAuth | Unit | R-006 | 2 | DEV | |
| `run-due` CLI picks due jobs and exits non-zero on failure | Integration | R-008, R-007 | 2 | DEV | Exit code drives job failure and alerting |
| Each API route exercised once on the emulator backed runtime | API | R-005 | 12 | DEV | Raises `app.py` and `runtime.py` coverage |
| OpenAPI schema to TypeScript type drift check | Static | R-014 | 1 | DEV | Fails on any diff |
| UI settings: token saved and sent; wrong token shows an error | E2E | R-002, R-014 | 2 | DEV | |
| Container structure: uid 10001, `PORT`, web root present, no `.env` or `data/` | Infra | R-008 | 4 | DEV | |
| Image and dependency scans: Trivy, `pip-audit`, `npm audit` | Static | R-015 | 3 | DEV | |
| Terraform `validate`, `tflint`, `checkov` including ingress and public invoker policy | Static | R-002, R-010 | 3 | DEV | |
| Terraform plan shows no image diff after a pipeline deploy | Infra | R-010 | 1 | DEV | Proves D1 `ignore_changes` |
| CI service account denied write to production bucket and database | Deploy | R-009 | 2 | DEV | Negative IAM checks |
| Smoke configuration asserts it targets CI stores before writing | Deploy | R-009 | 1 | DEV | |
| UTC cron and `run-due` boundaries at minutes 0, 15, 30, 45 | Unit | - | 3 | DEV | Extends existing schedule test |
| Volume cap of 128 MiB enforced; default 50 MiB | Unit | R-011 | 2 | DEV | |
| A failed CI job execution raises the production failure alert | Deploy | R-007, R-016 | 1 | DEV | Same alert policy as production |
| Nightly heartbeat email reaches the approvers group | Deploy | R-016 | 1 | Ben | Confirm first receipt by hand |

**Total P1**: 58 tests, ~45 to 75 hours

### P2 (Medium)

**Criteria**: Secondary behavior with narrower user reach and an acceptable workaround.

| Requirement | Test Level | Risk Link | Test Count | Owner | Notes |
|---|---|---|---|---|---|
| Keep refused with a clear message through API and UI | API, E2E | R-017 | 2 | DEV | Existing unit test covers the source |
| Job form validation for retention and schedule | API (2), E2E (1) | - | 3 | DEV | Rules at API level; one E2E for display |
| Large shared drive pagination | Integration | R-007 | 2 | DEV | Recorded responses |
| Remaining CLI commands: `run`, `verify`, `restore`, `rebuild` | Integration | R-003 | 4 | DEV | `cli.py` is at 0% |
| Performance dataset backup: peak memory, duration, throughput | Performance | R-011 | 1 | DEV | Thresholds UNKNOWN; record baseline first |
| k6 p95 for list and summary endpoints | Performance | R-011 | 2 | DEV | Threshold UNKNOWN |
| Full restore drill and `verify --full` on the CI bucket | Deploy | R-003 | 1 | DEV | |

**Total P2**: 15 tests, ~10 to 20 hours

### P3 (Low)

**Criteria**: Rare, cosmetic, or experimental behavior with minimal impact and an easy workaround.

| Requirement | Test Level | Risk Link | Test Count | Owner | Notes |
|---|---|---|---|---|---|
| `web/src/lib/format.ts` helpers | Unit | - | 3 | DEV | |
| Dashboard empty state with no jobs | E2E | - | 1 | DEV | |

**Total P3**: 4 tests, ~1 to 3 hours

---

## Execution Strategy

**Philosophy:** Run every functional scenario in pull requests while the suite stays under 15 minutes. Defer only work with material infrastructure or duration cost. P0 to P3 describe importance, not when a test runs.

- **Pull request:** static checks, all unit, integration (emulators), API and Playwright E2E tests against the image built in that build, plus burn-in (10 repeats) of new or changed tests. The current Python suite runs in 1.7 s, so the PR budget is dominated by the image build and E2E; Playwright runs in parallel workers to stay inside the 10 minute target.
- **Main:** the PR set, then deploy without traffic, deployed smoke, canary job, promotion, final smoke and rollback check.
- **Nightly:** performance dataset, k6, a full suite run three times to surface flakiness, alert heartbeat and synthetic failure alert.
- **Weekly:** full restore drill.

**Recommended change to the epic:** section 4.3 of the epic runs P2 and P3 tests only at night. Given the suite size, run them on every PR too and keep them non-blocking. Only the performance, drill and alert checks need to wait for the nightly schedule.

---

## Resource Estimates

### Test Development Effort

| Priority | Count | Effort | Notes |
|---|---|---|---|
| P0 | 49 | ~70 to 110 hours | Emulator harness, fault injection, deploy smoke and rollback |
| P1 | 58 | ~45 to 75 hours | Recording setup and scrubbing, container and IAM checks |
| P2 | 15 | ~10 to 20 hours | Performance baseline needs one tuning pass |
| P3 | 4 | ~1 to 3 hours | |
| Pipeline build (not tests) | - | ~40 to 70 hours | Triggers, Terraform for CI resources, gate script, notifier |
| **Total** | **126** | **~165 to 280 hours** | **~4 to 7 weeks for one engineer** |

### Prerequisites

**Test Data:**

- Northwind demo fixture (exists in `src/bgb/sources/demo.py`), made usable against emulators
- `BytesSource` helper (exists in `tests/helpers.py`) for synthetic files
- Random data generator for property tests and the performance dataset
- Scrubbed recorded Google API responses under `tests/fixtures/google/`

**Tooling:**

- `pytest-cov`, `pytest-xdist`, `pytest-repeat`, `hypothesis` for the Python suite
- Firestore emulator and `fake-gcs-server` for integration tests
- `@playwright/test` with `@seontechnologies/playwright-utils` for E2E (not installed yet; TEA config requires it)
- `openapi-typescript` for the drift check
- Trivy, `pip-audit`, `container-structure-test`, `tflint`, `checkov`, `gitleaks`, k6

**Environment:**

- Cloud Build triggers, Artifact Registry and CI service account in `aviato-prod-demo-baby-got-back`
- CI bucket, `bgb-ci` Firestore database and `bgb-backup-ci` job, isolated from production
- Cloud Monitoring email channel to `aviato-prod-demo-baby-got-back-approvers@aviato.consulting`

---

## Quality Gate Criteria

### Pass/Fail Thresholds

- **P0 pass rate**: 100%, no retries, no waivers
- **P1 pass rate**: 100%, or each failure waived by a code owner with reason and expiry. This is stricter than the usual 95% and matches epic Story 1.12
- **P2/P3 pass rate**: ≥90%, informational, failures open a ticket
- **High-risk mitigations**: R-001 complete before the first production tenant; all other scores of 6 or more complete or waived

### Coverage Targets

- **Line coverage**: never below the 66% baseline; per module ratchet on `engine.py`, `volume.py`, `retention.py`, `storage.py`, `schedule.py`, `index/`
- **Critical modules** (`engine.py`, `volume.py`, `retention.py`, `storage.py`, `index/firestore.py`): ≥80%
- **Security scenarios**: 100% of `/api` routes covered by the auth test
- **Edge cases**: every limit named in README or REVIEW.md (400 hash shard, 500 write transaction, 128 MiB volume, 25% compaction) has a test

### Non-Negotiable Requirements

- [ ] All P0 tests pass
- [ ] No high risk (≥6) item unmitigated without a recorded waiver
- [ ] SEC category tests pass 100%
- [ ] Performance thresholds are agreed before the PERF gate is enforced; until then results are recorded, not gated
- [ ] Planned NFR evidence exists, or `nfr-assess` has recorded CONCERNS or waivers

---

## Mitigation Plans

### R-001: Production index untested (Score: 9, BLOCK)

**Mitigation Strategy:** Build the parametrised index fixture so every index behaviour test runs against `MemoryIndex` and the Firestore index on the emulator. Add shard (over 400 hashes) and large backup (over 500 writes) tests. Run the Northwind restore journey on emulators. Back this with the canary job against real Firestore at deploy time.
**Owner:** Dev (bgb)
**Timeline:** Milestone 2 of the epic; before the first production tenant
**Status:** Accepted risk (waived by Ben, 2026-10-31). Acceptance tests written in `tests/integration/test_firestore_index.py` and passing against the memory and file indexes; Firestore variants skipped and assumed to pass. Emulator harness deferred.
**Verification:** Originally: `index/firestore.py` coverage at or above 80%, with all P0 rows linked to R-001 passing in a PR build. Under the waiver: the Story 1.10 canary job against real Firestore is the remaining check.

### R-002: Backup content exposed through the API (Score: 6)

**Mitigation Strategy:** Enumerated route auth test, content endpoint negative tests, secret leakage tests, and a promotion check that blocks a public tokenless service.
**Owner:** Dev (bgb)
**Timeline:** Milestone 2
**Status:** Planned
**Verification:** Adding an unauthenticated test route makes the build fail

### R-003: Crash between upload and index write (Score: 6)

**Mitigation Strategy:** Fault injection test, then `rebuild`, then full restore, on emulators; weekly restore drill.
**Owner:** Dev (bgb)
**Timeline:** Milestone 2
**Status:** Planned
**Verification:** Crash test passes on both index implementations

### R-005: GCS store untested (Score: 6)

**Mitigation Strategy:** Volume store shared behaviour suite on `fake-gcs-server`; verify tests on GCS; canary job on the real bucket.
**Owner:** Dev (bgb)
**Timeline:** Milestone 2
**Status:** Planned
**Verification:** `storage.py` coverage at or above 80%

### R-006: Google auth paths untested (Score: 6)

**Mitigation Strategy:** Unit tests for all three credential paths and error mapping, with mocked endpoints.
**Owner:** Dev (bgb)
**Timeline:** Milestone 5
**Status:** Planned
**Verification:** `googleapi.py` coverage raised from 23%; each path has a passing test

### R-007: Google side changes undetected (Score: 6)

**Mitigation Strategy:** Recorded response suite including error paths; production failure and partial failure alert; review D2 before the first tenant.
**Owner:** Dev (bgb), Ben for D2
**Timeline:** Milestone 5
**Status:** Planned
**Verification:** Synthetic failed job execution produces an email to the approvers group

### R-008: Bad image reaches users (Score: 6)

**Mitigation Strategy:** Digest promotion, container structure tests, no-traffic revision with smoke and canary, automatic rollback, CLI `run-due` tests.
**Owner:** Dev (bgb)
**Timeline:** Milestone 4
**Status:** Planned
**Verification:** A deliberately broken revision is never promoted, and a revision failing after promotion is rolled back

### R-012: Demo tier expiry (Score: 6)

**Mitigation Strategy:** Every CI resource created by Terraform in this repo. Extend `owner_until` in the landing zone YAML, or raise the tier.
**Owner:** Ben
**Timeline:** 2026-11-23
**Status:** Planned
**Verification:** Landing zone PR merged with a later date or a new tier

---

## Decisions and Waivers

### W-001: R-001 accepted without a Firestore run

| Field | Value |
|---|---|
| Date | 2026-10-31 |
| Decided by | Ben |
| Risk | R-001, score 9 (BLOCK): Firestore index untested |
| Decision | Treat R-001 as sufficiently derisked. Assume the Firestore variants of the R-001 acceptance tests pass. |
| Evidence at decision | Four acceptance tests (AC-1 to AC-4) written; the four memory and file variants pass; the four Firestore variants have **never run**, because no emulator was available. `index/firestore.py` line coverage is still 0%. |
| Remaining check | The Story 1.10 canary job runs a real backup against real Firestore (the `bgb-ci` database) before any revision gets traffic. |
| Residual risk | A Firestore-specific defect is found at the canary stage rather than on the PR, or in production if Story 1.10 has not landed yet. The three code observations in the ATDD checklist (duplicate detection by exception class name, `select([])` in `count_blocks`, non-atomic fileset batches) are unverified. |
| Deferred work | Emulator harness (`docker-compose.test.yml`, Cloud Build emulator step, removing the skip marker). The tests stay in the repo, skipped, ready to enable. |
| Revisit when | Any change to `src/bgb/index/firestore.py`; any canary or production run failure that involves the index; or before the first customer tenant, whichever comes first. |

TEA note: this waiver accepts a score 9 risk based on reasoning, not on a test run. The tests are written and the harness is small (~6 to 10 hours), so the cheapest time to close the gap is the next change to the Firestore index.

---

## Assumptions and Dependencies

### Assumptions

1. The Firestore emulator and `fake-gcs-server` are close enough to the real services for PR gating; the canary job against real services catches the rest (R-013).
2. The Google API client honours `FIRESTORE_EMULATOR_HOST` and `STORAGE_EMULATOR_HOST` as bgb builds its clients today. If not, a small injection point is needed (epic Story 1.4).
3. One engineer does the work. Estimates scale roughly but not linearly with more people, because the emulator harness comes first.
4. Owners are given as roles until named people are assigned.

### Dependencies

1. APIs enabled and CI service account created - required before Story 1.1 can run
2. Landing zone decision on the Demo tier - required by 2026-11-30
3. Playwright and `playwright-utils` installed through the TEA framework workflow - required before the E2E rows

### Risks to Plan

- **Risk**: The emulator harness takes longer than planned.
  - **Impact**: P0 data integrity rows slip, and R-001 stays at BLOCK.
  - **Contingency**: Ship the Firestore suite first, then GCS; run the canary job by hand until Story 1.10 lands.
- **Risk**: Unknown NFR thresholds are never set.
  - **Impact**: Performance results are recorded but never gate anything.
  - **Contingency**: Use the first two weeks of nightly results as the baseline and propose thresholds from that data.

---

## Interworking & Regression

| Service/Component | Impact | Regression Scope |
|---|---|---|
| **Backup engine** (`engine.py`, `volume.py`) | Shared behaviour suites move tests onto fixtures | All 8 existing `test_engine.py` tests must pass unchanged in intent |
| **Index** (memory, file, Firestore) | New parametrised suite | `test_file_index_reloads_a_job`, `test_rebuild_index_from_volumes` |
| **Sources** (Gmail, Drive, Contacts, Keep) | New recorded and error tests | All 7 existing source tests |
| **Retention and schedule** | Boundary tests added | All 4 existing `test_retention.py` tests |
| **API and web UI** | Auth, route and E2E tests added | `test_demo_backup_restore_and_second_run` |
| **Terraform** | CI resources and `ignore_changes` added | Plan for production resources shows no unintended change |
| **Cloud Scheduler to Cloud Run job** | Job image changes through the pipeline | Canary job execution and the next scheduled `run-due` succeed |

---

## Follow-on Workflows (Manual)

- Run `/bmad-testarch-framework` to install Playwright and `playwright-utils` before the E2E rows.
- Run `/bmad-testarch-atdd` to write failing P0 tests for R-001, R-002 and R-003 first.
- Run `/bmad-testarch-ci` to scaffold the Cloud Build files from this plan.
- Run `/bmad-testarch-nfr` once nightly performance and alert evidence exists.

---

## Approval

**Test Design Approved By:**

- [ ] Product owner: ________ Date: ________
- [ ] Tech lead: ________ Date: ________
- [ ] QA lead: ________ Date: ________

**Comments:**

---

## Appendix

### Knowledge Base References

- `risk-governance.md` - Risk classification framework
- `probability-impact.md` - Risk scoring methodology
- `test-levels-framework.md` - Test level selection
- `test-priorities-matrix.md` - P0 to P3 prioritization
- `nfr-criteria.md` - NFR validation planning

### Related Documents

- Epic: `_bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md`
- Architecture: `README.md`, `REVIEW.md`, `terraform/main.tf`
- PRD and tech spec: none exist

---

**Generated by**: BMad TEA Agent - Test Architect Module
**Workflow**: `bmad-testarch-test-design`
**Version**: 4.0 (BMad v6)
