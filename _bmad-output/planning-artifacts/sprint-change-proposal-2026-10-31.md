# Sprint Change Proposal: realign Epics 2 to 7 and 10 with the current code

**Status:** Approved by Ben, 2026-10-31. Applied to `epics.md`, `bgb-fix-plan.md` and `sprint-status.yaml`. Section 4.9 (Epics 1, 8, 9) is for their owners.
**Date:** 2026-10-31
**Workflow:** bmad-correct-course (batch mode)
**Requirements baseline:** `epics.md` requirements inventory (FR1 to FR49) and `bgb-fix-plan.md`, standing in for a PRD (agreed with Ben). No `AGENTS.md`.
**Trigger:** readiness gate FAIL, `implementation-readiness.md`

---

## 1. Issue summary

The code review, `bgb-fix-plan.md` and `epics.md` (Epics 2 to 7 and 10) were written against commit `e3b0171`. Commit `5d1c615` ("Make backups resumable, lease-guarded, and harder to delete", 11:59) landed while planning was under way. It already implements a large part of Epics 2, 3 and 4, sometimes with a different design. The readiness check found that a developer working from the stories as written would rebuild existing code or contradict it, and would have no recorded decision on retention values or checkpoint design.

**Category:** misunderstanding of the baseline (planning ran against stale code), not a requirement change.

**Evidence (checked in the code at HEAD `eb307cd`):**

| In the code now | Where |
|---|---|
| Job lease in the index: holder is the Cloud Run execution name, `LEASE_TTL` 30 min, `HEARTBEAT` 60 s. Held by backup, retention, compaction, prune, rebuild and delete (`Engine.leased`) | `engine.py:40-130` |
| Abandoned runs closed by the next lease holder, marked `failed` with "abandoned: the run stopped without finishing (timeout or crash)" | `engine.py:_close_abandoned` |
| Checkpoint every volume, at least every 5 min or 1,000 entries; the next run merges it and does not re-read finished files | `engine.py:44-45, 196-203`, `test_killed_run_resumes_without_rereading` |
| `run_due` skips leased jobs and catches per-job errors | `runtime.py:77-95` |
| `busy()` with a 24 h horizon still defined but no longer called | `engine.py:749` |
| Maintenance (prune, rebuild, delete) runs as a backup-job execution with overrides, because only the job's account can delete objects; the UI account can only read them | `runtime.py:in_backup_job`, `app.py:240-254`, `main.tf:143,149` |
| `min_object_age` from `BGB_OBJECT_RETENTION_DAYS`; age measured from the index `created_at`; compaction skips young volumes; retention marks volumes `expired` and `sweep_expired` deletes them later; deletes refused by retention raise `Retained` | `engine.py:500-525`, `storage.py:91-93`, `test_retention_defers_deletes_until_objects_are_old_enough` |
| Job delete removes the index and leaves retained objects in the bucket | `runtime.py:delete_job` |
| Bucket retention **30 days** default, soft delete **90 days** default, `lock_retention` variable (default false), optional separate `backup_project_id` | `variables.tf:37-59`, `main.tf:88-98` |
| `roles/run.jobsExecutorWithOverrides` granted to the UI service account | `main.tf:300` |
| Retries: 429, 5xx, and 403 only for `rateLimitExceeded`, `userRateLimitExceeded`, `quotaExceeded`; honours `Retry-After` | `googleapi.py:19-55`, `test_rate_limit_403_is_retried_but_permission_403_is_not` |
| Drive media streamed in 8 MiB chunks; reader returns full blocks | `googleapi.py:354`, `test_media_stream_returns_full_blocks_and_holds_one_chunk` |

Not found in the code: Firestore point-in-time recovery, per-job prefix and block size, fileset completeness flag, multi-part file lists, carry-forward on scope failure, departed-user handling, API token header changes, alerting, restore write-back, quota pacing, phased onboarding.

## 2. Impact analysis

### Epic impact

