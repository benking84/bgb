# bgb fix plan (revised, staged)

**Status:** Draft for review

> **Superseded in part (2026-10-31).** Commit `5d1c615` implemented parts of Stages 1 to 3 and 5 (job lease, checkpoint and resume, run-due isolation, rate-limit retries, Drive streaming, retention-aware deletes, bucket retention and soft delete). Retention defaults are now 30 days and soft delete 90 days (D1). `epics.md` is the source of truth; see `sprint-change-proposal-2026-10-31.md`.
**Date:** 2026-10-31
**Inputs:** full repository code review (4 reviewers), plan review (adversarial and edge-case lenses), party-mode roundtable with Ben.

## Context

bgb is an internal Aviato service on Google Cloud. It may be commercialised later, so the code avoids hard ties to Aviato infrastructure where a small seam costs little, and builds nothing else for that future.

It runs in `aviato-prod-demo-baby-got-back`, a Demo-tier landing zone project: one project, no Shared VPC (per Epic 1, `epics/epic-1-pipeline-quality-gates.md`). Epic 1 owns the CI pipeline, emulators and test infrastructure. The stages below own the product fixes and their unit tests.

There is no test Workspace domain. Behaviour that can only be confirmed against a live domain is built so that it is safe whichever way the check would turn out (see "Unverified assumptions").

## How the work runs

Nine stages, applied in order. Each stage ends with its own tests passing before the next starts:

- `pytest`
- `terraform fmt -check` and `terraform validate` when Terraform changed
- `npm run lint` and `npm run build` in `web/` when the UI changed

Irreversible or unconfirmed infrastructure (the retention lock and VPC egress) ships behind Terraform variables that default to off.

## Stage 1. Run ownership and lifecycle

Foundation for every later stage.

- **Run lease (P10).** A Firestore transaction on the job document holds `active_run_id`, `lease_expires` and `heartbeat`.
  - The claim succeeds when the lease is empty, has expired, or already belongs to the caller's run id, so "Run now" can execute its own queued run.
  - Runs renew the lease periodically.
