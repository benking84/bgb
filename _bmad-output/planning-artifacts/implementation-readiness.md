# bgb implementation readiness gate

**Status:** Draft for review
**Date:** 2026-10-31, re-run at 22:00 for all epics (1 to 10) after decision D11 and the fixes for N1 to N3
**Skill:** bmad-sprint-planning (readiness and validate intents)
**Scope:** `epics.md` (Epics 2 to 7 and 10), `epics/epic-1-pipeline-quality-gates.md`, `epic-8-deployment-pipeline.md`, `epic-9-workspace-source-coverage.md`, `sprint-change-proposal-2026-10-31.md`, with the code at HEAD (`eb307cd`).
**History:** FAIL (12:40, the plan was written against code from before `5d1c615`), CONCERNS (14:00, after the correct-course pass), CONCERNS (21:50, after D7 to D10), PASS (22:00).

## Verdict: PASS for all ten epics

A developer can build these epics without inventing decisions that nothing records. Build order: Epic 8 (8.1 to 8.3), then Epic 1 from Story 1.1 (8.4 before 1.10), then Epics 2, 3, 4, 5, 6, 7 and 10. Epic 9 comes after Epic 3, Story 3.6 and Story 10.2.

## 21:50 concerns: where they stand

| # | Concern | Now |
|---|---|---|
| N1 | Tests and CI could not call an IAP-only API | **Resolved by D11.** Story 5.1 states there is no bypass, flag or test-key setting, and production trusts only Google's IAP keys. Tests patch the verifier's Google key fetch inside the test process and sign headers with a key they generate. Local development uses an entry point outside the shipped package. A build test (Story 5.1) and an image check (Story 1.7) fail if the dev entry point or test key material ships. Story 1.4 API tests use the in-process patch. Story 1.8 runs the UI against mocked API responses checked against the OpenAPI schema, including a signed-in identity and an expired session. Real end-to-end coverage comes from Story 1.4 (in-process) and Story 1.10 (through real IAP). |
| N2 | Post-deploy checks could not get through IAP | **Resolved.** Story 5.2 adds a dedicated smoke-test service account that has IAP access only and can mint an ID token for the IAP audience. Story 1.10's smoke tests run as that account through real IAP. They check that a signed-in request succeeds and that a request with no sign-in is refused at the edge. The app's own header check is left to unit tests, which is correct. |
| N3 | Decision ID overlap; Epic 9 header | **Resolved.** `epics.md` and Epic 9 both state how decision IDs are cited across documents. Epic 9's header says it needs Epic 3 and Story 10.2 first, but not Epic 7. |

## Optional tidy-ups (not findings)

- Epic 1 Story 1.8's last task still says the PR step "starts the PR image, waits on `/api/health`, then runs Playwright", and Story 1.9 says "Story 1.8 reuses the running container". This is consistent with the new acceptance criteria if the image is only serving the static UI at `/` (which Story 5.1 does not gate) while Playwright intercepts every `/api/*` call. A short note saying so would stop a reader thinking the E2E tests depend on the real API.
- The remaining mentions of `BGB_API_TOKEN` (Story 5.1's removal criterion, Epic 8 Q1, Epic 1's current-state table) are intentional, because they describe what is being removed.

## Still to watch (not findings)

- **D10:** the `owner_until` extension must happen before 2026-11-30 and before Story 8.1 is applied.
- **Story 4.6:** permanently locking retention in a time-boxed Demo project. Decide on the tier at sign-off, after at least one 30-day retention period of clean running.
- **Emailer delivery** depends on the emailer team (already recorded).

## Checks performed

- All 49 FRs and UX-DR1 to UX-DR6 have "Covers:" lines (checked by script).
- Every decision is recorded where it is used: `epics.md` D1 to D11, Epic 1 D1 to D5, Epic 8 DEP-D1 to DEP-D4, Epic 9 D1 to D4. No open questions remain in any epic.
- Cross-epic links agree:
  - **Alerting:** Epic 6 owns run-outcome alerts, Story 1.12 owns the channel, D8 sets the group, and Story 6.1 defines the progress rule.
  - **Runtime configuration:** values are either Story 8.4 deploy parameters or stored in Settings.
  - **Authentication:** IAP only across Stories 1.4, 1.7, 1.8, 1.10 and 5.1 to 5.3, plus D7 and D11.
  - **Restore:** job executions (D3) holding clean-up only (D9), with quota pacing from Story 10.2.
  - **Scopes:** declared as capabilities in the Story 9.1 catalog (D6).
- Baseline claims in "Baseline: implemented" notes still match the code at HEAD (checked at 14:00; no code has changed since).

## sprint-status.yaml

- `validate`: valid, no problems. `generate --dry-run` against all four epic files: **in sync** (no new entries, no orphans). Nothing was written in this run.
- 10 epics, 75 stories. 82 entries in backlog, 3 in `review` (2.1, 4.2, 5.4), 10 optional retrospectives.
- Changes this session, all through the skill's script except where noted:
  - Story 3.12 and Epic 10 added (13:30).
  - Story 3.6 key renamed (13:45).
  - Five stories with gaps set back to `backlog` by hand at Ben's request, because the script never lowers a status (14:10).
  - Story 5.1 and 6.2 keys renamed (21:50).

  Copies of each earlier file are in `/private/tmp/claude-502/-Users-Ben-Documents-Code-bgb/5b3e85a5-2002-484f-8f55-76ac5c2a5420/scratchpad/`.
- The file lists epics by number. Build order starts with Epic 8, so start there explicitly when building begins.