| Epic | Impact |
|---|---|
| 2 | Stories 2.1, 2.3, 2.4 and 2.8 are largely implemented. 2.2 changes (abandoned runs). 2.5, 2.6, 2.7, 2.9 still needed, with notes. |
| 3 | 3.3 largely implemented. 3.6 adds the final deletion date. Others unchanged. |
| 4 | 4.1 and 4.2 largely implemented. 4.3 differs from the code. 4.4 differs on job delete. 4.5 values depend on D1. 4.6 unchanged in substance. |
| 5 | 5.4 Terraform half done (role on the UI account). 5.1 and 5.2 depend on Epic 8 Story 8.4 for deploy parameters. |
| 6 | Wrong Epic 1 story for the channel; duplicate failed-run alert; new statuses to handle. |
| 7 | Execution model undecided (D3); quota pacing and scope listing missing. |
| 10 | 10.1 overlaps the existing checkpoint design (D2). 10.2 and 10.4 need infrastructure and scope listing. |

No epic becomes obsolete. No new epic is needed. Order stays 2, 3, 4, 5, 6, 7, 10, but Epic 2 shrinks a lot.

### Artifact conflicts

- **PRD substitute (`epics.md` requirements):** FR2 (abandoned runs), FR25 (age source), FR27 (pending versions), FR28 (job delete) and the Additional Requirements (retention values, deploy parameters) need small edits. MVP scope is unchanged.
- **Architecture research** (`research/technical-google-workspace-backup-architecture-rev-2026-10-31/`): consistent with the code; no change proposed.
- **`bgb-fix-plan.md`:** superseded where the code already delivers. Add a header note rather than rewriting it.
- **Other epics (owned by other sessions):** Epic 1 (channel and alert ownership), Epic 8 (deploy parameters, Cloud Quotas API), Epic 9 (scope catalog). Proposed below as cross-references; their owners apply them.
- **`sprint-status.yaml`:** story statuses change (Section 4.6). No stories added or removed.

## 3. Recommended approach

**Direct adjustment (Option 1), with six decisions for Ben.** Edit the stories in place to describe what remains, mark implemented stories `review` so a developer confirms them against their acceptance criteria and tests, and record the decisions below. Rollback of `5d1c615` is not viable: it is tested, it matches most of the plan's intent, and reverting it would throw away working code. An MVP reduction is not needed.

- **Effort:** low (document edits only).
- **Risk:** low, if the six decisions are made now. Medium if they are left for developers.
- **Timeline:** Epic 2 drops from 9 stories of new work to 5, plus 4 verifications.

### Decisions for Ben

**Decided 2026-10-31 (Ben): all six recommendations accepted.** D1 (a) 30 days retention and 90 days soft delete; D2 (a) extend the existing resume design; D3 (a) restores run as job executions; D4 (a) tombstone job delete; D5 (a) Epic 6 owns the failed-run alert; D6 (a) scopes listed in the source catalog.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Bucket retention and soft delete periods | (a) Keep the code: 30 days retention, 90 days soft delete. (b) Plan: 7 and 7. | **(a) 30 and 90.** Already built and tested, a longer ransomware window, and 90 days is the maximum soft delete. Cost: compaction and deletes wait 30 days, so storage runs higher, and a departed user's or deleted job's data is fully gone about 4 months after it becomes eligible. |
| D2 | Story 10.1 (long first backups) | (a) Extend the existing checkpoint and resume design. (b) Replace it with the planned clean stop and partial versions. | **(a) Extend.** Resume already works with a 24 h job timeout and 3 retries. Add only what is missing: a resumed run must not count as failed, and progress must be visible. Partial restorability comes from phased onboarding (10.3), where each cohort's run completes a version. |
| D3 | Where restore runs | (a) As a backup-job execution with overrides, holding the lease, like maintenance. (b) In the API service. | **(a) Job execution.** API requests time out at 3,600 s, and large or multi-user restores will not finish in one request. Dry runs also run as a job for plans over a size threshold. |
| D4 | Deleting a job that still has protected objects | (a) Tombstone: mark the job deleted and hidden, and let the sweep delete objects as they come out of retention, then remove the job record. (b) Refuse with 409 until every object is old enough (current Story 4.4). | **(a) Tombstone.** Closer to the current code, and nothing is left orphaned. Today the code deletes the index and leaves retained objects that nothing ever removes. |
| D5 | Who owns the failed-run alert | (a) Epic 6 owns all run-outcome alerts; Epic 1 Story 1.11 drops its failed-run alert and keeps its nightly drill alerts. (b) Epic 1 owns failed runs; Epic 6 covers only timed-out, warnings and stale. | **(a) Epic 6.** One place for run outcomes, so one email per problem. |
| D6 | Where extra scopes are listed (restore write scopes, Reports usage scope) | (a) In the source catalog from Epic 9 Story 9.1, as capabilities ("restore", "estimate") alongside sources, so the README delegation table has one source. (b) Separately in each story's README section. | **(a) Source catalog.** |

