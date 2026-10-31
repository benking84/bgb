---
title: 'technical research: Google Workspace backup on Google Cloud, first principles review of bgb'
type: 'technical'
topic: 'Google Workspace backup on Google Cloud: first principles review of bgb'
decision: "Will bgb's architecture work for a real Workspace domain, and which decisions must change"
source: 'native run (4 researchers, 1 verifier), 2026-10-31'
status: complete
preset: 'standard'
validation: 'normal'
created: '2026-10-31'
updated: '2026-10-31'
claims_verified: 8
claims_unverified: 14
---

# Google Workspace backup on Google Cloud: first principles review of bgb

**Status: draft for review.** Prepared 2026-10-31. Not yet reviewed by a person. Figures for limits and pricing came from Google pages that were read through a summarising fetch tool. Re-read them verbatim before using them in client material.

**Decision this research serves:** will bgb's architecture work for a real Workspace domain (hundreds to thousands of users, terabytes of data), and which decisions must change before more is built.

**How to read it.** Sections 1 to 4 are external evidence, cited `[n]`. Section 5 maps that evidence onto bgb. Statements about bgb come from reading the code at commit `e3b0171`. They are labelled as code observations and are not cited.

## Executive summary

**Verdict: the platform choices are sound. The way the engine runs a backup is not.** In its current shape, bgb will work for small domains and the demo. It will fail on the first full backup of any large mailbox or Drive, and it does not protect its backups against the credential that writes them. None of this needs a new architecture. It needs five specific changes before a client pilot.

What drives that answer:

1. **The first full backup of a large mailbox cannot finish, and gets no further on later runs.** Since 1 May 2026, Gmail allows 6,000 quota units per minute per user, and fetching a raw message costs 60 units [1]. bgb also fetches metadata for every message (20 units), so the ceiling is about 75 messages per minute per user. A 100,000 message mailbox therefore needs at least 22 hours. The backup job times out after 4 hours with no retries (code), and the fileset is only written at the end of a run (code). Each later run downloads the same messages again. Dedup saves the upload but not the download.
2. **Large files will crash the run.** Drive downloads and exports are read fully into memory before chunking (code), and the job has 2 GiB. Docs, Sheets and Slides exports over 10 MB fail by API design [5].
3. **Backups are deletable by the account that writes them.** The bucket has no retention policy (code). Only a locked bucket retention policy or locked object retention stops a compromised writer from deleting data [20][21]. Soft delete can be switched off by anyone who can update the bucket [19]. Google's Backup and DR vaults, which are indelible, do not cover Cloud Storage, Firestore or Workspace data [23].

**Biggest caveat.** Two things are unproven: whether bgb is worth building rather than buying, and whether restore is good enough. Commercial products sell restore back into Workspace with permissions and labels intact [33][51]. bgb restores files to local disk only (code). Vault is explicitly not a backup tool [30], and native admin restore is limited to 25 days and does not restore sharing [31], so a gap exists. Whether bgb closes it for a client depends on that client's restore expectations. This report cannot settle that.

## 1. Google Workspace API reality

**Gmail.** Quotas changed on 1 May 2026: 1,200,000 units per minute per project and 6,000 per minute per user [1]. `messages.get` costs 20 units, or 60 with `format=raw`, `full` or `html` [1] (verifier correction: this is not specific to raw). Batches are capped at 100 calls, with 50 or fewer recommended, and every call in a batch still counts against quota [3]. Google gives no fixed history window. Records are "typically available for at least one week", and an expired `startHistoryId` returns HTTP 404, which forces a full resync [2]. Projects that used the API between November 2025 and April 2026 keep their earlier quotas [1]. Confidence: high (verified against the primary page, with one independent guide agreeing).

**Drive.** `files.export` output is limited to 10 MB [5]. `files.download` is a newer asynchronous method that also exports Workspace documents and states no size limit [6]. Whether it actually handles large documents is **unverified**. Forms, Sites, Jamboard, Maps and shortcuts are absent from the export table [7]. Drive keeps a separate change log for each shared drive. The user's log does not reliably include shared drive items, a deletion looks the same as a loss of access, and permission changes show only on the item that changed [9]. Change token expiry is not documented [9]. Per project, there is a 1 TB per day egress threshold and a 400,000,000 units per day threshold that cannot be raised. Google says exceeding them "is planned to incur charges ... later in 2026", with at least 90 days' notice [8]. Downloads cost 200 units each [8]. Confidence: high for the limits (verified), medium for the change log behaviour (single primary source).

