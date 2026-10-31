---
status: final
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
inputDocuments:
  - _bmad-output/planning-artifacts/bgb-fix-plan.md
  - REVIEW.md
  - README.md
  - _bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md (reference only, to avoid overlap)
---

# bgb - Epic Breakdown

## Overview

This document breaks bgb's backlog into epics and stories. There is no PRD or architecture document. The backlog is the revised, staged fix plan (`bgb-fix-plan.md`, from a full code review, a plan review and a roundtable with Ben), with behaviour and constraints from `REVIEW.md` and `README.md`.

Epic 1 (pipeline and quality gates) is owned by a separate document. Epics here are numbered from 2. They own product fixes and their unit tests, and reference Epic 1 for CI, emulators and test infrastructure.

**Status:** Draft for review. Planning only, no implementation.

**Baseline:** stories were realigned on 2026-10-31 to commit `5d1c615` ("Make backups resumable, lease-guarded, and harder to delete"), per `sprint-change-proposal-2026-10-31.md`. Stories marked "Baseline: implemented" are believed done by that commit. Those with no gap (2.1, 4.2, 5.4) are `review` in `sprint-status.yaml`: a developer confirms each acceptance criterion against code and tests. Those with a listed gap (2.3, 2.4, 2.8, 3.3, 4.1) stay `backlog`, and the work is only that gap.

**Decisions (2026-10-31, Ben):** D1 bucket retention 30 days, soft delete 90 days. D2 long backups extend the existing checkpoint and resume design. D3 restores and large dry runs run as backup-job executions. D4 deleting a job with protected objects tombstones it. D5 Epic 6 owns run-outcome alerts. D6 extra scopes are declared as capabilities in the Epic 9 source catalog. D7 API access is IAP only: IAP is mandatory, the public option and the app token are removed, so there is no token secret. D8 alerts and pipeline notices go to `bgb-admins@aviato.consulting`, the same group that has console access. D9 a restore pauses clean-up (compaction, retention, prune, delete) for its job but not backups. D10 Ben gets the Demo project's `owner_until` (2026-11-30) extended before that date. D11 IAP is never weakened for testing: production code has no auth bypass, flag or test-key setting; tests and local development mock Google's IAP key endpoint inside the test or dev process, UI end-to-end tests mock the API endpoints, and deployed checks go through real IAP.

**Decision IDs:** other documents cite these as "`epics.md` D1" and so on. Epic 1 and Epic 9 have their own D-numbers; inside those files a bare "D3" means that file's decision.

## Requirements Inventory

### Functional Requirements

**Run ownership and lifecycle**

FR1: Only one operation (backup, prune, rebuild or delete) may act on a job at a time, across processes. A "Run now" execution can run its own queued run.
FR2: A running operation renews its ownership. A run whose ownership expires without renewal is marked `timed_out`, and the next execution resumes its work.
FR3: Prune, rebuild and delete-job return 409 while another operation owns the job.
FR4: The scheduled run-due pass handles each job independently. One job's failure does not stop later jobs. An error before a run record exists is recorded as a failed run.
FR5: Each job records its storage prefix and block size at the start of its first run and uses them from then on. Existing jobs are backfilled from where their volumes actually live.
FR6: The end of a run updates only the job's source state and update time. Job edits made during a run are kept.
FR7: Changing the backup bucket is refused while any job has backups.
FR8: Rebuild refuses to clear the index when it finds no fileset volume, and validates every fileset before clearing anything.

**Source error isolation**

FR9: When a whole user or shared drive fails to scan, its previous entries carry forward unchanged, its cursor is not advanced, and a warning names it.
FR10: When reading one object fails, its previous entry is kept. A new object that fails is recorded as pending and retried on the next run. Storage and index write errors still fail the run.
FR11: A run with scan warnings ends as `completed_with_warnings`.
FR12: Google API calls retry 429, 500, 502, 503, 504, connection errors and rate-limit 403s, with backoff and jitter. Other 403s are not retried.
FR13: Contacts keeps the sync token on every page request, and treats an expired token (400 or 410) as a signal to fall back to a full listing.
FR14: Shared drives are listed with domain admin access, which requires an admin email when shared drives are included. Each drive is isolated per FR9, and unreadable drives are reported once, by name.
FR15: Departed users (suspended, or removed from the directory) keep their last backed-up entries and are not scanned. A warning names them. Each job sets how long a departed user's backup is kept after they leave: forever, or a number of years (for example 1, 7 or 10) to match the organisation's compliance policy.
FR16: When "every user" is selected, the directory list is used regardless of any typed users. Existing jobs whose scope this changes are listed in a warning first.

**Streaming and crash safety**

FR17: Drive downloads and exports stream to the engine in full blocks. A retried download resumes from the bytes already read, or restarts the file cleanly when it cannot resume.
FR18: A fileset's file list is written as capped parts, not one object. Rebuild reads multi-part file lists.
FR19: A fileset is marked complete only after all its entries are written. Incomplete filesets are ignored everywhere.

**Identity and paths**

FR20: Drive item ids include the scanning user. Existing backups migrate once, matching old entries by scope and file id, so unchanged files are not downloaded again.
FR21: Incremental and full Drive scans cover the same set of files.
FR22: Path conflicts within a scope are resolved in the engine, deterministically, and a file's own previous path never counts as a conflict.
FR23: Gmail messages moved into Spam or Trash are treated as deleted.
FR24: Contacts backups include addresses, birthdays, URLs, relations, user-defined fields and group memberships. The change triggers one full Contacts scan.

**Deletion under locked retention**