## 4. Detailed change proposals

Notation: **Status** is the proposed `sprint-status.yaml` value. "Review" means the code is believed to meet the story; a developer confirms each acceptance criterion against code and tests, and writes only the missing pieces.

### 4.1 Epic 2

**Story 2.1: One operation per job at a time** → Status: review

OLD: Firestore transaction records `active_run_id`, `lease_expires` and `heartbeat`; a "Run now" execution re-claims with the same run id.
NEW: The job lease already exists (`Engine.leased`): the holder is the Cloud Run execution name, so a retry of the same execution takes over its own lease; TTL 30 min; heartbeat every 60 s; held by every operation that changes stored data. Acceptance criteria are rewritten to that design. A second execution gets a conflict, and a queued run that loses the race is marked failed with the reason. Remaining work: none expected; confirm `test_second_execution_cannot_run_while_the_lease_is_held` and `test_expired_lease_is_taken_over` cover the criteria.
Rationale: implemented by `5d1c615` with a different but equivalent key.

**Story 2.2: Runs that die are marked timed out** → Status: backlog (changed)

OLD: an expired run is marked `timed_out`; remove the 24 h `busy()` horizon.
NEW: `_close_abandoned` already closes runs left by a killed execution, but marks them `failed` ("abandoned"). Change them to `timed_out`, keeping the message that progress was kept. Remove the unused `busy()` function. Add: a `timed_out` run whose work is resumed by the next execution links to that run, so the history reads as one backup.
Rationale: with D2 and Epic 6, a resumed run must not alert as a failure.

**Story 2.3: Maintenance waits for the run** → Status: review, with one gap

OLD: API returns 409 directly while a run owns the job.
NEW: Maintenance runs as a backup-job execution that takes the lease (done). Remaining gap: before starting a maintenance execution, the API checks `lease_holder` and returns 409 with the holder, instead of starting an execution that will fail. CLI `run`, `run-due` and `rebuild` already take the lease.

**Story 2.4: One failing job never stops the schedule** → Status: review, with one gap

NEW: `run_due` already skips leased jobs and catches per-job errors. Remaining gap: an error before a run record exists is recorded as a `failed` run, and the CLI lists failed jobs and exits non-zero.

**Story 2.5: Each job keeps its own storage settings** → Status: backlog

ADD note: the bucket may be in a separate project (`backup_project_id`); the bucket-change guard applies to that setting too.

**Story 2.6: Rebuild never wipes the index by mistake** → Status: backlog

ADD: rebuild sets each volume's `created_at` from the Cloud Storage object's creation time, not "now", so retention timing survives a rebuild (see 4.1).

**Story 2.7: A partial backup is never used as the base** → Status: backlog

ADD: checkpoint entries (`list_checkpoint`) are not a fileset and are never listed as a version; they are cleared only after the fileset is marked complete.

**Story 2.8: Large Drive files stream in full blocks** → Status: review, with one gap

NEW: streaming in 8 MiB chunks and full-block reads are done (`test_media_stream_returns_full_blocks_and_holds_one_chunk`). Remaining gap: a download that fails mid-file resumes from the bytes already read (Range), or an export restarts the file cleanly with a fresh hasher.

**Story 2.9:** unchanged.

### 4.2 Epic 3

**Story 3.3: Throttling and network blips do not fail backups** → Status: review, with one gap

NEW: 429, 5xx and rate-limit 403s are retried with `Retry-After` (done). Remaining gap: connection errors and timeouts are retried, with jitter.

**Story 3.6: Departed users keep their backup for as long as policy requires** → Status: backlog

ADD acceptance criterion: the job view and the audit record show both the date a departed user's data becomes eligible for removal and the expected final deletion date (eligible date, plus the version retention needed to age it out, plus bucket retention, plus soft delete). The job view explains that data is held until then.
Rationale: with D1, final deletion can be about 4 months after eligibility; compliance policies may need the real date.