**Contacts.** People API sync tokens expire 7 days after the full sync and return `EXPIRED_SYNC_TOKEN` [10]. Other contacts and directory contacts use separate methods [10]. Confidence: high.

**Keep.** A Google Keep API exists for enterprise administrators using domain-wide delegation. It can list and get notes and download attachments [11]. The note resource does not include labels, colours, reminders, or pinned or archived state, so a restore from it loses those [12]. Confidence: high that the API exists (verified), medium for the field gaps.

**Chat and Sites.** A delegated service account can read Chat only as each user. There is no admin-level read of message content [13]. New Google Sites has no public content API. That comes from vendor sources only (low confidence), and one vendor lists Sites as unsupported for that reason [32].

**Credentials.** Organisations created on or after 3 May 2024 enforce `iam.managed.disableServiceAccountKeyCreation` by default [14]. Google recommends keyless signing through the IAM Credentials `signJwt` API for domain-wide delegation, and keeping delegation accounts in dedicated projects because they can impersonate any user [28][29]. Changes to domain-wide delegation can require a second super admin's approval [15].

## 2. Native options and the market

Google states that Vault "isn't designed to be a backup or archive tool". Vault exports cover one service at a time, cannot be scheduled, and are not meant for high volume [30]. The Vault API allows 20 concurrent exports per organisation, and exports expire after 15 days [4]. A deleted user's data can be recovered for 20 days [30]. Admin Drive restore works only within 25 days after trash is emptied, only by date range, and sharing is not restored [31]. No Google-native Workspace backup product was found, and Backup and DR does not list Workspace [23] (absence of evidence only).

Commercial products advertise point-in-time restore back into the same account or another one, with permissions and nested Gmail labels preserved [33][51]. Afi claims it keeps Drive file IDs on restore [33] (vendor claim, medium confidence). Keepit's June 2026 coverage page admits gaps: no Sites, Chat, Keep or Contacts [32]. Veeam has said it will not pursue Workspace backup [35]. Commvault announced a Workspace offering in October 2024 [36]. CubeBackup is the closest analogue: self-hosted, covering Gmail, Drive, shared drives, Calendar and Contacts, priced at about USD 5 per user per year [34]. That price is undated and low confidence.

Open-source tools show where restore breaks. Got Your Back (GYB) restores fail on invalid label names and on oversized messages, and labels get flattened on mbox restore [37]. A vendor reports that Docs over about 11 MB cannot be exported to Office formats [38], which is consistent with Google's 10 MB export limit [5].

User reviews of throttling and restore fidelity were searched for and not found within budget.

## 3. Google Cloud building blocks

**Immutability.**
- *Locked bucket retention.* A locked bucket retention policy blocks deletes and replacements until objects reach the retention age. It can be lengthened but never shortened or removed, and it places a lien on the project [20].
- *Object Retention Lock.* This sets retention per object. In Locked mode it cannot be reduced [21].
- *Soft delete.* The default is 7 days, configurable from 7 to 90, and it can be disabled by setting it to 0. Soft-deleted objects are billed [19]. Lifecycle rules can delete locked objects only after retention is met [20].
- *Storage class minimums.* Nearline has a 30 day minimum, Coldline 90 days and Archive 365 days [22]. Rewrites before then incur early deletion charges.
- *Backup and DR vaults.* These are indelible even to administrators, but they support Compute Engine, disks, Filestore, Cloud SQL and AlloyDB, not Cloud Storage or Firestore [23].

**Cloud Run jobs.** The task timeout can be set up to 168 hours and applies per attempt. Google recommends retries for long tasks [16]. No documented control stops a new execution of a job while another is still running [17]. Parallelism only limits tasks within one execution [17]. A community thread confirms the gap [18]. Status: unverified absence, so plan an application lock.

