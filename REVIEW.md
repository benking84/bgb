# What bgb keeps from Duplicati

Duplicati (https://github.com/duplicati/duplicati) is a C# backup client. This note is the cut list for bgb, which backs up Google Workspace onto Google Cloud and nothing else. It is new Python and TypeScript. It does not vendor or translate the C# sources.

## How Duplicati is put together

The design premises are in the project docs: a backup is a snapshot, files are streams of fixed-size blocks, a block is stored once, blocks are packed into volumes, volumes are compressed and then encrypted, and the destination only needs GET, PUT, LIST, and DELETE. A local database (SQLite) is a cache of that remote state so a later backup does not download volumes to find out what is already stored. The database can be rebuilt from the remote volumes.

The engine in `Duplicati/Library/Main` splits streams into blocks (`StreamBlockSplitter`, `DataBlockProcessor`), writes `dblock` volumes, a small `dindex` for each, and a `dlist` fileset that records how to reconstruct every file. Retention (`keep-time`, `keep-versions`, or `retention-policy`, including the smart default `1W:1D,4W:1W,12M:1M`) runs after a successful backup and never deletes the last version unless asked. Compaction rewrites volumes that are mostly unreferenced. A sample of remote volumes is downloaded and checked. Restore hashes the rebuilt file.

The server (`Duplicati/Server` plus `Library/RestAPI`) stores jobs, schedules, and settings in its own SQLite file and hosts the web UI and API in-process. Schedules are timezone-aware; timestamps inside the backup are UTC. Storage backends are a separate plugin set (S3, B2, FTP, SFTP, WebDAV, local disk, Dropbox, Google Drive as a *destination*, OneDrive, Azure, and others). Sources are local files, with Windows VSS and USN journal support. There is a tray icon, installers, and images for many platforms.

## Kept

- Fixed-size block dedup, content addressed by SHA-256. Identical blocks across users and sources in one job are stored once. A later snapshot does not re-upload a block the index already has, and an unchanged revision is not even read again.
- Volumes. `dblock` holds block bytes, `dindex` is the hash list for that volume, `dlist` is the fileset (path, revision, ordered block hashes). Objects are compressed (zlib) and then encrypted (AES-256-GCM). GCM replaces Duplicati's zip-AES: one authenticated blob, no native 7-zip dependency.
- Every successful run is a full snapshot of the selected sources. Storage is incremental because of dedup. There is no full-plus-incremental chain to walk at restore time.
- Retention with the same three modes, including the smart bucket policy. The newest version is always kept. Months are 30 days and years are 365, not calendar months.
- Compaction when a volume's unreferenced-block ratio crosses a threshold (default 25%).
- Verification: the remote listing is compared to the index, and sample volumes are decrypted and hashed. Restore checks the file hash.
- Rebuild of the index from the encrypted volumes, which is the property that makes the index a cache.
- A server that holds job config, run history, and a schedule, and exposes an HTTP API plus a web UI. Cloud Scheduler is the clock (UTC cron). A Cloud Run job runs `bgb run-due` or one job id. "Run now" from the UI starts that job when `BGB_CLOUD_RUN_JOB` is set, and runs in-process otherwise.

## Removed, and why

- Every storage backend except Cloud Storage. The GET/PUT/LIST/DELETE surface is still there (`VolumeStore`), with a local directory implementation for development.
- Microsoft 365, OneDrive, SharePoint, Azure, and all Windows-specific code (VSS, USN, services, tray icon, installers).
- Local disk, S3, B2, FTP, SFTP, WebDAV, Dropbox, and Google Drive as a *destination*. Drive is a source.
- Desktop apps, Debian/Windows/Synology packages, and any container image other than the Cloud Run image.
- SQLite, both the per-backup block database and the server database. See Firestore below.
- GPG, 7z, speed limits, pause/resume, usage reporting, and partial backups. A bgb snapshot is complete or the run is failed.
- Filesystem filters, symlink policy, and OS snapshots. Selection is "which Workspace sources and which users."

## Firestore

Jobs, settings, run history, fileset summaries, file entries, blocksets, and the block index are stored in Firestore. Block documents use the hash as the id, which matches the hot path (one get per block to decide whether to upload). Block lists are sharded at 400 hashes so a large file stays under the 1 MiB document limit.

Firestore is a poor fit for two parts of Duplicati's SQLite database, and those limits are real:

- A fileset is a full snapshot. One document per file per version means a nightly run over a large domain rewrites a document per message even when the body did not change. Compact has to stream every remaining entry to learn which blocks are still referenced. SQLite does that with a join. Firestore does not have joins, and a backup is far too large for one transaction (500 writes).
- A crash can upload a volume before the index records it. The encrypted `dlist` and `dblock` headers are the recoverable copy. `bgb rebuild` reconstructs the index from them. That is weaker atomicity than SQLite's transactions.

bgb still uses Firestore for those records, as requested. If a domain outgrows it, keep jobs, runs, settings, and fileset summaries in Firestore, and move the block hash index and fileset entries to Cloud SQL (Postgres) so compaction is a query. Do not replace the index with "list the bucket and download volumes." That is the cost Duplicati's local database exists to avoid.

## Sources

Gmail and Drive are implemented, including shared drives read once as the admin (or the first user), Docs/Sheets/Slides/Drawings exported, and incremental cursors (Gmail history id, Drive change token). Contacts is a real plugin on the same interface, behind Gmail and Drive. Google Keep is registered and refused: there is no supported Workspace API for it. Takeout is not a live source.

Authentication is a service account with domain-wide delegation, or an OAuth refresh token for a single user. The Cloud Run runtime identity can sign JWTs without a key if that service account is the one authorized in the Admin console. A JSON key in Secret Manager is the other option.