**Story 3.12: Sharing permissions are backed up** → ADD: permission reads go through the quota pacing in Story 10.2.

Other Epic 3 stories unchanged.

### 4.3 Epic 4

**Story 4.1: Deletes respect a minimum object age** → Status: review, with one gap

OLD: age measured from the Cloud Storage object's creation time.
NEW: `min_object_age` from `BGB_OBJECT_RETENTION_DAYS` and `Retained` handling exist. Keep measuring from the index `created_at` (it is written just after upload, so it never deletes early). Remaining gap: rebuild restores `created_at` from object metadata (Story 2.6), so a rebuild does not delay every delete by a full retention period.
FR25 edit: "measured from the time the object was written, as recorded in the index (or, after a rebuild, the object's creation time)".

**Story 4.2: Compaction leaves young volumes alone** → Status: review.

**Story 4.3: Retention finishes young deletes later** → Status: backlog (differs from code)

NEW wording of the gap: the code removes an expired version from the index at once and keeps only its objects (marked `expired`) until the sweep. Ben decided versions waiting for deletion stay visible, marked "Scheduled for removal", and restorable until removed. So the fileset row and its entries are kept, marked `pending_delete`, until `sweep_expired` deletes its file list object; then the row is removed. Block volumes still referenced by a pending version are not compacted.

**Story 4.4: Prune and job delete respect the protection window** → Status: backlog (per D4)

NEW (if D4 = tombstone): prune skipping retained objects is done. Job delete marks the job `deleted`, hides it, stops schedules, and deletes objects as they come out of retention through the sweep; the job record is removed once its last object is gone. The response gives the expected completion date.

**Story 4.5: The bucket and index are protected (unlocked)** → Status: backlog, reduced

NEW: bucket soft delete, retention policy and `lock_retention` exist in Terraform. Remaining: set defaults per D1; add Firestore point-in-time recovery; confirm versioning stays off; confirm the separate `backup_project_id` path works with the protections. `BGB_OBJECT_RETENTION_DAYS` must match the bucket's period and, under Epic 8 DEP-D1, is passed as a Cloud Deploy parameter (Story 8.4).

**Story 4.6: Lock the protection after sign-off** → Status: backlog. Wording follows D1 (the trial must last at least one full retention period, so compaction and the sweep are seen deleting real objects).

### 4.4 Epic 5

**Story 5.1: The API refuses anyone without the token** → ADD dependency: `BGB_REQUIRE_TOKEN` and `BGB_CORS_ORIGINS` are Cloud Deploy parameters (Epic 8 Story 8.4). The token value is a Secret Manager reference if Epic 8 Q1 is answered that way.

**Story 5.2: Admins sign in through IAP** → ADD dependency on Story 8.4 for `BGB_REQUIRE_TOKEN`.

**Story 5.4: "Run now" works in the cloud** → Status: review

OLD: role granted to the runtime service account.
NEW: `roles/run.jobsExecutorWithOverrides` is granted to the UI service account, which is the account that starts the execution. That is correct. Remaining: confirm "Run now" moves a run from queued to running in a deployed environment.

Other Epic 5 stories unchanged.

### 4.5 Epic 6

**Story 6.1:** logged outcomes include `timed_out` (Story 2.2) and the onboarding states from Epic 10.

**Story 6.2:** OLD "the email channel from Epic 1 Story 1.11" → NEW "the email channel created by Epic 1 Story 1.12". ADD (per D5): this story owns the failed-run alert; Epic 1 Story 1.11 drops its duplicate.

**Story 6.3:** ADD: a job whose first backup is still in progress (resuming, or onboarding under Epic 10) is not stale while it is making progress; stale means no successful run and no progress for N hours.

**Story 6.4:** ADD: the emailer URL and audience are stored in Settings (Firestore), not environment variables, so they do not depend on Cloud Deploy parameters.

FR38 edit: "Epic 1 Story 1.11" → "Epic 1 Story 1.12".

### 4.6 Epic 7

**Stories 7.2 to 7.5:** ADD (per D3): restores and large dry runs run as backup-job executions with overrides, hold the job's lease, checkpoint per item, and resume on retry. The API only creates plans, starts executions and reports progress.