**Firestore.**
- *Pricing.* Standard edition is USD 0.09 per 100,000 writes and USD 0.03 per 100,000 reads (us-central1) [24].
- *Throughput.* New collections should ramp using the 500/50/5 rule. Sequential IDs and indexed timestamps cause hotspots [25].
- *Limits.* Documents max out at 1 MiB and transactions at 270 seconds. The quotas page no longer lists a 500 writes per transaction limit [26].
- *Recovery.* Point-in-time recovery covers 7 days, and scheduled backups are kept for at most 14 weeks [27]. Longer retention needs exports, or an index that can be rebuilt from the stored objects.

## 4. Backup engine design lessons

- **Block size.** Duplicati moved its default block size from 100 KB to 1 MB in April 2024 "to reduce the blocks to track by a factor of 10" [41]. Users report a performance cliff below about 0.5 to 1 MB on large backups [42].
- **Index cost.** Borg documents index cost at about 164 bytes per chunk, so cost scales inversely with chunk size [40].
- **Chunking.** restic averages about 1 MiB chunks using content-defined chunking and does not split files under 512 KiB [39]. Whole-file dedup captured about 75 to 87% of block-level savings in a large Microsoft study [50] (medium confidence, figures taken from the abstract).
- **Index rebuilds.** Duplicati's compaction bug wrote incomplete index files. Rebuilds then fell back to downloading every data volume, which took 12 hours or more, and already-written files stay broken after the fix [43]. Lesson: the index must be rebuildable from the backup store, and that rebuild must be tested and timed.
- **Crash safety.** restic writes data packs, then the index, then the snapshot last. Prune takes an exclusive lock and removes a pack from the index before deleting it [39]. Kopia and Duplicacy use time margins or two-step deletion so that compaction cannot remove blocks a running backup has just deduplicated against [44][45].
- **Verification.** Checking structure alone does not prove the data is intact. restic needs `--read-data` or a rotating subset for that [46]. CISA advises offline, encrypted backups with regular restore tests [47] (medium confidence, wording from a summary).
- **Encryption.** restic and Kopia always encrypt on the client, and Kopia refuses unencrypted repositories [39][48]. Every modern engine reviewed offers zstd. zlib is the slowest option borg lists [49][40].

## 5. Mapping to bgb: keep, change, risk

Code observations are marked (code). Severity reflects whether the item stops bgb from working at domain scale.