FR25: Every delete respects a minimum object age equal to the bucket retention period (default 30 days, 0 in tests), measured from the time the object was written as recorded in the index (after a rebuild, the object's creation time).
FR26: Compaction skips volumes that are too young, before any rewrite.
FR27: Retention keeps a version that is due for removal but still protected visible and restorable, marked scheduled for removal, until its objects can be deleted; then it is removed.
FR28: Prune skips objects that are too young. Deleting a job with protected objects marks it deleted and hidden; its objects are removed as they come out of protection, then the job record is removed.
FR29: The Cloud Storage volume store reports a missing object as not found, and a retention-hold refusal as deferred.
FR30: Rebuild restores the links between each block volume and its index volume.

**API and UI**

FR31: The API accepts only requests that came through IAP: it verifies IAP's signed header and rejects anything else. There is no app token. Unauthenticated access is possible only in local development, bound to localhost. CORS is off in production and limited to a configured origin list in development.
FR32: The console shows who is signed in, and explains what to do when the IAP session expires or access is denied.
FR33: File downloads work for any file name, including non-Latin characters, with a safe ASCII fallback.
FR34: Job edits accept partial updates (merged onto the current job, then validated). A job's block size cannot change once recorded.
FR35: The file browser pages through large folders, ignores responses for an older search or version, and resets when the selected version has been removed.
FR36: Block counts use a count query. Prefix search includes every character, emoji included. Retention accepts an interval equal to its timeframe.

**Alerting**

FR37: bgb writes one structured log line per run outcome (job id, run id, status, error, warning count).
FR38: Cloud Monitoring alerts fire on failed and completed-with-warnings runs, on backups that are stuck (three executions in a row with no progress), and on enabled, scheduled jobs with no success and no progress in N hours. A single timed-out run that resumes and makes progress does not alert. They use the notification channel from Epic 1 Story 1.12, and Epic 6 is the only owner of run-outcome alerts.
FR39: An email sender interface exists, with an Aviato emailer implementation that is off by default. Settings hold the sender address, recipients and the stale threshold. Each problem sends one alert until it changes or recovers. A failed alert never changes a run's status.

**Restore (D7)**

FR40: Restore writes data back into Workspace (Gmail import, Drive upload) for a user's mailbox, a user's drive, a shared drive, or several users at once.
FR41: The person restoring chooses the target on each restore: another user in the same domain, or the same user in a different domain. Each target domain uses its own delegated credentials and write scopes.
FR42: A dry run reports the counts and paths per target without writing anything.
FR43: Restored items can carry a dated "Restored by bgb" Gmail label or Drive folder. This is an option on each restore, on by default.
FR44: Drive and shared drive sharing permissions are captured in backups and reapplied on restore without notification emails. When restoring into a different domain, permissions for addresses that do not exist there are skipped and reported.
FR45: A restore can create a new shared drive in the target domain.

**Large organisations**

FR46: Google API usage is paced to stay below 80% (configurable) of each applicable quota, using the quotas Google reports for the project where available.
FR47: A first full backup that does not finish in one job execution saves its progress and continues in the next, without downloading again what it already stored.
FR48: Large organisations are onboarded in phases: users are split into cohorts (default 28) and one cohort's first full backup runs per day, while users already onboarded get incremental backups every run.
FR49: Before a job's first backup, bgb estimates how long onboarding will take from user count, data volume and the quota budget, and shows it (for example "about 4 weeks").

### NonFunctional Requirements

NFR1: **No silent data loss.** No failure path may remove previously backed-up data from the latest backup. Failures carry previous state forward and raise a warning.
NFR2: **Crash safety.** A crash at any point leaves a recoverable state, and a partial backup is never used as the base for the next run.
NFR3: **Bounded memory.** No whole-file buffering. The backup job stays within its 2 GiB memory limit, whatever the file size.
NFR4: **Stable deduplication.** Identical content produces identical blocks regardless of network chunking or retries.
NFR5: **Locked-retention compatible.** No code path fails because of a bucket retention hold (30 days by default). Deletes are deferred, not errors.
NFR6: **Secure by default.** IAP is mandatory and the API rejects any request without a valid IAP signed header. The service cannot be made public. Response headers cannot be injected through file names.
NFR7: **Fail-safe assumptions.** Google behaviour that cannot be verified without a test domain (suspended-user impersonation, the People API expired-token code, Run now permissions) is handled so that either outcome is safe.
NFR8: **Large organisations onboard safely.** A first backup of a large domain (for example 10,000 users) finishes across several job executions and days, never goes above 80% of a Google API quota, and its expected duration is known before it starts.
NFR9: **Alert hygiene.** One alert per problem until it changes or recovers. Alerting never affects backup results.
NFR10: **No hard-coded internal identifiers.** Emailer URL and project, and other Aviato infrastructure, are configuration.
NFR11: **Minimal commercial seam.** Only the email sender interface is built for future commercialisation. Nothing else.
NFR12: **Testable in stages.** Each stage is verifiable on its own: pytest, plus `terraform fmt -check` and `terraform validate` for Terraform changes, plus web lint and build for UI changes.

### Additional Requirements

- **Brownfield project.** No starter template. All work modifies the existing repository.
- **Stage order is a dependency.** Run ownership (FR1 to FR8) comes first. The deletion work (FR25 to FR30) must ship before the retention lock is applied.
- **Infrastructure (Terraform):**
  - Grant the runtime service account `roles/run.jobsExecutorWithOverrides` on the backup job, so Run now works.
  - Put IAP in front of the UI service, always (D7). Remove the `allow_unauthenticated` variable and the public invoker binding. Console access goes to `bgb-admins@aviato.consulting`.
  - Bucket: 90-day soft delete and a 30-day retention policy (D1), with `lock_retention` defaulting to false. Versioning stays off. These exist in Terraform since `5d1c615`, as does the optional separate `backup_project_id`.
  - Runtime configuration is owned by Cloud Deploy (Epic 8 DEP-D1): `BGB_OBJECT_RETENTION_DAYS` and the IAP audience (`BGB_IAP_AUDIENCE`) are deploy parameters (Epic 8 Story 8.4). `BGB_CORS_ORIGINS` is for local development only and is not set in production.
  - Cloud Quotas API enabled and quota read granted to the runtime account, for Story 10.2 (proposed for Epic 8 Story 8.1).
  - Firestore point-in-time recovery on.
  - Log-based metrics and alert policies for bgb run outcomes, attached to the Epic 1 notification channel.
  - Emailer access flag off. No VPC egress.
  - Alert emails and pipeline notices go to `bgb-admins@aviato.consulting` (D8), through the channel created by Epic 1 Story 1.12.
- **Retention lock sign-off.** About two weeks after deploy, Ben checks four items (every run succeeded, compaction and retention ran clean, prune skipped young objects, verify found no unexplained objects), then applies `lock_retention=true`. The lock is permanent.
- **Documentation.** Image build and push, the Artifact Registry repository and the README deploy section are owned by Epic 8 (Stories 8.1 and 8.6). Add a lock checklist (`docs/lock-checklist.md`) and the one-off emailer invoker grant.
- **External dependency.** Turning on emailer delivery needs the emailer owners to admit the bgb project (VPC Service Controls perimeter or an ingress change). That is outside this backlog.
- **Environment.** Demo-tier project `aviato-prod-demo-baby-got-back`: one project, no Shared VPC. There is no test Workspace domain; Epic 9 spikes use two temporary users in the Aviato domain. Editor access ends 2026-11-30: Ben gets `owner_until` extended before then (D10), or nobody can apply Terraform. Settle the project tier before the retention lock (Story 4.6).
- **Overlap with Epic 1.** Tests for the Firestore index, IAP header check, scheduler selection, concurrency guard and PATCH guard are written as unit tests in these stories. Emulator, CI and E2E coverage belongs to Epic 1. Alerting shares Epic 1's notification channel.

### UX Design Requirements

No UX design document exists. These come from the fix plan and the roundtable, and each one is specific enough for a story.

UX-DR1: The console header shows the signed-in user. When the IAP session expires or access is denied, a clear page explains how to sign in again and who grants access (`bgb-admins@aviato.consulting`).
UX-DR2: The file browser has "load more" paging, and shows a short message when the selected version no longer exists.
UX-DR3: The restore screen shows the source user, target user and target domain prominently. A target outside the source domain is visibly marked as such.
UX-DR4: Restore requires the target address to be typed exactly before anything is written.
UX-DR5: A dry-run result view shows counts and paths per target before the real restore is offered.
UX-DR6: Job views show `completed_with_warnings` and `timed_out` clearly, with the named users or drives behind each warning.

### FR Coverage Map

FR1: Epic 2 - One operation per job across processes
FR2: Epic 2 - Ownership renewal and timed-out runs
FR3: Epic 2 - Maintenance returns 409 during a run
FR4: Epic 2 - Scheduler handles each job independently
FR5: Epic 2 - Per-job prefix and block size, with backfill
FR6: Epic 2 - End of run keeps job edits
FR7: Epic 2 - Bucket change refused while backups exist
FR8: Epic 2 - Safe rebuild
FR9: Epic 3 - Failed user or drive carries forward
FR10: Epic 3 - Failed object keeps entry, pending retry
FR11: Epic 3 - Completed with warnings
FR12: Epic 3 - Retry policy
FR13: Epic 3 - Contacts sync token and expiry
FR14: Epic 3 - Shared drives with admin access
FR15: Epic 3 - Departed users kept for a configurable period
FR16: Epic 3 - "Every user" uses the directory
FR17: Epic 2 - Full-block streaming and retries
FR18: Epic 2 - Multi-part file lists
FR19: Epic 2 - Fileset completeness flag
FR20: Epic 3 - Drive ids per user, migration without re-download
FR21: Epic 3 - Incremental and full Drive scans match
FR22: Epic 3 - Deterministic path conflicts
FR23: Epic 3 - Gmail Spam and Trash as deletes
FR24: Epic 3 - More Contacts fields
FR25: Epic 4 - Minimum object age on every delete
FR26: Epic 4 - Compaction skips young volumes
FR27: Epic 4 - Pending fileset deletes
FR28: Epic 4 - Prune and job delete respect age
FR29: Epic 4 - Storage errors mapped
FR30: Epic 2 - Rebuild restores volume links
FR31: Epic 5 - IAP-only API access, CORS
FR32: Epic 5 - Signed-in user and sign-in errors
FR33: Epic 5 - Downloads for any file name
FR34: Epic 5 - Partial job edits
FR35: Epic 5 - File browser paging and stale responses
FR36: Epic 5 - Count query, prefix search, retention interval
FR37: Epic 6 - Structured run outcome log
FR38: Epic 6 - Cloud Monitoring alerts
FR39: Epic 6 - Emailer sender (off), alert dedup
FR40: Epic 7 - Write back into Workspace
FR41: Epic 7 - Target chosen per restore
FR42: Epic 7 - Dry run
FR43: Epic 7 - Optional restored-item label
FR44: Epic 3 (capture) and Epic 7 (restore) - Sharing permissions
FR45: Epic 7 - Create a shared drive on restore
FR46: Epic 10 - Quota budget
FR47: Epic 10 - Long backups resume without false alarms
FR48: Epic 10 - Phased onboarding
FR49: Epic 10 - Onboarding estimate

## Epic List

Epic 1 (pipeline and quality gates) is in `epics/epic-1-pipeline-quality-gates.md`. Order: 2, 3, 4, 5, 6, 7, 10. Epics 5 and 7 can run alongside 3 and 4. Epic 10 needs Epics 2 and 3 and must ship before any large organisation is onboarded. NFR8 (large organisations) is covered by Epic 10. Numbers 8 and 9 belong to epics in `epics/`.

Epics 2, 3 and 4 all change `src/bgb/engine.py`, in different areas: run lifecycle (2), scan merging (3), retention and compaction (4). They stay separate on purpose: Epic 4 is a risk boundary that must be proven before the irreversible retention lock, and merging 2 and 3 would make one epic of 20 stories. Related epics in `epics/`: Epic 1 (quality gates), Epic 8 (deployment pipeline, owns image and Cloud Run runtime configuration), Epic 9 (Keep, Chat, Calendar, Tasks; follows Epic 3's warning rules).

### Epic 2: Backup runs that never collide or corrupt
An admin can run, schedule, prune and rebuild without operations colliding. A crash or timeout never leaves a broken backup, each job keeps its own storage settings, and the index can always be rebuilt from storage.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8, FR17, FR18, FR19, FR30

### Epic 3: Every user, mailbox and drive is covered, and failures are named
Every user, mailbox, My Drive and shared drive is backed up correctly. A failure on one person or drive is named in a warning, never silently drops their history, and never stops everyone else's backup.
**FRs covered:** FR9, FR10, FR11, FR12, FR13, FR14, FR15, FR16, FR20, FR21, FR22, FR23, FR24, FR44 (capture)

### Epic 4: Backups that can't be deleted by mistake or by attack
Nothing can be deleted for 30 days and deleted data stays recoverable for 90, and the lock becomes permanent after sign-off. bgb's own clean-up works within that rule instead of failing against it.
**FRs covered:** FR25, FR26, FR27, FR28, FR29

### Epic 5: A secure admin console that works for every file
Admins sign in through IAP, which is mandatory (D7), the API rejects anything that did not come through IAP, "Run now" works, and admins can browse any folder and download any file, whatever its name.
**FRs covered:** FR31, FR32, FR33, FR34, FR35, FR36

### Epic 6: Know when a backup fails, once per problem
An admin is told when a backup fails, times out, finishes with warnings or goes stale, once per problem, and alerting never affects a backup.
**FRs covered:** FR37, FR38, FR39

### Epic 7: Restore into Workspace, safely
An admin can restore a mailbox, drive, shared drive or several users back into Workspace, choosing the target user or domain each time, with a dry run first and a typed confirmation of the target.
**FRs covered:** FR40, FR41, FR42, FR43, FR44 (restore), FR45

### Epic 10: Large organisations onboard without hitting Google limits
An admin can take on a very large organisation (for example 10,000 users) knowing in advance how long the first backup will take. Users are onboarded in daily phases, Google API use stays below 80% of quota, and long first backups continue across job runs.
**FRs covered:** FR46, FR47, FR48, FR49

## Epic 2: Backup runs that never collide or corrupt

An admin can run, schedule, prune and rebuild without collisions. A crash or timeout never leaves a broken backup, each job keeps its own storage settings, and the index can always be rebuilt from storage.

### Story 2.1: One operation per job at a time

**Covers:** FR1, FR2

**Baseline: implemented** (`Engine.leased`, `heartbeat`; `test_second_execution_cannot_run_while_the_lease_is_held`, `test_expired_lease_is_taken_over`). No gap expected.

As a backup admin,
I want each job to be owned by one run at a time, across every bgb process,
So that a scheduled run and a manual "Run now" never back up the same job at once.

**Acceptance Criteria:**

**Given** a job with no lease
**When** an operation that changes stored data starts (backup, retention, compaction, prune, rebuild, delete)
**Then** it takes the job's lease in the index, with the Cloud Run execution name as holder and a 30 minute TTL
**And** another execution trying to take it gets a conflict, and a queued run that loses is marked failed with the reason

**Given** a Cloud Run retry of the same execution
**When** it starts
**Then** it can take over its own lease

**Given** a run in progress
**When** 60 seconds have passed since the last renewal
**Then** it renews the lease, and stops writing if another execution has taken it
**And** the lease is released when the operation ends, whether it succeeded or failed

**And** tests cover a held lease blocking a second execution and an expired lease being taken over.

### Story 2.2: Runs that die are marked timed out

**Covers:** FR2

**Baseline:** `_close_abandoned` already closes these runs but marks them `failed` ("abandoned"). This story changes the status and adds the link.

As a backup admin,
I want a run whose process was killed to show as timed out,
So that the job is not blocked and I can see what happened.

**Acceptance Criteria:**

**Given** a run left `running` (or stale `queued`) by an execution that was killed or timed out
**When** the next execution takes the job's lease
**Then** that run is marked `timed_out` (not `failed`), with a finish time and a reason saying its progress was kept

**Given** a `timed_out` run whose work the next execution resumes from the checkpoint
**When** the job's history is shown
**Then** the resuming run links to the `timed_out` run, so it reads as one backup

**And** the unused `busy()` function is removed.

### Story 2.3: Maintenance waits for the run

**Covers:** FR3

**Baseline: implemented, one gap.** Maintenance runs as a backup-job execution that takes the lease, and the CLI takes it too. Gap: before starting a maintenance execution, the API checks `lease_holder` and returns 409 with the holder instead of starting an execution that will fail.

As a backup admin,
I want prune, rebuild and delete to refuse while a run is active,
So that maintenance can never delete files a backup just wrote or clear its index.

**Acceptance Criteria:**

**Given** a job owned by an active run
**When** I call prune, rebuild or delete-job
**Then** the API returns 409 with the active run's id

**Given** no active run
**When** I call one of those operations
**Then** it claims the job's lease for its duration
**And** a backup that tries to start meanwhile gets a conflict

**Given** the CLI commands `bgb run`, `bgb run-due` and `bgb rebuild`
**When** they act on a job
**Then** they claim the same lease, and report a conflict instead of proceeding when another operation owns the job

### Story 2.4: One failing job never stops the schedule

**Covers:** FR4

**Baseline: implemented, one gap.** `run_due` skips leased jobs and catches per-job errors. Gap: an error before a run record exists is recorded as a `failed` run, and the CLI lists failed jobs and exits non-zero.

As a backup admin,
I want each scheduled job handled on its own,
So that one broken job does not silently stop every other backup.

**Acceptance Criteria:**

**Given** three due jobs where the first raises an error
**When** `run-due` runs
**Then** the second and third jobs still run
**And** the CLI exits non-zero and lists the failed job

**Given** a job that fails before a run record exists (missing job, invalid config)
**When** `run-due` handles it
**Then** a `failed` run is recorded with the error, so it shows in the UI

**And** unit tests cover enabled, disabled, unscheduled, busy and due jobs, and a failing job in the middle of the list.

### Story 2.5: Each job keeps its own storage settings

**Covers:** FR5, FR6, FR7

**Note:** the bucket may live in a separate project (`backup_project_id`); the bucket-change guard covers that too.

As a backup admin,
I want each job to keep the storage prefix and block size it started with,
So that changing global settings never hides old backups or breaks deduplication.

**Acceptance Criteria:**

**Given** a new job's first run
**When** the run starts, before any volume is written
**Then** the job records `gcs_prefix` and `block_size`, and the engine uses the job's values from then on

**Given** existing jobs with backups and no recorded values
**When** the migration runs
**Then** each job's prefix is taken from where its volumes actually live (index volume names), and its block size from the job or the global value it used

**Given** a run is in progress
**When** an admin edits the job
**Then** the run's final update writes only `source_state` and `updated_at`, and the edit is kept

**Given** any job has backups
**When** an admin changes the bucket in Settings
**Then** the change is refused with a message explaining why

### Story 2.6: Rebuild never wipes the index by mistake

**Covers:** FR8, FR30

**Addition:** rebuild sets each volume's `created_at` from the Cloud Storage object's creation time, not "now", so retention timing survives a rebuild (Story 4.1).

As a backup admin,
I want rebuild to check what it found before clearing anything, and to rebuild completely,
So that a wrong prefix or a damaged object cannot leave me with an empty or broken index.

**Acceptance Criteria:**

**Given** the listing under the job's prefix contains no fileset volume
**When** I run rebuild
**Then** it refuses and the index is unchanged

**Given** any fileset in the listing fails validation
**When** I run rebuild
**Then** it refuses before clearing the index and names the bad object

**Given** a valid listing
**When** rebuild completes
**Then** each block volume and its index volume are linked to each other
**And** a later compaction that deletes a block volume also deletes its index volume

### Story 2.7: A partial backup is never used as the base

**Covers:** FR19

**Addition:** checkpoint entries (`list_checkpoint`) are never listed as a version, and are cleared only after the fileset is marked complete.

As a backup admin,
I want a backup version to count only once it is fully written,
So that a crash during writing cannot make the next run drop files.

**Acceptance Criteria:**

**Given** a fileset being written
**When** the write starts
**Then** the summary is saved with `complete=false`, then all entries, then `complete=true`

**Given** a fileset with `complete=false`
**When** the next run chooses its base, or the UI, retention, compaction or verify lists filesets
**Then** the incomplete fileset is ignored

**Given** an incomplete fileset left by a crash
**When** a later run or delete cleans up
**Then** its entries and its file-list object are removed

**And** deleting a fileset sets `complete=false` first.

### Story 2.8: Large Drive files stream in full blocks

**Covers:** FR17

**Baseline: implemented, one gap.** 8 MiB chunked streaming and full-block reads exist (`test_media_stream_returns_full_blocks_and_holds_one_chunk`). Gap: a download that fails mid-file resumes from the bytes already read, or an export restarts the file cleanly with a fresh hasher.

As a backup admin,
I want Drive files streamed to storage block by block,
So that a multi-gigabyte file cannot crash the backup job and deduplication keeps working.

**Acceptance Criteria:**

**Given** a Drive file larger than the job's memory limit
**When** it is backed up
**Then** it is read as a stream and never held in memory whole

**Given** a stream that returns short reads
**When** the engine reads a block
**Then** the reader fills each block to the full block size except the last
**And** the same content produces the same block hashes regardless of read sizes (tested with randomised read sizes)

**Given** a download fails partway through
**When** it is retried
**Then** downloads resume from the bytes already read using a Range request, and exports (which cannot resume) restart the file with a fresh hasher and drop that file's pending blocks
**And** the restored file matches its content hash

### Story 2.9: Large domains get a file list in parts

**Covers:** FR18

As a backup admin,
I want a backup version's file list written in capped parts,
So that large domains do not hit the volume cap and fail every run.

**Acceptance Criteria:**

**Given** a fileset whose file list would exceed the part cap
**When** it is written
**Then** it is stored as several numbered parts, each under the cap, built without holding the whole list in memory

**Given** a multi-part file list
**When** rebuild reads it
**Then** the fileset is rebuilt completely

**Given** a single-part file list from before this change
**When** rebuild reads it
**Then** it is still read correctly

## Epic 3: Every user, mailbox and drive is covered, and failures are named

Every user, mailbox, My Drive and shared drive is backed up correctly. A failure on one person or drive is named, never silently drops their history, and never stops everyone else's backup.

### Story 3.1: A failed user or drive keeps their backup

**Covers:** FR9, FR11

As a backup admin,
I want a person or shared drive that fails to scan to keep their last backup,
So that one bad account cannot erase anyone's history.

**Acceptance Criteria:**

**Given** one user's scan raises a source error (for example getProfile 400 for an unlicensed account)
**When** the run builds the new backup version
**Then** that user's previous entries carry forward unchanged, their cursor is not advanced, and none of their entries is counted as deleted
**And** a warning names the user and source

**Given** a run that finished with one or more scan warnings
**When** it completes
**Then** its status is `completed_with_warnings` and the warnings are listed on the run

**And** a test proves a user whose scan failed still has every file in the next fileset.

### Story 3.2: A failed item keeps its last copy and is retried

**Covers:** FR10

As a backup admin,
I want one unreadable message or file to be skipped safely and tried again,
So that a single bad item neither fails the run nor goes missing for good.

**Acceptance Criteria:**

**Given** reading one object fails with a source error (`HttpError`, `RefreshError`, not-found, unsafe path)
**When** the run continues
**Then** the object's previous entry is kept if it has one, and a warning names it

**Given** a new object that fails and has no previous entry
**When** the run finishes
**Then** its id is stored in `source_state` as pending
**And** the next run retries it even though the source cursor moved past it

**Given** a Cloud Storage or Firestore write error during the run
**When** it occurs
**Then** the run still fails as before

### Story 3.3: Throttling and network blips do not fail backups

**Covers:** FR12

**Baseline: implemented, one gap.** 429, 5xx and rate-limit 403s (including `quotaExceeded`) are retried, honouring `Retry-After`. Gap: connection errors and timeouts are retried too, with jitter.

As a backup admin,
I want temporary Google errors retried,
So that routine rate limits do not fail a whole domain's backup.

**Acceptance Criteria:**

**Given** a Google API call returns 429, 500, 502, 503, 504 or a connection error
**When** it is retried
**Then** it backs off with jitter up to the attempt limit

**Given** a 403 whose reason is `rateLimitExceeded` or `userRateLimitExceeded`
**When** it is retried
**Then** it is treated as retryable

**Given** a 403 with any other reason (for example `exportSizeLimitExceeded`) or an unreadable reason
**When** it occurs
**Then** it is not retried and is handled by Story 3.2

### Story 3.4: Contacts sync handles big address books and old tokens

**Covers:** FR13

As a backup admin,
I want Contacts to sync correctly across many pages and after long gaps,
So that a large address book or a job paused for a week does not break Contacts backups.

**Acceptance Criteria:**

**Given** an incremental Contacts sync spanning several pages
**When** each page is requested
**Then** every request carries the same sync token

**Given** the People API reports an expired sync token as 400 `EXPIRED_SYNC_TOKEN` or 410
**When** the scan handles it
**Then** it falls back to a full listing and adds a warning

### Story 3.5: Every shared drive is listed, and unreadable ones are named

**Covers:** FR14

As a backup admin,
I want bgb to find every shared drive in the domain and tell me which it cannot read,
So that no shared drive is silently left out.

**Acceptance Criteria:**

**Given** a job that includes shared drives and no admin email in Settings
**When** the job is saved or run
**Then** it is rejected with a message asking for the admin email

**Given** an admin email is set
**When** shared drives are listed
**Then** the listing uses domain admin access and returns drives the admin is not a member of

**Given** a listed drive returns 403 or 404 when its files are read
**When** the run continues
**Then** that drive's previous entries carry forward (Story 3.1) and one warning names the drive

### Story 3.6: Departed users keep their backup for as long as policy requires

**Covers:** FR15

A departed user is someone whose account has been suspended or removed from the directory, usually because they left the organisation. bgb can no longer back up anything new for them.

As a backup admin,
I want a departed user's last backup kept for the period our compliance policy requires,
So that their mail and files are there when a manager or legal needs them, and removed when the policy says so.

**Acceptance Criteria:**

**Given** "every user" is selected
**When** the directory is read
**Then** suspended users are included

**Given** a user who is suspended, or who was in the previous backup but is no longer in the directory
**When** the run builds the new version
**Then** their last entries are kept unchanged, they are not scanned, and a warning names them as departed
**And** the date bgb first saw them as departed is recorded

**Given** a job's departed-user retention setting
**When** an admin sets it
**Then** they can choose "keep forever" (the default) or a number of years after departure (for example 1, 7 or 10, or any whole number)

**Given** a departed user whose retention period has not ended
**When** normal version retention runs
**Then** it never removes the newest copy of that user's data, whatever the version policy says

**Given** a departed user whose retention period has ended
**When** the next run builds a new version
**Then** their entries are no longer carried forward, so normal retention removes their data as older versions age out
**And** the job view lists departed users with their departure date and the date their data becomes eligible for removal, at least 30 days in advance
**And** each removal is recorded in the run (user, departure date, policy applied) as an audit trail

**Given** a departed user who returns (account restored)
**When** the next run sees them active again
**Then** they are scanned normally and the departure record is cleared

**Given** a departed user
**When** the job view or the audit record shows them
**Then** it shows both the date their data becomes eligible for removal and the expected final deletion date (eligible date, plus the version retention needed to age it out, plus the bucket retention period, plus soft delete), and explains that data is held until then

### Story 3.7: "Every user" means every user

**Covers:** FR16

As a backup admin,
I want the "every user" option to back up the whole directory,
So that names typed earlier do not quietly limit the backup.

**Acceptance Criteria:**

**Given** a job with "every user" selected and typed users saved
**When** it runs
**Then** the directory list is used and typed users are ignored

**Given** the job form with "every user" ticked
**When** it is submitted
**Then** it sends an empty users list

**Given** existing jobs saved with both
**When** this change is deployed
**Then** a one-off report lists those jobs and the job view shows the scope change

### Story 3.8: Drive items are tagged per user, with no re-download

**Covers:** FR20, FR21

As a backup admin,
I want each person's Drive items identified per person,
So that files shared between colleagues are kept correctly in each person's backup.

**Acceptance Criteria:**

**Given** a Drive item seen by a user
**When** its id is built
**Then** it includes the scanning user, and one helper builds every Drive id, deleted ids included

**Given** existing backups with old-style ids
**When** the first run after the change happens (triggered once by a schema version in `source_state`)
**Then** old entries are matched by scope and file id, so unchanged revisions are reused and nothing is downloaded again
**And** the next fileset has no duplicate entries

**Given** the same user's Drive
**When** an incremental scan and a full scan run
**Then** both cover the same set of files, shared-with-me included

### Story 3.9: Stable, unique file paths

**Covers:** FR22

As a backup admin,
I want every file in a backup to have one stable, unique path,
So that restoring by path always finds the right file.

**Acceptance Criteria:**

**Given** two files resolving to the same path in a scope
**When** the engine merges retained and changed entries
**Then** the clash is resolved with a deterministic suffix (sorted by file id), looping until unique

**Given** a file that was edited but not renamed
**When** paths are resolved
**Then** its own previous path does not count as a clash and its path is unchanged

**Given** the same set of files
**When** full and incremental scans run
**Then** they produce the same paths

### Story 3.10: Spam and trash match between scans

**Covers:** FR23

As a backup admin,
I want messages moved to Spam or Trash handled the same way in every scan,
So that the backup does not depend on which kind of scan ran.

**Acceptance Criteria:**

**Given** an incremental Gmail scan
**When** a message is added to or moved into Spam or Trash
**Then** it is treated as deleted, the same as a full scan

### Story 3.11: Contacts backups keep the whole contact

**Covers:** FR24

As a backup admin,
I want Contacts backed up with all their useful fields,
So that a restored contact is complete.

**Acceptance Criteria:**

**Given** a Contacts scan
**When** people are requested
**Then** fields include names, emails, phones, organizations, notes, addresses, birthdays, URLs, relations, user-defined fields and memberships

**Given** existing Contacts backups
**When** the first run after the change happens
**Then** a schema version bump (the mechanism from Story 3.8) forces one full Contacts scan

### Story 3.12: Sharing permissions are backed up

**Covers:** FR44 (capture)

**Note:** permission reads go through the quota pacing in Story 10.2.

As a backup admin,
I want who-can-access-what saved with each Drive file and shared drive,
So that a restore can put sharing back the way it was.

**Acceptance Criteria:**

**Given** a Drive file or folder in My Drive or a shared drive
**When** it is backed up
**Then** its permissions (type, role, email or domain, and whether it is inherited) are stored with the entry's metadata

**Given** a shared drive
**When** it is backed up
**Then** its members and their roles are stored with the drive's scope

**Given** a permission change with no content change
**When** the next run happens
**Then** the new permissions are recorded without downloading the file again

**Given** existing backups taken before this change
**When** the first run after it happens
**Then** a schema version bump (Story 3.8) refreshes permissions for every item, without re-downloading content

## Epic 4: Backups that can't be deleted by mistake or by attack

Nothing can be deleted for 30 days and deleted data stays recoverable for 90, and the lock becomes permanent after sign-off. bgb's own clean-up works within that rule instead of failing against it. Order is deliberate: code that respects the rule (4.1 to 4.4), then unlocked protection (4.5), then the permanent lock (4.6).

### Story 4.1: Deletes respect a minimum object age

**Covers:** FR25, FR29

**Baseline: implemented, one gap** (`min_object_age`, `Retained`). Gap: the rebuild case, delivered with Story 2.6.

As a backup admin,
I want every delete bgb makes to check the object's real age first,
So that bgb never fights the bucket's retention rule.

**Acceptance Criteria:**

**Given** the bucket retention period (`BGB_OBJECT_RETENTION_DAYS`, default 30 days, 0 in tests)
**When** bgb considers deleting any object
**Then** it uses that period as the minimum age, measured from the time the object was written as recorded in the index

**Given** a rebuilt index
**When** age is measured
**Then** it uses the object's creation time restored by rebuild (Story 2.6), not the rebuild time

**Given** Cloud Storage refuses a delete because of retention or a hold
**When** the volume store handles it
**Then** it raises `Retained`, and callers defer the delete instead of failing

**Given** an object is missing
**When** the volume store reads it
**Then** it raises `FileNotFoundError`, so verify reports it instead of crashing

### Story 4.2: Compaction leaves young volumes alone

**Covers:** FR26

**Baseline: implemented** (`test_retention_defers_deletes_until_objects_are_old_enough`). Confirm the repeated-runs criterion with a 30-day minimum age.

As a backup admin,
I want compaction to skip volumes that are still protected,
So that it does not rewrite the same data every run and grow storage.

**Acceptance Criteria:**

**Given** a block volume younger than the minimum age
**When** compaction considers it
**Then** it is skipped before any rewrite and its blocks stay where they are

**Given** a volume old enough and over the waste threshold
**When** compaction runs
**Then** it rewrites and deletes as before
**And** a test with a 30-day minimum age shows no rewrite of young volumes across repeated runs

### Story 4.3: Retention finishes young deletes later

**Covers:** FR27

**Baseline: differs from the code.** Today retention removes the version from the index at once and only keeps its objects, marked `expired`, until `sweep_expired` deletes them. This story keeps the version row and entries, marked `pending_delete`, until the sweep deletes its file list; block volumes still referenced by a pending version are not compacted.

As a backup admin,
I want old backup versions that are still protected to be removed once they can be,
So that retention never leaves the index and storage disagreeing.

**Acceptance Criteria:**

**Given** a backup version due for removal whose file list is younger than the minimum age
**When** retention runs
**Then** the version is marked `pending_delete`, and its index row and object are both kept

**Given** a `pending_delete` version whose object is now old enough
**When** a later run applies retention
**Then** the object and the index row are both removed

**Given** a `pending_delete` version
**When** the UI or restore lists versions
**Then** it is shown, marked "Scheduled for removal" with the date it will be removed, and can still be restored until then

### Story 4.4: Prune and job delete respect the protection window

**Covers:** FR28

**Baseline:** prune already skips retained objects. Job delete today removes the index and leaves retained objects that nothing ever removes; this story replaces that with a tombstone (D4).

As a backup admin,
I want prune and job delete to work within the protection window,
So that they never fail halfway or leave a job half deleted.

**Acceptance Criteria:**

**Given** orphaned objects younger than the minimum age
**When** I run prune
**Then** they are skipped and listed as "too young", and older orphans are removed

**Given** a job with any object still under retention
**When** I delete the job
**Then** the job is marked `deleted`, hidden from lists and schedules, and the response gives the expected date its data will be gone
**And** objects are deleted by the sweep as they come out of retention, and the job record is removed once the last object is gone

**Given** a job with no protected objects
**When** I delete it
**Then** its objects and record are removed at once

### Story 4.5: The bucket and index are protected (unlocked)

**Covers:** Additional requirement: bucket soft delete, retention policy (unlocked), Firestore PITR

**Baseline:** soft delete, retention policy and `lock_retention` exist in Terraform. Remaining: Firestore PITR, the separate-project check and the deploy parameter.

As a backup admin,
I want deleted backups recoverable for 90 days and nothing deletable before it is 30 days old,
So that stolen credentials or a bad script cannot wipe the backups.

**Acceptance Criteria:**

**Given** the Terraform for the backup bucket
**When** it is applied
**Then** soft delete is 90 days and the retention policy is 30 days (D1), `lock_retention` defaults to `false`, and versioning stays off

**Given** the Firestore database
**When** Terraform is applied
**Then** point-in-time recovery is on

**Given** a separate backup project (`backup_project_id`)
**When** Terraform is applied
**Then** the same protections apply to the bucket there

**Given** the deployed service
**When** it runs
**Then** `BGB_OBJECT_RETENTION_DAYS` matches the bucket's retention period, passed as a Cloud Deploy parameter (Epic 8 Story 8.4)

**Given** the deployed service with these settings
**When** a full backup, compaction, retention, prune and verify cycle runs
**Then** none of them fails because of the retention policy

### Story 4.6: Lock the protection after sign-off

**Covers:** Additional requirement: retention lock sign-off

As Ben, the owner of the bgb deployment,
I want a clear checklist and a single switch to make the protection permanent,
So that the lock is applied deliberately once the code is proven.

**Acceptance Criteria:**

**Given** `docs/lock-checklist.md`
**When** it is read
**Then** it lists the four checks (successful runs for at least one full retention period, so compaction and the sweep are seen deleting real objects; compaction and retention without errors; prune skipped young objects; verify found no unexplained objects)
**And** it states plainly that the lock is permanent and cannot be undone

**Given** all four checks pass and Ben signs off
**When** Terraform is applied with `lock_retention=true`
**Then** the bucket's retention policy is locked
**And** the date and approver are recorded in the checklist

## Epic 5: A secure admin console that works for every file

Admins sign in through IAP, which is mandatory (D7), the API rejects anything that did not come through IAP, "Run now" works, and admins can browse any folder and download any file. Builds app behaviour; Epic 1 Story 1.7 enforces it in the pipeline.

### Story 5.1: The API accepts only requests that came through IAP

**Covers:** FR31

**Dependency:** the IAP audience (`BGB_IAP_AUDIENCE`) is a Cloud Deploy parameter (Epic 8 Story 8.4).

As a backup admin,
I want the API to trust only requests that passed Google sign-in,
So that nobody can read backed-up mail or delete jobs by reaching the service directly.

**Acceptance Criteria:**

**Given** a request to `/api/*` other than `/api/health`
**When** it has no IAP signed header (`X-Goog-IAP-JWT-Assertion`), or the header fails signature, expiry or audience checks
**Then** it gets 401, and the reason is logged without the header's contents

**Given** a request with a valid IAP signed header
**When** it reaches the API
**Then** it is served, and the signed-in user's email is available to the request for display and audit

**Given** the existing app token gate (`BGB_API_TOKEN`) and the UI code that stores and sends a token
**When** this story is done
**Then** both are removed (D7)

**Given** the production app and its container image
**When** it starts, whatever its configuration
**Then** there is no setting, flag or code path that skips the IAP check or trusts a key other than Google's IAP keys (D11)

**Given** unit and API tests that need an authenticated request
**When** they run
**Then** they patch the verifier's Google key fetch inside the test process and sign headers with a key the test generates, so the real verification code runs unchanged

**Given** local development
**When** a developer runs the console from source
**Then** it starts through a development-only entry point outside the shipped package (for example `tests/dev_server.py`) that applies the same in-process patch; the container image does not include it

**Given** production
**When** the UI calls the API from the same origin
**Then** CORS is not enabled
**And** in development only, origins listed in `BGB_CORS_ORIGINS` are allowed

**And** tests cover a missing header, an invalid header, a wrong audience, an expired header, a valid header, and `/api/health` open.
**And** a test fails the build if the shipped package contains the development entry point or any test key material.

### Story 5.2: Admins sign in through IAP

**Covers:** Additional requirement: IAP

As a backup admin,
I want the console behind Google sign-in, always,
So that only approved Aviato staff can open it.

**Acceptance Criteria:**

**Given** the Terraform for the UI service
**When** it is applied
**Then** IAP fronts the service, the IAP service agent can invoke it, and access is granted to `bgb-admins@aviato.consulting` (a Terraform variable with that default)

**Given** the Terraform variables
**When** they are read
**Then** there is no `allow_unauthenticated` option and no `allUsers` invoker binding; the service cannot be made public (D7)

**Given** a person not in the access group
**When** they open the console
**Then** IAP refuses them before the app is reached

**Given** the Cloud Deploy post-deploy checks (Epic 1 Story 1.10)
**When** Terraform is applied
**Then** a dedicated smoke-test service account has IAP access to the service and no other roles on it, and can mint an ID token for the IAP audience

### Story 5.3: The console shows who is signed in

**Covers:** FR32, UX-DR1

As a backup admin,
I want to see which account I am signed in with, and a clear message when my session expires or I lack access,
So that I am never left with a broken page.

**Acceptance Criteria:**

**Given** a signed-in user
**When** any console page loads
**Then** the header shows their email, taken from the IAP identity

**Given** the IAP session has expired
**When** the UI calls the API and gets 401
**Then** the page explains the session expired and offers to reload to sign in again

**Given** a user IAP denies
**When** they reach the console
**Then** they see who grants access (`bgb-admins@aviato.consulting`)

**And** the Settings page no longer has a token field.

### Story 5.4: "Run now" works in the cloud

**Covers:** Additional requirement: Run now permission

**Baseline: implemented, one check.** `roles/run.jobsExecutorWithOverrides` is granted to the UI service account, which starts the execution; that is correct. Check: in a deployed environment, "Run now" moves a run from queued to running.

As a backup admin,
I want "Run now" to start a backup on Cloud Run,
So that I do not have to wait for the schedule.

**Acceptance Criteria:**

**Given** the Terraform for the backup job
**When** it is applied
**Then** the UI service account, which starts executions, has `roles/run.jobsExecutorWithOverrides` on the backup job

**Given** a deployed service
**When** I press "Run now"
**Then** a Cloud Run execution starts for that job and run id, and the run moves from queued to running

### Story 5.5: Any file can be downloaded

**Covers:** FR33

As a backup admin,
I want to download a backed-up file whatever its name,
So that files named in other languages or with emoji restore like any other.

**Acceptance Criteria:**

**Given** a file whose name contains non-Latin characters or emoji
**When** I download it
**Then** the response uses `filename*=UTF-8''` and the browser saves it under the original name, with no server error

**Given** a name with control characters, quotes or backslashes
**When** I download it
**Then** the plain fallback filename has them replaced, and no extra header can be injected

**Given** a name with nothing printable in ASCII
**When** I download it
**Then** the fallback name is `download`

### Story 5.6: Jobs can be edited a field at a time

**Covers:** FR34

As a backup admin,
I want to change one setting on a job without resending everything,
So that an edit never resets settings I did not touch.

**Acceptance Criteria:**

**Given** a PATCH with only some fields
**When** it is applied
**Then** only those fields change, and the merged job is validated as a whole

**Given** a job whose block size has been recorded (Story 2.5)
**When** a PATCH sends a different block size or `null`
**Then** it is rejected with 400

**And** tests cover a partial update and the block size guard.

### Story 5.7: The file browser handles big folders

**Covers:** FR35, FR36, UX-DR2

As a backup admin,
I want to page through large folders and always see the right results,
So that I can find any file to restore.

**Acceptance Criteria:**

**Given** a folder with more files than one page
**When** I reach the end of the list
**Then** "Load more" fetches the next page using the cursor

**Given** I change the search prefix or version while a request is in flight
**When** the older response arrives
**Then** it is ignored

**Given** the selected version was removed by retention or rebuild
**When** the job view reloads
**Then** it switches to the newest version, or shows "no versions yet", with a short message

**Given** paths containing emoji or other characters beyond the basic range
**When** I search by prefix
**Then** they are included in the results

### Story 5.8: Run results say what happened

**Order:** build after Stories 2.2 and 3.1, which add the `timed_out` and `completed_with_warnings` statuses.

**Covers:** UX-DR6

As a backup admin,
I want each run to show clearly whether it completed, completed with warnings, failed or timed out,
So that I know what to check.

**Acceptance Criteria:**

**Given** a run with status `completed_with_warnings`
**When** I open the job
**Then** the status is visibly different from `completed` and the warnings list the named users, drives or items

**Given** a run with status `timed_out`
**When** I open the job
**Then** it shows as timed out with when it stopped

### Story 5.9: Small correctness fixes

**Covers:** FR36

As a backup admin,
I want the dashboard and retention settings to behave correctly,
So that large jobs load quickly and valid policies are accepted.

**Acceptance Criteria:**

**Given** a job with millions of blocks
**When** the dashboard loads
**Then** block counts come from a count query, not reading every block

**Given** a retention policy whose interval equals its timeframe (for example `1D:1D`)
**When** it is saved
**Then** it is accepted, and an interval larger than its timeframe is still rejected

## Epic 6: Know when a backup fails, once per problem

An admin is told when a backup fails, times out, finishes with warnings or goes stale, once per problem, and alerting never affects a backup. Depends on Epic 1 Story 1.12's email notification channel and on run statuses from Epics 2 and 3. Epic 6 owns run-outcome alerts; Epic 1 Story 1.11 does not duplicate them (D5).

### Story 6.1: Every run logs its outcome

**Covers:** FR37

As a backup admin,
I want each run to write one structured log entry when it ends,
So that monitoring can rely on it.

**Acceptance Criteria:**

**Given** a run ends as `completed`, `completed_with_warnings`, `failed` or `timed_out` (Story 2.2), or onboarding changes state (Epic 10)
**When** its final status is saved
**Then** one structured log entry is written with job id, job name, run id, status, error (if any), warning count, and progress (files and bytes newly stored by this execution), under a fixed event name

**Given** the progress rule used by every alert in this epic and by Story 10.1
**When** an execution ends as `timed_out` or `failed` having stored no new files or bytes
**Then** it counts as an execution with no progress
**And** when three executions of the same backup in a row make no progress, one `backup_stuck` event is logged; the count resets when an execution makes progress or the backup completes

**Given** a `run-due` pass
**When** it finishes
**Then** it writes one heartbeat log entry with the number of jobs started, skipped and failed

### Story 6.2: Alerts for failed, stuck and warning runs

**Covers:** FR38

As a backup admin,
I want an email when a backup fails, gets stuck or finishes with warnings, but not every time a long backup times out and resumes,
So that I find out the same day, not when I need a restore.

**Acceptance Criteria:**

**Given** the Terraform for monitoring
**When** it is applied
**Then** log-based metrics and alert policies exist for `failed` and `completed_with_warnings` outcomes and for `backup_stuck` events (Story 6.1), grouped by job
**And** there is no alert on an individual `timed_out` outcome, because a long backup times out and resumes as normal (Stories 2.2 and 10.1)
**And** they notify the email channel created by Epic 1 Story 1.12, referenced by variable rather than created again
**And** this story is the only owner of run-outcome alerts; Epic 1 Story 1.11 does not add its own failed-run alert (D5)

**Given** the same job keeps failing every run
**When** the alert is already open
**Then** no further email is sent until it closes and reopens (auto-close and renotify settings are explicit)

**Given** an alert email
**When** it is read
**Then** it names the job and status and links to the job in the console

### Story 6.3: Alerts when backups go quiet

**Covers:** FR38

As a backup admin,
I want an alert when a job has not succeeded for too long, or the scheduler stops running,
So that silent failures are caught too.

**Acceptance Criteria:**

**Given** an enabled, scheduled job older than N hours with no successful run in the last N hours (N set in Settings)
**When** `run-due` runs
**Then** it logs one `job_stale` event when the job becomes stale and one `job_recovered` event when it next succeeds
**And** the last alerted state is stored per job so the event is not repeated every 15 minutes

**Given** disabled jobs, unscheduled jobs and jobs created less than N hours ago
**When** staleness is checked
**Then** they are excluded

**Given** a job whose backup is still in progress across executions (resuming, or onboarding under Epic 10)
**When** staleness is checked
**Then** it is not stale while it is making progress; stale means no successful run and no progress (as defined in Story 6.1) for N hours. A stuck backup is reported by Story 6.2 after three executions, and by this story after N hours if that comes first; each problem is alerted once

**Given** no `run-due` heartbeat has been logged for 1 hour
**When** Cloud Monitoring evaluates it
**Then** a "scheduler not running" alert fires through the same channel

### Story 6.4: The Aviato emailer is ready but switched off

**Covers:** FR39

As a backup admin,
I want bgb ready to send richer alert emails through the Aviato emailer,
So that we can switch it on once the emailer accepts the bgb project, without new code.

**Acceptance Criteria:**

**Given** the alert sender interface and an `EmailerProxySender`
**When** `emailer_enabled` is false (the default)
**Then** nothing is sent and no emailer call is attempted

**Given** Settings
**When** an admin opens them
**Then** they can set sender address, recipients and the stale threshold N, and the emailer URL and audience are stored in Settings, not code or environment variables

**Given** `emailer_enabled` is true
**When** a run fails or finishes with warnings, a backup is stuck (Story 6.1), or a job goes stale
**Then** one email per job and condition is sent through the emailer with a Google ID token, naming the users, drives or items involved
**And** no email repeats until the condition changes or recovers

**Given** the emailer is unreachable or returns an error
**When** an alert is sent
**Then** the failure is logged and the run's status and the `run-due` result are unchanged

**And** the README documents the one-off `roles/run.invoker` grant on the emailer and that the emailer team must admit the project first.

## Epic 7: Restore into Workspace, safely

An admin can restore a mailbox, drive, shared drive or several users back into Workspace, choosing the target user or domain each time, with a dry run first and a typed confirmation of the target. Builds on Epic 2's lease and Epic 5's console. Restores and large dry runs run as backup-job executions with overrides, checkpoint per item and resume on retry. While a restore runs it holds a restore hold on the job: scheduled backups continue, but compaction, retention, prune and delete wait until it ends (D9); the API only creates plans, starts executions and reports progress (D3). All restore calls go through Story 10.2's pacing. With no test domain, the dry run stands in for end-to-end testing.

### Story 7.1: Restore targets and their credentials

**Covers:** FR41

**Note (D6):** write scopes are declared as a "restore" capability in the source catalog (Epic 9 Story 9.1), which generates the README delegation table.

As a backup admin,
I want to register each domain I may restore into, with its own credentials,
So that restoring into another domain uses that domain's own permissions.

**Acceptance Criteria:**

**Given** Settings
**When** an admin adds a restore target domain
**Then** they set the domain, an admin email and the Secret Manager secret name (or keyless delegation), and the source domain is registered by default

**Given** a target domain
**When** the admin runs its connection test
**Then** bgb reports whether the write scopes are delegated (Gmail insert or import, Drive write including shared drive creation and permission changes) and names any missing scope

**And** the README lists the write scopes to add to domain-wide delegation, separately from the read scopes.

### Story 7.2: Plan a restore and see a dry run

**Covers:** FR41, FR42, UX-DR5

As a backup admin,
I want to choose what to restore and where, and see exactly what would be written,
So that I can check a restore before anything changes in Workspace.

**Acceptance Criteria:**

**Given** a job and a backup version
**When** I build a restore plan
**Then** I can pick one or more sources (a user's mailbox, a user's My Drive, a shared drive) and map each to a target user or target shared drive in any registered target domain

**Given** a restore plan
**When** I run it as a dry run (UI, API or `bgb restore --dry-run`)
**Then** it reports per target the item count, total size, and the paths or labels that would be created, and writes nothing to Workspace

**Given** a target user or shared drive that does not exist in the target domain
**When** the dry run checks it
**Then** it is reported as an error in the plan

### Story 7.3: Restore a mailbox into Gmail

**Covers:** FR40, FR43

As a backup admin,
I want a backed-up mailbox written back into a Gmail account,
So that a person, or their replacement, gets their mail back.

**Acceptance Criteria:**

**Given** a confirmed restore plan with a mailbox source
**When** it runs
**Then** each message is imported into the target user's Gmail with its original date and labels
**And** when the plan's "label restored items" option is on (the default), a dated "Restored by bgb" label is added

**Given** a restore that stopped partway
**When** it is run again
**Then** messages already imported (recorded per plan item) are skipped, so nothing is duplicated

**Given** one message fails to import
**When** the restore continues
**Then** it is recorded as failed with the reason and the rest carry on

**And** the API refuses to execute a plan unless the request carries the exact target address typed by the user.

### Story 7.4: Restore a drive or shared drive

**Covers:** FR40, FR43, FR44 (restore), FR45

As a backup admin,
I want backed-up Drive content written back into Drive,
So that a person's files or a shared drive can be recovered.

**Acceptance Criteria:**

**Given** a confirmed plan with a My Drive or shared drive source
**When** it runs
**Then** files are restored into the target's My Drive or shared drive keeping the original folder structure, inside a dated "Restored by bgb" folder when the plan's label option is on (the default), or at the original paths when it is off

**Given** a shared drive source whose target shared drive does not exist, or a plan that asks for a new shared drive
**When** the restore runs
**Then** bgb creates the shared drive in the target domain, using that domain's admin credentials, named as in the plan (the original name by default), restores its members, and restores into it

**Given** files that were exported Google Docs, Sheets or Slides
**When** they are restored
**Then** they are converted back to Google formats where Drive supports it, otherwise uploaded as the exported file

**Given** a restore that stopped partway
**When** it is run again
**Then** files already uploaded are skipped

**Given** files whose sharing permissions were backed up (Story 3.12)
**When** they are restored
**Then** their permissions are reapplied without sending notification emails
**And** when restoring into a different domain, permissions for addresses that do not exist in the target domain are skipped and listed in the restore record

**And** revision history is not restored, and the plan and dry run say so.

### Story 7.5: Restore several users at once

**Covers:** FR40

As a backup admin,
I want one restore to cover many users,
So that I can recover a team in one operation.

**Acceptance Criteria:**

**Given** a plan with several sources
**When** it runs
**Then** each source restores independently, and one target failing does not stop the others

**Given** a finished multi-user restore
**When** I open its record
**Then** I see per target the items written, skipped and failed, with reasons

**Given** a running restore
**When** a scheduled or manual backup of the same job runs
**Then** it runs normally, but skips compaction, retention and the sweep for that job until the restore ends

**Given** a running restore
**When** prune, rebuild or delete is requested for the same job
**Then** it is refused with 409 naming the restore, so nothing the restore reads is removed (D9)

**Given** a restore that stopped without finishing
**When** its hold is older than the lease TTL with no heartbeat
**Then** the hold is released and clean-up resumes

### Story 7.6: The restore screen makes the target impossible to miss

**Covers:** UX-DR3, UX-DR4

As a backup admin,
I want the restore screen to show plainly what goes where and make me type the target,
So that I never restore someone's mailbox into the wrong account under pressure.

**Acceptance Criteria:**

**Given** a restore plan in the console
**When** I review it
**Then** each row shows source user, target user and target domain in large type
**And** a target outside the source domain is marked "Different domain"

**Given** the confirmation step
**When** I try to start the restore
**Then** the button stays disabled until I type the target address exactly (for a multi-target plan, the number of targets)

**Given** a plan that has never been dry-run
**When** I open the confirmation step
**Then** the dry run runs first and its results are shown before confirmation is offered

**Given** a running restore
**When** I watch it
**Then** progress shows per target, and the final summary matches the Story 7.5 record

## Epic 10: Large organisations onboard without hitting Google limits

An admin can take on a very large organisation (for example 10,000 users) knowing in advance how long the first backup will take. Users are onboarded in daily phases, Google API use stays below 80% of quota, and long first backups continue across job runs. Needs Epics 2 and 3. Must ship before any large organisation is onboarded.

### Story 10.1: Long backups resume without false alarms

**Covers:** FR47

**Baseline (D2):** checkpoint and resume exist (`test_killed_run_resumes_without_rereading`). This story extends them; the clean stop, the `continuing` status and partial versions from the earlier draft are dropped. Finished users become restorable early through phased onboarding (Story 10.3), where each cohort's run completes a version.

As a backup admin,
I want a backup that is too big for one job run to resume in the next, and to look like one backup while it does,
So that a very large mailbox or drive finishes over several runs without false alarms.

**Acceptance Criteria:**

**Given** a run stopped by the job timeout or a crash, with a checkpoint
**When** the next execution (a retry or the next schedule) starts
**Then** the stopped run is marked `timed_out` (Story 2.2) and the new run resumes without re-reading finished files

**Given** a backup in progress across several executions
**When** I open the job
**Then** it shows as one backup in progress, with files and bytes done so far

**Given** a resumed backup that is still making progress
**When** alerts are evaluated (Epic 6)
**Then** no alert fires; the `backup_stuck` rule in Story 6.1 (three executions in a row with no progress) decides when to alert

**And** the README documents the job timeout (24 hours, up to 168) and retries (3) as the settings for very large users.

### Story 10.2: Google API calls stay within a quota budget

**Covers:** FR46

**Additions:** the Cloud Quotas API is enabled and the runtime account can read quotas (proposed for Epic 8 Story 8.1). Pacing covers every Google API caller: Epic 3 sources, Story 3.12 permission reads, Epic 7 restores and Epic 9 sources.

As a backup admin,
I want bgb to pace its Google API calls,
So that backups never push the organisation close to Google's limits and get throttled or blocked.

**Acceptance Criteria:**

**Given** a quota budget setting (default 80%)
**When** bgb calls the Gmail, Drive, People and Admin Directory APIs
**Then** calls are paced per API, per user and per project so usage stays below the budget of each applicable quota

**Given** the project's quotas as reported by Google (Cloud Quotas API)
**When** they are available
**Then** they are used as the limits; otherwise limits come from configuration, with defaults that are checked against Google's published quotas at implementation time

**Given** pacing slows a run
**When** the run approaches its time limit
**Then** it stops at a checkpoint (Story 10.1) rather than exceeding the budget

**And** each run records API usage per API as a share of the budget, and the job view shows it.

### Story 10.3: Large organisations onboard in phases

**Covers:** FR48

As a backup admin,
I want a large organisation's first backups spread over several days,
So that onboarding never overloads Google's limits or bgb.

**Acceptance Criteria:**

**Given** a job with more users than a configurable threshold, or an admin who turns phasing on
**When** the job is enabled
**Then** its users are split deterministically into cohorts (default 28), and one cohort's first full backup runs per day

**Given** users already onboarded
**When** any scheduled run happens
**Then** they get incremental backups as normal

**Given** users added to the directory during or after onboarding
**When** they are discovered
**Then** they join the next day's cohort

**Given** onboarding in progress
**When** I open the job
**Then** I see users onboarded out of the total, today's cohort, and the expected finish date
**And** I can pause onboarding or change the number of cohorts

**And** stale and warning alerts (Epic 6) ignore users not yet onboarded, and one summary alert is sent when onboarding finishes.

### Story 10.4: Know how long onboarding will take

**Covers:** FR49

**Note (D6):** the Reports usage scope is declared as an "estimate" capability in the source catalog (Epic 9 Story 9.1).

As a backup admin,
I want an estimate of how long a new organisation's first backup will take before it starts,
So that I can set expectations with the organisation (for example "about 4 weeks for 10,000 users").

**Acceptance Criteria:**

**Given** a new job before its first backup
**When** I request an estimate, or save the job
**Then** bgb reads the user count and per-user mail and Drive storage (Admin SDK Reports API usage data, which needs its read scope added to delegation) and calculates the duration from data volume, the quota budget (Story 10.2) and the cohort plan (Story 10.3)
**And** it shows the estimate in days or weeks, the cohort plan, and the assumptions used

**Given** the reports scope is not delegated
**When** I request an estimate
**Then** bgb says which scope is missing and gives an estimate from user count alone, clearly marked as rough

**Given** onboarding has started
**When** I open the job
**Then** actual progress is compared with the estimate

**And** the README explains onboarding a large organisation, with a worked 10,000 user example.
