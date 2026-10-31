# Digest d3-gcp-r1-1: Google Cloud building blocks for a Workspace backup service

Status: draft for review. Accessed 2026-10-31. Retrieval was through a summarising fetch tool, so the wording of each claim is paraphrased and exact figures should be spot checked before client use. Many docs now redirect from cloud.google.com to docs.cloud.google.com.

## Claims table

| # | Claim | Source URL | Publisher | Page updated | Accessed | Confidence | Class |
|---|---|---|---|---|---|---|---|
| 1 | Cloud Run job task timeout defaults to 10 minutes and can be set up to 168 hours (7 days) for non GPU tasks; GPU tasks max 12 hours (preview) | https://docs.cloud.google.com/run/docs/configuring/task-timeout | Google Cloud | 2026-10-30 | 2026-10-31 | high | limits |
| 2 | The task timeout applies to each attempt of a task, not the task overall; Google recommends enabling retries for long running tasks. Max retry count not stated on this page | same as 1 | Google Cloud | 2026-10-30 | 2026-10-31 | high (behavior), n/a (max retries) | behavior |
| 3 | Cloud Run job parallelism limits tasks running in parallel within one execution, not across separate executions of the same job | https://cloud.google.com/run/docs/configuring/parallelism | Google Cloud | not captured | 2026-10-31 | medium (seen via search snippet) | behavior |
| 4 | Cloud Scheduler triggers a job by authenticated POST to the jobs:run endpoint; the scheduling doc says nothing about overlapping executions or how to prevent them | https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule | Google Cloud | 2026-10-30 | 2026-10-31 | high (absence on that page) | behavior |
| 5 | No official mechanism found to make Cloud Run reject a new execution while one is running; community suggestions are an in-job lock (Firestore/GCS lease) or a Cloud Tasks queue with max concurrent dispatches 1 | https://lr.us.psf.lt/r/googlecloud/comments/1ecnz50/cloud_run_jobs_stop_executions_from_running_in | Reddit mirror (community) | 2024-07 | 2026-10-31 | low | guidance |
| 6 | GCS soft delete: default 7 days, configurable 7 to 90 days, can be disabled by setting 0; soft deleted objects cannot be read or overwritten, only listed or restored, and cannot be permanently deleted before retention ends | https://docs.cloud.google.com/storage/docs/soft-delete | Google Cloud | 2026-10-30 | 2026-10-31 | high | limits |
| 7 | Soft deleted objects are billed storage until retention ends; deleting before the class minimum duration incurs early deletion charges (except Standard); restored objects always return as Standard class | same as 6 | Google Cloud | 2026-10-30 | 2026-10-31 | high | pricing |
| 8 | Soft delete is described as a layer after Bucket Lock / Object Retention Lock; restoring a soft deleted bucket via CLI/JSON API restores only an empty bucket, objects restored separately; on project deletion, soft deleted buckets kept for shorter of retention or project recovery window | same as 6 | Google Cloud | 2026-10-30 | 2026-10-31 | high | behavior |
| 9 | Bucket retention policy blocks delete/replace until object age exceeds the period (403 retentionPolicyNotMet); max 100 years; a locked policy cannot be removed or shortened (only increased), locking is irreversible; bucket cannot be deleted until all objects meet retention; lock places a lien blocking project deletion | https://docs.cloud.google.com/storage/docs/bucket-lock | Google Cloud | 2026-10-30 | 2026-10-31 | high | behavior |
| 10 | Lifecycle rules can still delete objects in a locked bucket, but only after the retention period is met | same as 9 | Google Cloud | 2026-10-30 | 2026-10-31 | high | behavior |
| 11 | Object Retention Lock sets per object retain-until with Unlocked (GOVERNANCE, removable by authorised users) or Locked (COMPLIANCE, cannot be reduced or removed) mode; up to 100 years; can be enabled on existing buckets only via console and cannot be disabled once enabled; applies a best effort lien on projects.delete; if both bucket and object retention apply, both must be satisfied | https://docs.cloud.google.com/storage/docs/object-lock | Google Cloud | 2026-10-30 | 2026-10-31 | high | behavior |
| 12 | Minimum storage durations: Standard none, Nearline 30 d, Coldline 90 d, Archive 365 d; Nearline/Coldline/Archive have retrieval fees | https://docs.cloud.google.com/storage/docs/storage-classes | Google Cloud | 2026-10-30 | 2026-10-31 | high | limits/pricing |
| 13 | Autoclass manages class transitions automatically; soft deleted objects are excluded from Autoclass transitions and management fees | https://docs.cloud.google.com/storage/docs/storage-classes ; soft-delete page | Google Cloud | 2026-10-30 | 2026-10-31 | high | behavior |
| 14 | Backup vault: Google managed, regional, immutable and indelible storage; enforced minimum retention 1 day to 99 years; backups cannot be deleted before retention by the admin, any user or Google; minimum retention can be permanently locked; from 1 Nov 2026 a project lien is applied to projects with enforced retention vaults | https://docs.cloud.google.com/backup-disaster-recovery/docs/concepts/backup-vault | Google Cloud | 2026-10-26 | 2026-10-31 | high | behavior |
| 15 | Backup vault supported workloads listed: Compute Engine instances and disks, Filestore, Cloud SQL, AlloyDB (console); VMware Engine, Oracle, SQL Server (appliance). Cloud Storage, Firestore, Google Workspace and arbitrary app data are not listed | same as 14 | Google Cloud | 2026-10-26 | 2026-10-31 | high (list), medium (absence implies unsupported) | limits |
| 16 | Backup vault access restriction setting (project / org / unrestricted) is permanent once chosen; centralised (admin project) and decentralised models documented | same as 14 | Google Cloud | 2026-10-26 | 2026-10-31 | high | guidance |
| 17 | Firestore Standard edition: $0.03 per 100k reads, $0.09 per 100k writes, $0.01 per 100k deletes (us-central1); daily free tier 50k reads, 20k writes, 20k deletes; index storage is billed | https://firebase.google.com/docs/firestore/standard-edition | Google (Firebase) | 2026-10-28 | 2026-10-31 | high | pricing |
| 18 | Derived: 100 M new index documents at $0.09/100k writes is about USD 90 in write ops (us-central1), excluding storage, index entries and deletes. Storage per GiB-month price not retrieved | arithmetic on 17 | n/a | n/a | 2026-10-31 | medium | pricing |
| 19 | 500/50/5 rule: start at max 500 ops/s to a new collection and increase by 50% every 5 minutes; avoid high rates on lexicographically close documents; monotonically increasing IDs cause hotspots; automatic IDs use a scatter algorithm and should not hotspot | https://docs.cloud.google.com/firestore/docs/best-practices | Google Cloud | 2026-10-28 | 2026-10-31 | high | guidance |
| 20 | Indexing a sequentially increasing field (e.g. timestamp) caps the collection at 500 writes/s; exempting it from indexing removes that cap. Single document write rate not fixed, depends on workload | same as 19 | Google Cloud | 2026-10-28 | 2026-10-31 | high | limits |
| 21 | Firestore max document size 1 MiB; max API request size 10 MiB; transaction time limit 270 s with 60 s idle expiry; 40,000 index entries per document; 8 MiB sum of index entry sizes per document; 500 field transformations per document per commit. The quotas page does not list a 500 writes per transaction/batch limit | https://docs.cloud.google.com/firestore/quotas | Google Cloud | 2026-10-28 | 2026-10-31 | high | limits |
| 22 | Firestore PITR: 7 day window at 1 minute granularity when enabled (1 hour when disabled); scheduled backups daily or weekly with max retention 14 weeks; for longer retention, export to Cloud Storage; restore from backup cheaper than from PITR | https://firebase.google.com/docs/firestore/pitr ; https://docs.cloud.google.com/firestore/native/docs/backups | Google | not captured (search snippets) | 2026-10-31 | medium | limits |
| 23 | Google says service account keys are not needed for domain wide delegation; keyless flow: workload authenticates as attached SA, builds JWT with sub = user, calls IAM Credentials signJwt, exchanges at OAuth2 token endpoint. Requires iam.serviceAccounts.signJwt (Service Account Token Creator); JWT exp at most 12 h ahead | https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys ; https://support.google.com/a/answer/14437356 | Google Cloud / Google Workspace Admin Help | not captured | 2026-10-31 | medium (search summary, pages not opened) | guidance |
| 24 | DWD is high risk (can impersonate any user incl. super admins); Google recommends hosting DWD service accounts in dedicated projects and limiting who can grant access | https://support.google.com/a/answer/14437356 | Google Workspace Admin Help | not captured | 2026-10-31 | medium | guidance |

