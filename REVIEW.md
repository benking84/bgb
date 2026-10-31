# Design

bgb backs up Gmail, Google Drive (including shared drives), and Google Contacts for a Workspace domain. Bytes go to Cloud Storage. Job config, run history, and the block index go to Firestore. Workspace credentials go to Secret Manager. The only deployment is Terraform onto an existing GCP project: Cloud Run for the UI and API, a Cloud Run job for backup runs, and Cloud Scheduler to start that job.

## Backup model

A run is a snapshot of the selected sources. Each object is a stream of fixed-size blocks (default 100 KiB). A block is identified by the SHA-256 of its bytes and stored once per job, so identical content across people and sources is not uploaded again. An unchanged revision is not read again.

Blocks are packed into volumes:

- `dblock` holds the block bytes
- `dindex` lists the hashes in that volume
- `dlist` is the fileset: path, revision, and the ordered block hashes needed to rebuild each file

Volume payloads are zlib-compressed. Each stored object is hashed, and that hash is recorded in the index. Each block is checked against its hash when a volume is read, and a restored file is checked against the hash stored with the fileset. Cloud Storage and Firestore supply encryption at rest. There is no application-level cipher. A Terraform variable can set a Cloud KMS key on the backup bucket. Left empty, the bucket uses Google-managed encryption.

Retention runs after a successful snapshot and always keeps the newest version. A job can keep a number of versions, a maximum age, or a bucket policy such as `1W:1D,4W:1W,12M:1M` (daily for a week, weekly for four weeks, monthly for twelve months). Months are 30 days and years are 365 days. Compaction rewrites a volume when at least 25% of its blocks are no longer referenced. Verify compares the bucket listing to the index and downloads sample volumes to recheck hashes. `bgb rebuild` reconstructs the index from the volumes, so the index is a cache of remote state.

## Concurrency, resume, and retention

Every operation that changes stored data (backup, retention, compaction, prune, rebuild, delete) holds the job's lease, a Firestore document taken in a transaction and renewed every minute. Without it, a second execution could compact away blocks that a running backup had just deduplicated against, and the running backup would then commit a fileset pointing at missing blocks. As a second guard, a run checks that every block it reused still exists before it saves the fileset. A killed run's lease expires within 30 minutes.

A run saves a checkpoint each time it writes a volume, and at least every 5 minutes: the file entries whose blocks are all stored. The next run merges the checkpoint into the previous fileset, so files already stored are not read again. Compaction counts checkpointed blocks as live.

The bucket's retention period is passed to the engine. Compaction skips volumes younger than that, and volumes released by retention are marked expired and deleted by a later run once they are old enough.

The destination only needs put, get, list, and delete. Production uses Cloud Storage. Local development uses a directory of files and a JSON index that implement the same operations.

## Firestore

Jobs, settings, runs, fileset summaries, file entries, block lists, and the block index are Firestore documents. A block's document id is its hash, so the dedup check is one get. Block lists are sharded at 400 hashes so a large file stays under the 1 MiB document limit.

Two workloads fit poorly, and they are still stored in Firestore:

- A fileset is a full snapshot, so each version writes one document per file even when the body did not change. Compaction has to read every remaining entry to learn which blocks are still referenced. Firestore has no joins.
- A backup is larger than one transaction (500 writes). A crash can upload a volume before the index records it. The volumes themselves are the recoverable copy. `bgb rebuild` reads them back. It currently downloads every block volume and holds them in memory, so it suits small jobs only; rebuilding from the dindex and dlist volumes alone is the planned fix.

If a domain outgrows that, keep jobs, runs, settings, and fileset summaries in Firestore, and move the block hash index and fileset entries to Cloud SQL so compaction is a query. Listing the bucket and downloading volumes to discover what is already stored would defeat the index.

## Sources

Gmail, Drive, and Contacts share one plugin interface: a scan returns a full listing or an incremental change set, and the engine turns that into blocks. Gmail uses the history id after the first scan. Drive backs up each user's My Drive, and each shared drive once as the admin. Docs, Sheets, Slides, and Drawings are exported. Forms, shortcuts, and other Docs types are skipped. Contacts stores one JSON object per person and follows the People API sync token.

Google Keep is registered and refused. Google's Keep API is open to admins through domain-wide delegation, but it omits labels, colours, reminders, and pinned or archived state, so a restore from it would lose them.

Authentication is a service account with domain-wide delegation, or an OAuth refresh token for a single user. On Cloud Run the job and the UI sign the delegation JWT as `bgb-delegate`, an account with no Google Cloud roles, so a JSON key is optional.

## Scope

The service backs up Workspace data onto this GCP project. It does not copy local disks, and it does not write to any store other than Cloud Storage. Scheduling is a UTC cron expression because Cloud Scheduler is the clock. Volumes are held in memory while they are packed, so a volume is capped at 128 MiB (the default is 50 MiB).