| # | bgb decision | Evidence | Assessment | Severity |
|---|---|---|---|---|
| 1 | Single Cloud Run task, 4 h timeout, `max_retries = 0`; fileset written only at end of run (code) | Gmail about 75 msgs/min/user with metadata plus raw [1]; timeout up to 168 h [16] | **Change.** Large first backups never complete and redo all downloads on every run. Checkpoint progress per scope (persist partial filesets and Gmail page tokens), raise the timeout, enable retries, and split users across tasks. | Blocker |
| 2 | Whole object read into `BytesIO` before chunking, 2 GiB job memory (code) | Drive allows files up to 5 TB [8] | **Change.** Stream downloads block by block. One large video kills the whole run. | Blocker |
| 3 | Bucket without retention policy; runtime account can delete volumes; `delete_job` deletes them (code) | Only locked retention prevents deletion [20][21]; soft delete can be disabled [19]; vaults do not apply [23] | **Change.** Add a locked bucket retention or object lock period (for example 30 days), set soft delete to 90 days, move the bucket to a separate backup project, and run compaction and deletes under a separate identity. Compaction must skip volumes still under retention. | Blocker for client use |
| 4 | Overlap guard is a non-atomic "latest run busy" check with a 24 h horizon, while the job timeout is 4 h (code) | No platform overlap control [17][18] | **Change.** Use a Firestore transaction lease with an expiry slightly above the task timeout and a heartbeat. Today a killed run blocks that job for up to 20 hours, and two triggers can still race. | High |
| 5 | Retries only on HTTP 429, 500 and 503 (code) | Drive returns 403 `userRateLimitExceeded` [8] | **Change.** Retry 403 rate-limit reasons with backoff, and pace requests to the per-user quota. | High |
| 6 | Docs, Sheets and Slides exported with `files.export` (code) | 10 MB limit [5]; `files.download` may avoid it [6] (unverified) | **Change.** Test `files.download` for large documents, and report oversized documents explicitly rather than failing the run. | High |
| 7 | 100 KiB fixed blocks, one Firestore read per block lookup and one document per block (code) | Duplicati abandoned 100 KB [41][42]; index cost scales with block count [40]; Firestore cost is low [24] | **Change.** Keep fixed blocks but raise the default to 1 MiB, store each mail message as a single block, and batch lookups (`getAll`). Firestore cost is not the problem. Per-block round trips are (an estimate from the code, not measured). | Medium |
| 8 | Index in Firestore, rebuildable from volumes (`bgb rebuild`) | Duplicati failure [43]; Firestore backups capped at 14 weeks [27] | **Keep**, and add a scheduled, timed rebuild test. Confirm that compaction rewrites the index metadata correctly. | Keep |
| 9 | Cloud Run, Scheduler, GCS and Firestore on the client's project, deployed by Terraform | Building blocks fit (sections 3 and 4) | **Keep.** Customer-owned storage is the clearest point of difference from SaaS vendors [33][32]. | Keep |
| 10 | Keyless delegation via the runtime account's `signJwt`; JSON key optional | Google guidance [28][29]; key creation blocked by default [14] | **Keep**, and make keyless the documented default. Consider moving the delegating account to a dedicated project [29]. | Keep |
| 11 | No application encryption; Google-managed or CMEK at rest | All engines reviewed encrypt on the client [39][48]; CISA advises encrypted backups [47] | **Risk, accepted with reasons.** This is defensible when the threat is credential compromise, which items 3 and 10 address, rather than the provider. It differs from engine norms, so it should be stated in the client design record. | Medium |
| 12 | Keep "registered and refused: no supported API" (README) | Keep API exists for admins [11]; fidelity gaps [12] | **Correct the README.** Optionally add Keep as a source with a known-limits note. | Low |
| 13 | Restore writes files to local disk only (code) | Market sells in-place restore with permissions [33][51]; native restore does not reshare [31] | **Product decision.** Drive sharing and permissions are not captured today (code), so they cannot be restored later. Capture permissions now even if in-place restore comes later. | High (product) |
| 14 | Contacts sync token; Gmail history id | 7 day token expiry [10]; history at least one week [2] | **Keep.** Confirm the Contacts path handles `EXPIRED_SYNC_TOKEN` the way the Gmail path handles 404. Daily schedules sit well inside both windows. | Low |
| 15 | zlib compression | zstd in every modern engine reviewed [49][40] | Optional change. | Low |

**Synthetic scale test (2026-10-31).** The engine was run against fake Google clients with no Google calls. Details are in [scale/results.md](scale/results.md). It confirmed items 1, 2 and 4:
- *Item 1.* Killed runs restarted from zero, saved no fileset, and left the run record stuck at `running`.
- *Item 2.* A 1 GB Drive file peaked at 2,093 MB of memory, over the job's 2 GiB limit.
- *Item 4.* `run_due` skipped a job whose run had been killed 5 hours earlier.
- *Item 7.* 100 KiB blocks needed about 10 times as many index lookups as 1 MiB blocks. The single-threaded engine ran at about 34 MB/s locally, so 1 TiB would need more than 4 hours of local processing alone.

## Cross-dimension insights

- **Quota, timeout and checkpointing form one problem.** The API dimension sets throughput per user [1][8]. The platform dimension allows 168 hour tasks and multiple tasks [16]. The engine dimension shows that progress must be committed incrementally [39]. Any one fix alone does not make a large first backup succeed. All three together do.
- **Immutability and compaction pull against each other.** Locked retention [20] stops deletes. Compaction and retention pruning are deletes. The resolution, seen in other engines [44][45], is a time margin: never delete a volume younger than the retention period, and do deletes under a separate identity.
- **Restore fidelity is decided at backup time.** Native restore loses sharing [31], vendors sell keeping it [33], and the Drive change log handles permissions awkwardly [9]. Metadata bgb does not capture now cannot be restored later.
- **Drive egress may become a cost line.** The 1 TB per day threshold [8] means seeding a multi-terabyte domain will span days, and once charges start it may be billed. Seed pacing belongs in the design.

## Contrary evidence