- **Maintenance takes the lease (P9).** Prune, rebuild and delete-job take the same lease and return 409 while a run holds it. A backup cannot start during a rebuild either.
- **Expired runs (P8).** A sweep marks a run whose lease expired without a heartbeat as `timed_out`. That replaces the fixed 24-hour `busy()` horizon.
- **Scheduler isolation (P2).** `run_due` handles each job separately. An error before a run record exists (missing job, bad config) is recorded as a failed run, so it is visible and can alert.
- **Per-job storage settings (D8, merged with P11).**
  - On the first run, before any volume is written, the job records its `gcs_prefix` and `block_size`. From then on, the engine reads them from the job, never from global settings.
  - Existing jobs are backfilled from where their volumes actually live (the index's volume names).
  - The end of a run updates only `source_state` and `updated_at` (a field-level `finish_run`). Edits made to the job during a run are kept.
  - Changing the bucket is refused while any job has backups.
- **Safe rebuild.** Rebuild refuses to clear the index when the listing is empty, or when it holds no fileset (dlist) volume. It validates every fileset before clearing anything.
- **Tests:** P24 (`run_due` selection), P25 (concurrent-run guard), lease expiry, and maintenance returning 409 during a run.

## Stage 2. Source error isolation

- **Scope failure (P1, D3).** If a whole user or shared drive fails, its previous entries carry forward unchanged and its cursor is not advanced. A warning names the scope. Nothing is counted as deleted.
- **Object failure (P1).**
  - Only errors from reading the source are caught: Google API `HttpError`, `RefreshError`, a not-found file, and an unsafe path.
  - Storage and index write errors still fail the run.
  - A failed object keeps its previous entry. A new object that fails is recorded in `source_state` as pending and retried on the next run.
- **Warnings affect status.** A run with scan warnings ends as `completed_with_warnings`.
- **Retries (P13).** Retry 429, 500, 502, 503, 504, connection errors, and 403 only when the reason is `rateLimitExceeded` or `userRateLimitExceeded`. Use backoff with jitter. Other 403s, such as `exportSizeLimitExceeded`, are not retried.
- **Contacts (P14, W1).**
  - Keep `syncToken` on every page request.
  - Treat 400 `EXPIRED_SYNC_TOKEN` and 410 alike as "expired": fall back to a full listing.
- **Shared drives (D3).**
  - List with `useDomainAdminAccess`. This requires `admin_email` to be set when shared drives are included.
  - Each drive is isolated as in the scope-failure rule.
  - Unreadable drives are reported once, by name.
- **Suspended users (D4).** Included in "every user", in freeze-only mode: their last backed-up entries are kept and they are not scanned. See "Unverified assumptions".
- **Users removed from the directory.** Treated the same as suspended users: entries are frozen and a warning is raised. *(Default chosen by the room, confirm.)*
- **Selection (P17).**
  - When "every user" is ticked, the directory wins over any typed users, and the UI sends an empty users list.
  - Existing jobs affected by this are listed in a warning before the change takes effect.

## Stage 3. Streaming and memory

- **Streaming reads (P4).** Drive downloads and exports stream to the engine through a reader that always returns full blocks, except for the last one. That keeps block boundaries, and so deduplication, stable.
- **Mid-file retries (P13).** A retried download resumes with a Range request from the bytes already read. Exports cannot resume, so they restart the whole file with a fresh hasher and discard that file's pending blocks.
- **Split file lists (P16).** The fileset (dlist) is written in parts, each capped, rather than one object. Rebuild reads multi-part dlists.
- **Fileset write order (P5).** Write the fileset summary with `complete=false`, then the entries, then set `complete=true`. Every read ignores incomplete filesets. Deleting a fileset clears the flag first.

## Stage 4. Identity migration (Drive, Gmail, Contacts)

- **Drive identity (D2).**
  - Drive source ids include the scanning user: one helper builds every id, deleted ids included.
  - Migration matches old entries by `(scope, file_id)`, so unchanged revisions are reused and nothing is downloaded again.
  - A schema version in `source_state` triggers the migration once.
  - Incremental and full scans cover the same set of files.
- **Paths (P18, P29).** Path conflicts are resolved in the engine after retained and changed entries are merged for a scope. A file's own previous path is excluded. Suffixes are deterministic, and the engine loops until a path is unique.
- **Gmail (P30).** Messages moved into Spam or Trash are treated as deleted, which matches full scans.
- **Contacts fields (P21).** Add addresses, birthdays, URLs, relations, user-defined fields and memberships. A schema version bump forces one full Contacts scan.

## Stage 5. Deletion that respects locked retention (code only)

- **Minimum age.** A minimum object age (default 7 days, injectable, 0 in tests) is measured from the Cloud Storage object's creation time, not bgb's own timestamps.
- **Compaction.** Checks age before any rewrite, and skips volumes that are too young.
- **Retention.** A fileset due for removal whose dlist is too young is marked `pending_delete` and finished on a later run. The index row is not removed while the object exists.
- **Prune.** Skips objects that are too young.
- **Delete job.** Refused with 409 while any object is still inside the window. The response gives the earliest date it can be deleted.
- **Cloud Storage errors (P12).** `GCSVolumeStore` maps not-found to `FileNotFoundError`, and retention-hold refusals to a "deferred" result.
- **Rebuild links (P15).** Rebuild restores the links between each block volume and its index volume.

## Stage 6. API and UI

- **Access (D1).**
  - The app token moves to an `X-BGB-Token` header, so it cannot clash with IAP's use of `Authorization`.
  - Comparison is constant-time on bytes.
  - Terraform passes `BGB_REQUIRE_TOKEN` and the app fails closed when it is set without a token.
  - The token check runs inside the CORS layer and lets preflight requests through (P34).
  - CORS is removed in production (the UI is served from the same origin). `BGB_CORS_ORIGINS` is for local development only.
- **Settings page (P7).** The token field shows even when settings return 401, and the token is saved independently of the settings save.
- **Downloads (P6).** The filename uses `filename*=UTF-8''`, plus a sanitised ASCII fallback with no control characters or quotes.
- **Job edits (P27, P26).** A `JobPatch` model with all fields optional is merged onto the current job, and the merged result is validated. Under D8, block size is fixed once recorded.
- **File browser (P19, P31, P32).**
  - Pages with `next_cursor`.
  - Drops responses for an older prefix or fileset.
  - Resets the selected fileset if retention removed it.
- **Small fixes.**
  - P20: `count()` aggregation for block counts.
  - P28: prefix upper bound by incrementing the last character.
  - P33: retention accepts an interval equal to its timeframe.
- **Tests:** P23 (token gate), P26, and P22 (Firestore index contract test, including a file over 4,000 blocks and prefix plus cursor listing).

## Stage 7. Alerting (D6)

Decided 2026-10-31: **both**. Cloud Monitoring alerts now, and the Aviato emailer later.

- **Now: Cloud Monitoring.**
  - Log-based metrics and alert policies on failed and timed-out runs and on stale jobs, sent through an email notification channel.
  - This works from the Demo project without any network change, and is shared with Epic 1 Story 1.11, which sets up the failed-execution alert and notification channel. Stage 7 adds bgb's own conditions (`timed_out`, `completed_with_warnings`, stale jobs) to that channel and does not create a second one.
  - bgb writes one structured log line per run outcome (job id, run id, status, error, warning count) so the metrics are reliable.
- **Later: the emailer.**
  - A small sender interface, with `EmailerProxySender` as the first implementation. It calls the internal emailer with a Google ID token.
  - Off by default (`alerts.emailer_enabled = false`) until the emailer team admits the bgb project. The emailer only accepts internal traffic, and the Demo project has no Shared VPC, so this needs a VPC Service Controls perimeter or a change to the emailer's ingress. That is an action for the emailer owners, not this plan.
  - Once on, it sends the richer per-run emails (what failed, which users or drives, links to the run).
- **Configuration.**
  - The emailer URL and project are configuration, not code.
  - The sender address, recipient list and "no success in N hours" threshold live in Settings. The threshold also feeds the Cloud Monitoring stale-job policy.
- **Triggers.** Alerts fire on:
  - `failed` and `timed_out` runs
  - `completed_with_warnings`, as one summary per run
  - stale jobs: enabled and scheduled jobs with no success in N hours, excluding jobs younger than N hours
- **Deduplication.** A last-alerted time is kept per job and condition, so one problem sends one email until it changes or recovers.
- **Failure handling.** A failed alert is logged and never changes a run's status.

## Stage 8. Terraform and docs

- **Run now (P3).** Grant the runtime service account `roles/run.jobsExecutorWithOverrides` on the backup job.
- **IAP (D1).** IAP in front of the UI service, mutually exclusive with `allow_unauthenticated`. `BGB_REQUIRE_TOKEN` is set when the service is public.
- **Bucket (D5).**
  - Soft delete for 7 days.
  - A retention policy of 7 days, with `lock_retention` defaulting to `false`.
  - Versioning off (no benefit, since bgb never overwrites an object).
- **Firestore (D5).** Point-in-time recovery on.
- **Alerting (D6).**
  - Log-based metrics and alert policies for bgb's run outcomes, attached to the notification channel from Epic 1 Story 1.11.
  - Emailer access stays off (`emailer_enabled = false`). No VPC egress is added in this plan. When the emailer team admits the project, enabling it is a variable change, plus the one-off `roles/run.invoker` grant on the emailer.
- **Docs (P35).**
  - README covers building and pushing the image, plus an Artifact Registry repository.
  - The one-off `gcloud` grant of `roles/run.invoker` on the emailer for bgb's runtime service account.
  - `docs/lock-checklist.md`.

## Stage 9. Retention lock sign-off

About two weeks after deploy, Ben checks:

1. Every run succeeded.
2. Compaction and retention ran without errors.
3. Prune skipped objects that were too young.
4. Verify reported no unexplained objects.

Then apply with `lock_retention=true`. The lock is permanent and cannot be undone.

**Owner:** Ben *(suggested, confirm)*.

## Unverified assumptions

These were not checked live because there is no test domain. Each one is built so that a wrong guess fails safe.

| Assumption | Safe default in this plan |
|---|---|
| Domain-wide delegation may not impersonate suspended users | Freeze-only, no scanning |
| IAP may reject a non-Google `Authorization` bearer | App token moved to `X-BGB-Token` |
| People API may return 400 rather than 410 for an expired sync token | Both treated as expired |
| "Run now" with overrides needs `run.jobs.runWithOverrides` | Role granted in Stage 8 |
| The bgb project can reach the emailer's internal ingress | Not assumed. Cloud Monitoring alerts carry alerting now; the emailer sender stays off until the emailer team admits the project |

## Out of scope: bulk restore (D7), separate work item

Requirements captured for its brief:

- **Write-back.** Gmail via import, Drive via upload. Restore covers a user's mailbox, a user's drive, a shared drive, and many users at once.
- **Target choice.** The person restoring picks the target on each restore: another user in the same domain, or the same user in a different domain. Each target domain needs its own delegated credentials and write scopes.
- **Dry run.** `--dry-run` reports counts and paths per target without writing anything. With no test domain, this stands in for end-to-end testing.
- **Confirmation screen.** Shows the source user, target user and target domain prominently, and requires the target address to be typed before writing.
- **Labelling.** Restored items get a "Restored by bgb" Gmail label or Drive folder with the date. *(Proposed, confirm.)*