## Implications for the decision (analysis, not sourced fact)

- A backup writer SA with storage.objects.delete can still destroy data unless a bucket retention policy (locked) or Locked mode Object Retention is in place; soft delete alone can be turned off (retention 0) by anyone with bucket update permission, so it is a recovery aid, not an immutability control. Whether reducing soft delete retention affects already soft deleted objects was not verified.
- Retention lock conflicts with compaction/garbage collection of shared dedup blocks: blocks cannot be deleted until retention expires, and rewrites in Nearline/Coldline/Archive incur early deletion charges; soft delete adds billed storage on top.
- Backup and DR vaults do not cover GCS objects, Firestore, or Workspace per the listed workloads, so the immutability story must be built on GCS retention plus project/IAM separation.
- Firestore write cost for a hash index is small; the operational risks are ramp up (500/50/5), sequential IDs/indexed timestamps, and index storage. Hash based IDs are presumably well distributed but Google does not explicitly endorse custom random IDs (load test).
- Firestore native backups max 14 weeks; the index itself needs exports to GCS (ideally into the locked bucket) for longer retention, or the index must be rebuildable from GCS object metadata.
- Overlap protection for scheduled jobs must be built (lease/lock) because no platform control was found.

## Leads worth chasing

- Cloud Run jobs limits page (max tasks per execution, max parallelism, memory/CPU per task, max retries 0 to 10 believed) at docs.cloud.google.com/run/docs/configuring/... and quotas page.
- Cloud Run "Manage job executions" and "jobs retries and checkpoints" pages for overlap behaviour.
- Google Cloud blog / Architecture Center on ransomware resilient backups (separate project, separate org, VPC-SC, Backup vault) not retrieved this run.
- Firestore pricing page (cloud.google.com/firestore/pricing) for storage per GiB-month, PITR and backup storage, restore pricing; fetch returned a redirect loop.
- Firestore batched writes / transactions docs to confirm current per commit write limit.
- IAM Credentials API quotas (signJwt requests per minute) on the API quotas page or console.
- GCS pricing page for early deletion calculation and whether objects.rewrite / overwrite counts as delete; Autoclass doc for management fee and early deletion exemption.
- Whether soft delete retention changes apply retroactively, and the IAM permission needed to change it (storage.buckets.update), to frame the compromised SA threat.
- Comparative costs of Bigtable / Spanner / Cloud SQL for a hash index (not researched).

## Looked for and could not find

- Official Cloud Run statement on whether concurrent executions of the same job are allowed or can be blocked (none found; only community answers).
- Max retries for Cloud Run jobs (not on the task timeout page).
- Firestore storage, PITR, backup and restore prices (pricing page not retrievable).
- A current 500 writes per transaction limit in the Firestore quotas page (not listed; only 500 field transforms per document).
- signJwt quotas.
- Google ransomware backup guidance document (not retrieved within budget).
- Any Backup and DR support for Cloud Storage, Firestore or Workspace data (not listed on the vault concept page).