The red team pass was off for this run. The strongest counter-argument found in the evidence is cost: CubeBackup's listed price of about USD 5 per user per year [34] (low confidence) sets a low bar for build versus buy. It is not checked here whether CubeBackup supports Cloud Storage natively or restores into Workspace.

## Recommendations

Feeds: architecture decisions and the client pilot gate.

1. **Before any client pilot, fix the blockers (items 1 to 5).** These are checkpointed, resumable runs; streaming downloads; locked retention in a separate backup project; an atomic lease; and 403 retries. Confidence: high. It rests on verified quota and limit claims [1][5][16][20] and on direct code observation.
2. **Run a scale test before claiming a capacity.** Use one real mailbox of 50,000 or more messages and one Drive with files over 2 GB and documents over 10 MB. Measure messages per minute against the 75 per minute ceiling derived from [1]. Confidence: medium, because the throughput figure is arithmetic on verified quotas, not a measurement.
3. **Capture Drive permissions and sharing metadata now.** Decide whether in-place restore is in scope before the first client. Confidence: medium, because the market evidence is vendor claims.
4. **Raise the default block size to 1 MiB, and store mail messages whole.** Confidence: medium. It rests on Duplicati's change [41] and borg's figures [40], not on a bgb benchmark.
5. **Correct the Keep statement in the README and REVIEW.md** [11]. Confidence: high.
6. **Record the no-application-encryption decision and its threat model** in the client-facing design. Confidence: medium.

## Open questions

- Does `files.download` export Workspace documents over 10 MB? Answer it by testing against a large document.
- Does `messages.get` with `format=raw` return label IDs and `internalDate`? If so, the extra metadata call (20 units) can be dropped. Check the API reference or test it.
- Can an admin back up every shared drive without being a member of each one? Neither `useDomainAdminAccess` file content access nor the alternative of impersonating one member per drive was researched.
- How are Drive egress charges priced, and when do they start? Watch the Drive API release notes for the 90 day notice [8].
- How do CubeBackup's storage targets and restore behaviour compare? Check its documentation, or run a trial.
- Calendar is not backed up by bgb or researched here. Several products cover it [34][51]. Decide whether it is in scope.

## Source appendix

