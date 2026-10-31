# bgb synthetic scale test

**Status: draft for review.** Run 2026-10-31 on an Apple M5 Mac against commit `e3b0171`.

## Scope

This test runs bgb's real engine, `GmailSource` and `DriveSource` against fake API clients that count calls. It makes no Google or GCP calls, so it measures the engine's behaviour, not Google's latency or throttling.

- **Quota time** is arithmetic on Google's published Gmail quota (6,000 units per minute per user; 20 units for metadata, 60 for raw; verified 2026-10-31).
- **Timeout kills** are simulated by an exception the engine does not catch, which is the same effect as Cloud Run killing the process.
- **To rerun:**

```bash
PYTHONPATH=. .venv/bin/python _bmad-output/planning-artifacts/research/technical-google-workspace-backup-architecture-rev-2026-10-31/scale/scale_test.py resume
```

The same script also takes `memory SIZE_MB`, `blocks` and `busy`.

## Results

### 1. A killed first backup does not progress (confirms blocker 1)

The mailbox had 5,000 messages of 75 KiB. Runs 1 and 2 were killed after 2,000 raw downloads. Run 3 was allowed to finish.

| Run | Outcome | Metadata calls | Raw downloads | Quota time at 6,000 units/min | Run record left as | Filesets saved |
|---|---|---|---|---|---|---|
| 1 | killed | 5,000 | 2,000 | 36.7 min | `running` | 0 |
| 2 | killed | 5,000 | 2,000 | 36.7 min | `running` | 0 |
| 3 | completed | 5,000 | 5,000 | 66.7 min | `completed` | 1 |

- **Each run starts over.** Run 2 repeated every call run 1 made. Only the block uploads were saved, because dedup matched them. Nothing records which messages are already done, so a mailbox that needs longer than the timeout never completes.
- **Every run spends quota on the full mailbox first.** Each run fetches metadata for all 5,000 messages before it downloads any message body.
- **Ceiling.** The cap is 75 messages per minute per user, so 100,000 messages take at least 22.2 hours. The job timeout is 4 hours.

### 2. Whole-file buffering exceeds the job's memory (confirms blocker 2)

Each case backed up one Drive file. The fake client returns the bytes directly. The real client buffers the download as well, so real peaks will be higher.

| File size | Peak memory | Peak divided by file size |
|---|---|---|
| 256 MB | 1,043 MB | 4.1 |
| 1,024 MB | 2,093 MB | 2.0 |

The backup job's limit is 2 GiB (2,048 MiB). A single file of about 1 GB is enough to exceed it, and when it does Cloud Run kills the whole run.

### 3. Block count and index round trips (supports item 7)

The test backed up 200 MB of unique data.

| Block size | Index lookups | Lookups per TiB | Hours per TiB if each lookup takes 10 ms | Local engine speed |
|---|---|---|---|---|
| 100 KiB | 2,050 | about 10.7 million | 29.9 | 33.5 MB/s |
| 1 MiB | 200 | about 1.0 million | 2.9 | 34.9 MB/s |

- **The 10 ms figure is an assumption.** It is a placeholder for one Firestore read round trip, which was not measured.
- **Lookup count.** Lookups scale with block count, so 1 MiB blocks need about a tenth as many.
- **Engine speed alone breaks the timeout.** The engine runs on one thread at about 34 MB/s here. 1 TiB would take about 8.5 hours of hashing and compression alone, before any API or network time, which is already past the 4 hour timeout.

### 4. A killed run blocks the schedule (confirms item 4)

Setup: a run killed 5 hours ago is still marked `running`. `run_due` skipped the job. The busy guard expires after 24 hours, while the job times out after 4. So after a timeout kill, that job's schedule stops for about the next 20 hours.

## What this does not cover

These need a real Workspace tenant and GCP project:
- real API latency and throttling
- Firestore round trip time
- Cloud Storage upload speed
- memory on Cloud Run's Linux runtime, which reports differently from macOS
- `files.download` behaviour for documents over 10 MB

## Index loss and corruption (integrity_test.py)

Run on 2026-10-31. The tests use the same fakes as above and make no Google calls. To rerun one, pass `rebuild`, `compaction`, `race` or `rebuildcost 400` to `scale/integrity_test.py`.

| Scenario | Result |
|---|---|
| All backup records deleted from the index, then `rebuild` | 90 of 90 file versions restored before; 0 after the loss; 90 after the rebuild. Full verify passes. |
| Retention and compaction over 6 runs, then index wiped and rebuilt | 42 of 42 restored after the rebuild. Compaction rewrote its index volumes correctly, so Duplicati's dindex bug is not present. |
| Two overlapping executions: one compacts while the other is reusing blocks | **Silent data loss.** Run 3 reports `completed` and a full verify passes, but restoring the reused file fails with `block ... not found`. |
| Rebuild cost, 400 MB backup | The rebuild read the whole 401 MB bucket. The index (dindex) and fileset (dlist) volumes alone are 0.31 MB. Peak memory rose by about 520 MB, because every decoded volume is held in memory. |

What these show:
- **The storage format is sound.** The bucket alone is enough to rebuild the index, and compaction keeps it that way.
- **The real corruption path is overlap.** Two executions running at once can commit a backup that references deleted blocks. `verify` checks the bucket against the index, not each backup against its blocks, so it misses this.
- **Rebuild only works at small scale.** It downloads every data volume rather than reading the index volumes, and holds them all in memory. That is Duplicati's slow recreate path, plus a memory ceiling. It also clears the index before it starts.

## After the blocker fixes (same harness, 2026-10-31)

`scale_test_before.py` keeps the original harness. `scale_test.py` and `integrity_test.py` now use the new client contract: one raw fetch per message, and Drive downloads as streams.

| Check | Before | After |
|---|---|---|
| Gmail quota per new message | 80 units (metadata plus raw) | 60 units (raw only); ceiling 100 messages per minute per user, so 100,000 messages take 16.7 h |
| Downloads repeated by a run after a kill | all of them | only work since the last checkpoint, at most about one volume. 5,000 messages took 6,269 downloads over 3 runs, two of them killed |
| Peak memory, one Drive file | 1 GB file: 2,093 MB | 256 MB: 389 MB; 1 GB: 443 MB; 4 GB: 506 MB |
| Run blocked after a killed run | for up to 24 h | until its lease expires (at most 30 min); the next run closes the killed run as abandoned |
| Overlapping executions compacting | silent loss; verify passed | second execution refused by the lease; restore succeeds. A run whose reused blocks vanish now fails instead of saving |
| Rebuild after index loss, and after compaction | 90 of 90; 42 of 42 | unchanged: 90 of 90; 42 of 42 |
| Rebuild cost | reads every volume and holds it in memory | **not fixed**: same |

Unit tests: 27 pass, including 7 new ones in `tests/test_resilience.py`.