**Story 7.1:** ADD (per D6): write scopes are declared as a "restore" capability in the source catalog (Epic 9 Story 9.1), which generates the README delegation table.

**All restore stories:** Google API calls go through Story 10.2's pacing.

### 4.7 Epic 10

**Story 10.1: A first backup continues across runs** → rewritten (per D2)

NEW title: "Long backups resume without false alarms".
NEW acceptance criteria:
- A run stopped by the job timeout or a crash, with a checkpoint, is marked `timed_out` and resumed by the next execution (retry or schedule) without re-reading finished files (existing behaviour, Story 2.2).
- The job view shows a backup in progress across executions as one backup, with files and bytes done so far.
- Alerts do not fire for a resumed backup that is still making progress; they fire if three consecutive executions make no progress (Epic 6).
- The job timeout (24 h, up to 168 h) and retries (3) are documented as the levers for very large users.
Removed: the clean stop before the time limit, the `continuing` status and partial versions.

**Story 10.2: Google API calls stay within a quota budget** → ADD: enable the Cloud Quotas API and grant the runtime account quota read access (proposed for Epic 8 Story 8.1). ADD: pacing covers every Google API caller: Epic 3 sources, Story 3.12 permission reads, Epic 7 restores and Epic 9 sources.

**Story 10.4: Know how long onboarding will take** → ADD (per D6): the Reports usage scope is declared as an "estimate" capability in the source catalog.

### 4.8 Requirements inventory and Additional Requirements (epics.md)

- FR2: "marked `timed_out`" stays; add "and resumed by the next execution".
- FR25: age source wording as in 4.3.
- FR27: "keeps the version visible and restorable, marked scheduled for removal, until its objects are deleted".
- FR28: per D4.
- FR38: Story 1.12.
- Additional Requirements, Infrastructure: retention and soft delete values per D1; note the existing `backup_project_id`; note that `BGB_OBJECT_RETENTION_DAYS`, `BGB_REQUIRE_TOKEN` and `BGB_CORS_ORIGINS` are Cloud Deploy parameters (Epic 8 DEP-D1, Story 8.4); Cloud Quotas API for Story 10.2.
- Add a "Baseline" note under Overview: stories were realigned to commit `5d1c615` on 2026-10-31.

### 4.9 Cross-references for other epics (owners apply)

- **Epic 1 Story 1.11:** drop the failed-run alert (per D5); keep nightly drill alerts. Story 1.12 owns the channel.
- **Epic 8 Story 8.1:** enable the Cloud Quotas API; grant quota read to the runtime account.
- **Epic 8 Story 8.4:** carry `BGB_OBJECT_RETENTION_DAYS` over from Terraform; add `BGB_REQUIRE_TOKEN` and `BGB_CORS_ORIGINS` (dev only) as parameters.
- **Epic 9 Story 9.1:** the catalog also lists capabilities with scopes (restore write scopes, Reports usage scope).

### 4.10 Other artifacts

- `bgb-fix-plan.md`: add a header note that `5d1c615` implemented parts of Stages 1 to 3 and 5, and that `epics.md` is now the source of truth.
- `sprint-status.yaml`: set 2-1, 2-3, 2-4, 2-8, 3-3, 4-1, 4-2, 5-4 to `review`; all others stay `backlog`. Rename the key for 10.1 to match its new title.

## 5. Implementation handoff

**Scope: Moderate** (backlog reorganisation; no code changes in this proposal).

| Role | Responsibility |
|---|---|
| Ben (product owner) | Make decisions D1 to D6. Approve this proposal. |
| Planning session (this one) | Apply sections 4.1 to 4.8 and 4.10 to `epics.md`, `bgb-fix-plan.md` and `sprint-status.yaml` after approval. |
| Owners of Epics 1, 8 and 9 | Apply section 4.9 cross-references. |
| Readiness check | Re-run `bmad-sprint-planning` readiness for Epics 2 to 7 and 10 after the edits. |
| Developer (later, when Ben says build) | For `review` stories, confirm each acceptance criterion against code and tests and close the listed gaps only. |

**Success criteria:** the readiness check returns PASS or CONCERNS (no FAIL) for Epics 2 to 7 and 10; every story describes only work not already in `5d1c615`, or is marked `review`; decisions D1 to D6 are recorded in `epics.md`.