| [n] | Supports | Publisher | Pub / page date | Accessed | Confidence |
|---|---|---|---|---|---|
| 1 | Gmail quotas and method costs | [Google Developers](https://developers.google.com/workspace/gmail/api/reference/quota) | 2026-10-16 | 2026-10-31 | high |
| 2 | Gmail history window, 404 | [Google Developers](https://developers.google.com/workspace/gmail/api/guides/sync) | 2026-09-15 | 2026-10-31 | high |
| 3 | Gmail batch limits | [Google Developers](https://developers.google.com/workspace/gmail/api/guides/batch) | 2026-09-10 | 2026-10-31 | high |
| 4 | Vault export API | [Google Developers](https://developers.google.com/workspace/vault/guides/exports) | 2026-09-03 | 2026-10-31 | high |
| 5 | Drive export 10 MB | [Google Developers](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export) | 2025-08-26 | 2026-10-31 | high |
| 6 | Drive files.download | [Google Developers](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/download) | 2025-08-26 | 2026-10-31 | medium |
| 7 | Export formats | [Google Developers](https://developers.google.com/workspace/drive/api/guides/ref-export-formats) | 2026-09-03 | 2026-10-31 | high |
| 8 | Drive quotas, egress threshold, charges | [Google Developers](https://developers.google.com/workspace/drive/api/guides/limits) | 2026-10-30 | 2026-10-31 | high |
| 9 | Drive change logs | [Google Developers](https://developers.google.com/workspace/drive/api/guides/about-changes) | 2026-09-03 | 2026-10-31 | medium |
| 10 | People sync token expiry | [Google Developers](https://developers.google.com/people/api/rest/v1/people.connections/list) | 2024-08-06 | 2026-10-31 | high |
| 11 | Keep API for admins | [Google Developers](https://developers.google.com/workspace/keep/api/guides) | 2026-09-03 | 2026-10-31 | high |
| 12 | Keep note fields | [Google Developers](https://developers.google.com/workspace/keep/api/reference/rest/v1/notes) | 2026-02-24 | 2026-10-31 | medium |
| 13 | Chat user-only read | [Google Developers](https://developers.google.com/workspace/chat/authenticate-authorize) | 2026-10-23 | 2026-10-31 | medium |
| 14 | Key creation blocked by default | [Google Cloud](https://docs.cloud.google.com/resource-manager/docs/secure-by-default-organizations) | 2026-10-26 | 2026-10-31 | high |
| 15 | DWD multi-party approval | [Workspace Updates](https://workspaceupdates.googleblog.com/2024/08/multi-party-approvals-for-domain-wide-delegation-actions.html) | 2024-08 | 2026-10-31 | medium |
| 16 | Cloud Run task timeout 168 h | [Google Cloud](https://docs.cloud.google.com/run/docs/configuring/task-timeout) | 2026-10-30 | 2026-10-31 | high |
| 17 | Scheduled jobs; no overlap control documented | [Google Cloud](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule) | 2026-10-30 | 2026-10-31 | medium |
| 18 | Community: overlap gap | [Reddit mirror](https://lr.us.psf.lt/r/googlecloud/comments/1ecnz50/cloud_run_jobs_stop_executions_from_running_in) | 2024-07 | 2026-10-31 | low |
| 19 | GCS soft delete | [Google Cloud](https://docs.cloud.google.com/storage/docs/soft-delete) | 2026-10-30 | 2026-10-31 | high |
| 20 | Bucket Lock | [Google Cloud](https://docs.cloud.google.com/storage/docs/bucket-lock) | 2026-10-30 | 2026-10-31 | high |
| 21 | Object Retention Lock | [Google Cloud](https://docs.cloud.google.com/storage/docs/object-lock) | 2026-10-30 | 2026-10-31 | high |
| 22 | Storage class minimums | [Google Cloud](https://docs.cloud.google.com/storage/docs/storage-classes) | 2026-10-30 | 2026-10-31 | high |
| 23 | Backup vault scope | [Google Cloud](https://docs.cloud.google.com/backup-disaster-recovery/docs/concepts/backup-vault) | 2026-10-26 | 2026-10-31 | high |
| 24 | Firestore pricing | [Firebase](https://firebase.google.com/docs/firestore/standard-edition) | 2026-10-28 | 2026-10-31 | high |
| 25 | Firestore best practices | [Google Cloud](https://docs.cloud.google.com/firestore/docs/best-practices) | 2026-10-28 | 2026-10-31 | high |
| 26 | Firestore quotas | [Google Cloud](https://docs.cloud.google.com/firestore/quotas) | 2026-10-28 | 2026-10-31 | high |
| 27 | Firestore PITR and backups | [Firebase](https://firebase.google.com/docs/firestore/pitr) | not captured | 2026-10-31 | medium |
| 28 | Keyless signJwt guidance | [Google Cloud](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys) | not captured | 2026-10-31 | medium |
| 29 | DWD risk, dedicated projects | [Workspace Admin Help](https://support.google.com/a/answer/14437356) | not captured | 2026-10-31 | medium |
| 30 | Vault is not a backup | [Google Workspace](https://knowledge.workspace.google.com/vault/getting-started/google-vault-faq) | 2026-10-26 | 2026-10-31 | high |
| 31 | Admin Drive restore limits | [Google Workspace](https://knowledge.workspace.google.com/admin/drive/recover-deleted-files-and-folders-for-drive-users) | 2026-10-26 | 2026-10-31 | high |
| 32 | Keepit coverage gaps | [Keepit](https://web03.keepit.com/help/google-workspace-category/google-workspace-backup-coverage) | 2026-06 | 2026-10-31 | high |
| 33 | Afi restore features | [Afi](https://afi.ai/google-workspace-backup) | undated | 2026-10-31 | medium |
| 34 | CubeBackup features and price | [CubeBackup](https://www.cubebackup.com/) | undated | 2026-10-31 | low |
| 35 | Veeam not pursuing Workspace | [Veeam forums](https://forums.veeam.com/viewtopic.php?p=504540) | undated | 2026-10-31 | medium |
| 36 | Commvault Workspace launch | [SourceSecurity](https://sourcesecurity.com/amp/news/commvault-cloud-backup-google-workspace-launched-co-12158-ga-co-1691762009-ga-co-1728458418-ga.1728460473.html) | 2024-10-09 | 2026-10-31 | medium |
| 37 | GYB restore failures | [GYB Google Group](https://groups.google.com/g/got-your-back/c/4X17MfxQSxY) | 2016 to 2024 | 2026-10-31 | medium |
| 38 | Docs export size issue | [Movebot docs](https://docs.movebot.io/platform-guides/google/performance-and-limits) | undated | 2026-10-31 | low |
| 39 | restic design, chunking, locks, encryption | [restic](https://restic.readthedocs.io/en/latest/100_references.html) | living doc | 2026-10-31 | high |
| 40 | Borg chunk sizes, index cost, compression | [BorgBackup](https://borgbackup.readthedocs.io/en/stable/internals/data-structures.html) | living doc | 2026-10-31 | high |
| 41 | Duplicati 100 KB to 1 MB | [Duplicati GitHub PR 4925](https://github.com/duplicati/duplicati/pull/4925) | 2024-04-21 | 2026-10-31 | high |
| 42 | Small block performance cliff | [Duplicati forum](https://forum.duplicati.com/t/default-block-size-has-changed/20709) | 2024 to 2025 | 2026-10-31 | medium |
| 43 | Duplicati dindex/recreate failure | [Duplicati forum](https://forum.duplicati.com/t/improve-performance-of-restore-from-total-crash/20680) | 2025-05 | 2026-10-31 | high |
| 44 | Kopia maintenance safety | [Kopia](https://kopia.io/docs/advanced/maintenance/) | 2026-04-07 | 2026-10-31 | high |
| 45 | Duplicacy fossil collection | [Duplicacy wiki](https://github.com/gilbertchen/duplicacy/wiki/Lock-Free-Deduplication) | 2021-09-08 | 2026-10-31 | high |
| 46 | restic check read-data | [restic](https://restic.readthedocs.io/en/stable/045_working_with_repos.html) | living doc | 2026-10-31 | high |
| 47 | CISA backup guidance | [CISA](https://www.cisa.gov/stopransomware/ransomware-guide) | 2023-09 | 2026-10-31 | medium |
| 48 | Kopia mandatory encryption | [Kopia](https://kopia.io/docs/features/) | 2026-03-20 | 2026-10-31 | high |
| 49 | restic zstd compression | [restic blog](https://restic.net/blog/2022-08-25/restic-0.14.0-released/) | 2022-08-25 | 2026-10-31 | high |
| 50 | Whole-file vs block dedup | [USENIX FAST '11](https://www.usenix.org/legacy/event/fast11/tech/full_papers/Meyer.pdf) | 2011 | 2026-10-31 | medium |
| 51 | Spanning coverage and restore | [Unitrends](https://unitrends.com/?p=65823) | undated | 2026-10-31 | medium |

## Staleness map

Computed with `recon_kit.py staleness`. Windows: limits and policy 1 month, pricing and availability 6 months, features 12 months, design 24 months.

| Claim | Class | Page date | Re-check by |
|---|---|---|---|
| [5] Drive export 10 MB | limits | 2025-08-26 | **stale now**: page older than window; re-read before relying on it |
| [41] Duplicati 1 MB default block | design | 2024-04-21 | **stale now**: confirm the current default |
| [1] Gmail quotas and costs | limits | 2026-10-16 | 2026-11-16 |
| [23] Backup vault supported workloads | limits | 2026-10-26 | 2026-11-26 |
| [8] Drive egress threshold and planned charges | policy | 2026-10-30 | 2026-11-30 |
| [16] Cloud Run 168 h timeout | limits | 2026-10-30 | 2026-11-30 |
| [11] Keep API availability | availability | 2026-09-03 | 2027-03-03 |
| [24] Firestore pricing | pricing | 2026-10-28 | 2027-04-28 |
| [34] CubeBackup price (undated; access date used) | pricing | 2026-10-31 | 2027-04-30 |
| [32] Keepit coverage | feature | 2026-06 | 2027-06-01 |

The two stale items are Drive export [5] and the Duplicati default [41]. The earliest scheduled re-check is the Gmail quota page on 2026-11-16. The Drive egress charge notice [8] is the item most likely to change the cost picture.
