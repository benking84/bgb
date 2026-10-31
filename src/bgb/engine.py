from __future__ import annotations

import logging
import os
import random
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from bgb.errors import BgbError, ConfigError, Conflict, IntegrityError, NotFound, Retained
from bgb.models import BlockRef, FileEntry, FileSet, Job, Run, Settings, SourceObject, VolumeRef
from bgb.retention import Stamp, filesets_to_delete
from bgb.util import now_iso, parse_time, safe_path
from bgb.volume import (
    VolumeWriter,
    blockset_id,
    compress,
    decode_payload,
    decompress,
    encode_blocks,
    encode_fileset,
    encode_index,
    sha256_hex,
)

log = logging.getLogger("bgb.engine")


def _object_name(prefix: str, job_id: str, kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    token = uuid.uuid4().hex[:8]
    head = prefix.strip("/")
    tail = f"{job_id}/{kind}/{stamp}-{token}.bgb"
    return f"{head}/{tail}" if head else tail


# A lease outlives a killed run by at most this long. Heartbeats renew it well before then.
LEASE_TTL = 30 * 60
HEARTBEAT = 60
# Unflushed progress is saved at least this often, so a killed run loses little work.
CHECKPOINT_SECONDS = 5 * 60
CHECKPOINT_ENTRIES = 1000
# The commit check holds reused block hashes in memory; above this it is skipped with a warning.
REUSED_CHECK_LIMIT = 500_000


@dataclass
class _RunContext:
    job_id: str
    writer: VolumeWriter
    stats: dict
    run: Run
    local_new: set[str] = field(default_factory=set)
    reused: set[str] = field(default_factory=set)
    pending: list[FileEntry] = field(default_factory=list)
    saved_at: float = field(default_factory=time.monotonic)


class Engine:
    """Backup, retention, compaction, verify, restore, and rebuild for one index and bucket.

    Every operation that changes stored data holds the job's lease in the index, so
    two Cloud Run executions never back up, compact, or rebuild the same job at once.
    ``min_object_age`` matches the bucket retention period: objects younger than that
    are not compacted or deleted, and expired volumes are swept once they are old enough.
    """

    def __init__(self, index, volumes, sources_for, *, prefix: str = "bgb", min_object_age: timedelta = timedelta(0)):
        self.index = index
        self.volumes = volumes
        self.sources_for = sources_for
        self.prefix = prefix
        self.min_object_age = min_object_age
        # Cloud Run retries of one execution share its name, so a retry can take over its own lease.
        self.holder = os.environ.get("CLOUD_RUN_EXECUTION") or f"local-{uuid.uuid4().hex}"
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._rng = random.SystemRandom()
        self._beats: dict[str, float] = {}

    def _lock(self, job_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(job_id, threading.Lock())

    def _settings(self) -> Settings:
        return self.index.get_settings()

    def _prefix(self, job_id: str) -> str:
        head = (self._settings().gcs_prefix or self.prefix).strip("/")
        return f"{head}/{job_id}/" if head else f"{job_id}/"

    @contextmanager
    def leased(self, job_id: str):
        """Hold the job's thread lock and its index lease for the duration of the block."""
        lock = self._lock(job_id)
        if not lock.acquire(blocking=False):
            raise Conflict("another operation on this job is running in this process")
        try:
            if not self.index.acquire_lease(job_id, self.holder, LEASE_TTL):
                raise Conflict("another execution holds this job's lease")
            self._beats[job_id] = time.monotonic()
            try:
                yield
            finally:
                self.index.release_lease(job_id, self.holder)
        finally:
            lock.release()

    def heartbeat(self, job_id: str) -> None:
        """Renew the lease. Raises if another execution took it, so this run stops writing."""
        if time.monotonic() - self._beats.get(job_id, 0) < HEARTBEAT:
            return
        if not self.index.acquire_lease(job_id, self.holder, LEASE_TTL):
            raise Conflict("this run lost the job's lease to another execution")
        self._beats[job_id] = time.monotonic()

    def run_backup(self, job_id: str, run_id: str | None = None, *, clock: datetime | None = None) -> Run:
        try:
            with self.leased(job_id):
                return self._run_backup(job_id, run_id, clock)
        except Conflict as exc:
            if run_id:
                self._fail_queued(run_id, str(exc))
            raise

    def _fail_queued(self, run_id: str, reason: str) -> None:
        try:
            run = self.index.get_run(run_id)
        except NotFound:
            return
        if run.status == "queued":
            run.status, run.phase, run.error, run.finished_at = "failed", "failed", reason, now_iso()
            self.index.update_run(run)

    def _close_abandoned(self, job_id: str, current: str) -> None:
        """Runs left queued or running by a killed execution. Only called while holding the lease."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LEASE_TTL)
        for row in self.index.list_runs(job_id):
            # A queued run may still be starting in another execution; only stale ones are abandoned.
            stale_queue = row.status == "queued" and (not row.started_at or parse_time(row.started_at) < cutoff)
            if row.id != current and (row.status == "running" or stale_queue):
                row.status, row.phase = "failed", "failed"
                row.error = "abandoned: the run stopped without finishing (timeout or crash). Its progress was kept."
                row.finished_at = row.finished_at or now_iso()
                self.index.update_run(row)

    def _run_backup(self, job_id: str, run_id: str | None, clock: datetime | None) -> Run:
        job = self.index.get_job(job_id)
        settings = self._settings()
        block_size = job.block_size or settings.block_size
        volume_size = job.volume_size or settings.volume_size
        if block_size < 16:
            raise ConfigError("block size must be at least 16 bytes")
        if volume_size < block_size:
            raise ConfigError("volume size must be at least the block size")
        if run_id:
            run = self.index.get_run(run_id)
        else:
            run = Run(
                id=uuid.uuid4().hex,
                job_id=job_id,
                status="running",
                phase="scan",
                started_at=now_iso(),
            )
            self.index.add_run(run)
        run.status = "running"
        run.phase = "scan"
        run.started_at = run.started_at or now_iso()
        run.error = None
        self.index.update_run(run)
        self._close_abandoned(job_id, run.id)
        stats: dict = {
            "files": 0,
            "bytes": 0,
            "blocks_new": 0,
            "blocks_reused": 0,
            "volumes": 0,
            "stored_bytes": 0,
            "files_unchanged": 0,
            "files_deleted": 0,
            "files_read": 0,
            "filesets_removed": 0,
            "volumes_rewritten": 0,
            "volumes_deleted": 0,
            "warnings": [],
        }
        try:
            log.info("backup start job=%s", job_id)
            sources = self.sources_for(job, settings)
            if not sources:
                raise ConfigError("job has no sources")
            previous: list[FileEntry] = []
            existing = self.index.list_filesets(job_id)
            if existing:
                previous = self.index.iter_entries(job_id, existing[0].id)
            # Files a killed run already stored. Their revisions match, so they are not read again.
            resumed = self.index.list_checkpoint(job_id)
            if resumed:
                merged = {entry.source_id: entry for entry in previous}
                merged.update({entry.source_id: entry for entry in resumed})
                previous = list(merged.values())
                stats["files_resumed"] = len(resumed)
            run.phase = "blocks"
            run.stats = stats
            self.index.update_run(run)
            ctx = _RunContext(job_id=job_id, writer=VolumeWriter(volume_size), stats=stats, run=run)
            entries, new_state = self._collect(job, sources, previous, block_size, ctx)
            self._flush(ctx)
            self._check_reused(ctx)
            stats["files"] = len(entries)
            run.phase = "fileset"
            run.stats = stats
            self.index.update_run(run)
            self._write_fileset(job, entries, stats)
            job.source_state = new_state
            job.updated_at = now_iso()
            self.index.upsert_job(job)
            self.index.clear_checkpoint(job_id)
            run.phase = "retention"
            self.index.update_run(run)
            removed = self.apply_retention(job, now=clock)
            stats["filesets_removed"] = len(removed)
            run.phase = "compact"
            self.index.update_run(run)
            stats.update(self.compact(job_id))
            stats["volumes_swept"] = self.sweep_expired(job_id)
            run.phase = "verify"
            run.stats = stats
            self.index.update_run(run)
            report = self.verify(job_id)
            stats["verify"] = report
            run.stats = stats
            run.status = "completed" if report["ok"] else "completed_with_warnings"
            run.phase = "done"
            log.info("backup done job=%s files=%s new_blocks=%s", job_id, stats["files"], stats["blocks_new"])
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.phase = "failed"
            run.stats = stats
            log.exception("backup failed job=%s", job_id)
            raise
        finally:
            run.finished_at = now_iso()
            self.index.update_run(run)
            if hasattr(self.index, "flush"):
                self.index.flush()
        return run

    def _collect(self, job, sources, previous, block_size, ctx: _RunContext):
        stats = ctx.stats
        prefixes = tuple(source.id_prefix for source in sources)
        by_id = {entry.source_id: entry for entry in previous}
        for entry in previous:
            if not entry.source_id.startswith(prefixes):
                stats["files_deleted"] += 1
        entries: list[FileEntry] = []
        new_state = dict(job.source_state or {})
        for source in sources:
            scan = source.scan(job)
            stats["warnings"].extend(scan.warnings)
            new_state[source.name] = scan.state
            owned = {sid: entry for sid, entry in by_id.items() if sid.startswith(source.id_prefix)}
            seen_scopes = set()
            for scope in scan.scopes:
                seen_scopes.add(scope.scope)
                prev_scope = {sid: entry for sid, entry in owned.items() if entry.scope == scope.scope}
                if scope.mode == "full":
                    seen: set[str] = set()
                    for obj in scope.objects:
                        if obj.source_id in seen:
                            continue
                        seen.add(obj.source_id)
                        entries.append(self._ingest(obj, prev_scope.get(obj.source_id), block_size, ctx))
                    stats["files_deleted"] += sum(1 for sid in prev_scope if sid not in seen)
                else:
                    upserts = {obj.source_id: obj for obj in scope.objects}
                    deleted = set(scope.deleted_ids)
                    stats["files_deleted"] += sum(1 for sid in deleted if sid in prev_scope)
                    for sid, old in prev_scope.items():
                        if sid in deleted:
                            continue
                        if sid in upserts:
                            entries.append(self._ingest(upserts.pop(sid), old, block_size, ctx))
                        else:
                            entries.append(old)
                            stats["files_unchanged"] += 1
                    for obj in upserts.values():
                        entries.append(self._ingest(obj, None, block_size, ctx))
            for sid, old in owned.items():
                if old.scope not in seen_scopes:
                    stats["files_deleted"] += 1
        return entries, new_state

    def _ingest(self, obj: SourceObject, old: FileEntry | None, block_size, ctx: _RunContext) -> FileEntry:
        job_id, writer, stats, run = ctx.job_id, ctx.writer, ctx.stats, ctx.run
        self.heartbeat(job_id)
        self._maybe_checkpoint(ctx)
        try:
            safe_path(obj.path)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if old and old.revision == obj.revision:
            stats["files_unchanged"] += 1
            return FileEntry(
                path=obj.path,
                source_id=obj.source_id,
                scope=obj.scope,
                size=old.size,
                mtime=obj.mtime or old.mtime,
                revision=old.revision,
                blockset_id=old.blockset_id,
                content_hash=old.content_hash,
                # Gmail fills labels only when it reads a body, so an unread message keeps the old ones.
                metadata=dict(obj.metadata) or dict(old.metadata),
            )
        if obj.opener is None:
            raise ConfigError(f"no content reader for {obj.path}")
        digest = sha256_hex  # local alias keeps the loop readable
        hasher_whole = __import__("hashlib").sha256()
        hashes: list[str] = []
        size = 0
        with obj.opener() as handle:
            while True:
                chunk = handle.read(block_size)
                if not chunk:
                    break
                if len(chunk) > block_size:
                    raise ConfigError(f"{obj.path} returned a read larger than the block size")
                hasher_whole.update(chunk)
                size += len(chunk)
                block_hash = digest(chunk)
                hashes.append(block_hash)
                self.heartbeat(job_id)
                if block_hash in ctx.local_new:
                    stats["blocks_reused"] += 1
                    continue
                if self.index.has_block(job_id, block_hash):
                    stats["blocks_reused"] += 1
                    if len(ctx.reused) < REUSED_CHECK_LIMIT:
                        ctx.reused.add(block_hash)
                    else:
                        stats["reused_check_skipped"] = True
                    continue
                writer.add(block_hash, chunk)
                ctx.local_new.add(block_hash)
                stats["blocks_new"] += 1
                if writer.full():
                    self._flush(ctx)
        stats["files_read"] += 1
        stats["bytes"] += size
        if stats["files_read"] % 20 == 0:
            run.stats = dict(stats)
            self.index.update_run(run)
        identifier = blockset_id(hashes)
        self.index.put_blockset(job_id, identifier, hashes)
        entry = FileEntry(
            path=obj.path,
            source_id=obj.source_id,
            scope=obj.scope,
            size=size,
            mtime=obj.mtime,
            revision=obj.revision,
            blockset_id=identifier,
            content_hash=hasher_whole.hexdigest(),
            metadata=dict(obj.metadata),
        )
        ctx.pending.append(entry)
        return entry

    def _maybe_checkpoint(self, ctx: _RunContext) -> None:
        if not ctx.pending:
            return
        if len(ctx.pending) < CHECKPOINT_ENTRIES and time.monotonic() - ctx.saved_at < CHECKPOINT_SECONDS:
            return
        self._flush(ctx)

    def _check_reused(self, ctx: _RunContext) -> None:
        """Refuse to commit a fileset whose reused blocks were deleted while this run was ingesting."""
        if not ctx.reused:
            return
        missing = self.index.missing_blocks(ctx.job_id, sorted(ctx.reused))
        if missing:
            raise IntegrityError(
                f"{len(missing)} reused blocks were deleted during this run; the fileset was not saved. Run the backup again."
            )

    def _flush(self, ctx: _RunContext) -> None:
        """Write pending blocks, then checkpoint the files whose blocks are now all stored."""
        if ctx.writer.pending():
            pairs = ctx.writer.take()
            volume = self._write_block_volume(ctx.job_id, pairs)
            for block_hash, data in pairs:
                self.index.put_block(ctx.job_id, BlockRef(hash=block_hash, size=len(data), volume_id=volume.id))
            ctx.stats["volumes"] += 1
            ctx.stats["stored_bytes"] += volume.size
        if ctx.pending:
            self.index.put_checkpoint(ctx.job_id, ctx.pending)
            ctx.pending = []
            ctx.run.stats = dict(ctx.stats)
            self.index.update_run(ctx.run)
        ctx.saved_at = time.monotonic()

    def _write_block_volume(self, job_id: str, pairs: list[tuple[str, bytes]]) -> VolumeRef:
        prefix = self._settings().gcs_prefix or self.prefix
        blob = compress(encode_blocks(pairs))
        name = _object_name(prefix, job_id, "dblock")
        self.volumes.put(name, blob)
        index_blob = compress(encode_index(name, pairs))
        index_name = _object_name(prefix, job_id, "dindex")
        self.volumes.put(index_name, index_blob)
        created = now_iso()
        block_volume = VolumeRef(
            id=uuid.uuid4().hex,
            name=name,
            kind="dblock",
            size=len(blob),
            hash=sha256_hex(blob),
            state="available",
            created_at=created,
            counterpart=index_name,
            block_count=len(pairs),
        )
        index_volume = VolumeRef(
            id=uuid.uuid4().hex,
            name=index_name,
            kind="dindex",
            size=len(index_blob),
            hash=sha256_hex(index_blob),
            state="available",
            created_at=created,
            counterpart=name,
            block_count=len(pairs),
        )
        self.index.put_volume(job_id, block_volume)
        self.index.put_volume(job_id, index_volume)
        return block_volume

    def _write_fileset(self, job: Job, entries: list[FileEntry], stats: dict) -> FileSet:
        fileset_id = uuid.uuid4().hex
        created = now_iso()
        body = []
        total = 0
        for entry in entries:
            total += entry.size
            row = entry.to_dict()
            row["hashes"] = self.index.get_blockset(job.id, entry.blockset_id)
            body.append(row)
        plain = encode_fileset(
            {"job_id": job.id, "fileset_id": fileset_id, "created_at": created},
            body,
        )
        blob = compress(plain)
        name = _object_name(self._settings().gcs_prefix or self.prefix, job.id, "dlist")
        self.volumes.put(name, blob)
        volume = VolumeRef(
            id=uuid.uuid4().hex,
            name=name,
            kind="dlist",
            size=len(blob),
            hash=sha256_hex(blob),
            state="available",
            created_at=created,
            fileset_id=fileset_id,
            block_count=len(entries),
        )
        self.index.put_volume(job.id, volume)
        fileset = FileSet(
            id=fileset_id,
            job_id=job.id,
            created_at=created,
            volume_id=volume.id,
            file_count=len(entries),
            bytes=total,
        )
        self.index.put_fileset(fileset, entries)
        stats["stored_bytes"] += volume.size
        return fileset

    def apply_retention(self, job: Job, *, now: datetime | None = None) -> list[str]:
        moment = now or datetime.now(timezone.utc)
        filesets = self.index.list_filesets(job.id)
        stamps = [Stamp(row.id, parse_time(row.created_at)) for row in filesets]
        delete_ids = filesets_to_delete(stamps, job.retention, moment)
        for fileset_id in delete_ids:
            fileset = self.index.get_fileset(job.id, fileset_id)
            try:
                volume = self.index.get_volume(job.id, fileset.volume_id)
            except NotFound:
                volume = None
            if volume is not None:
                self._retire(job.id, volume, moment)
            self.index.delete_fileset(job.id, fileset_id)
        return delete_ids

    def _old_enough(self, volume: VolumeRef, now: datetime) -> bool:
        if not self.min_object_age:
            return True
        return now - parse_time(volume.created_at) >= self.min_object_age

    def _retire(self, job_id: str, volume: VolumeRef, now: datetime) -> bool:
        """Delete a volume, or mark it expired if the bucket still retains it. True when deleted."""
        if self._old_enough(volume, now):
            try:
                self.volumes.delete(volume.name)
                self.index.delete_volume(job_id, volume.id)
                return True
            except Retained:
                pass
        volume.state = "expired"
        self.index.put_volume(job_id, volume)
        return False

    def sweep_expired(self, job_id: str, *, now: datetime | None = None) -> int:
        """Delete expired volumes whose retention period has passed."""
        moment = now or datetime.now(timezone.utc)
        removed = 0
        for volume in self.index.list_volumes(job_id):
            if volume.state == "expired" and self._old_enough(volume, moment):
                removed += int(self._retire(job_id, volume, moment))
        return removed

    def compact(self, job_id: str) -> dict:
        threshold = self._settings().compact_waste_threshold
        now = datetime.now(timezone.utc)
        live: set[str] = set()
        for fileset in self.index.list_filesets(job_id):
            for entry in self.index.iter_entries(job_id, fileset.id):
                live.update(self.index.get_blockset(job_id, entry.blockset_id))
        for entry in self.index.list_checkpoint(job_id):
            live.update(self.index.get_blockset(job_id, entry.blockset_id))
        rewritten = 0
        deleted = 0
        for volume in list(self.index.list_volumes(job_id)):
            if volume.kind != "dblock" or volume.state != "available":
                continue
            if not self._old_enough(volume, now):
                continue
            blocks = self.index.blocks_for_volume(job_id, volume.id)
            live_blocks = [block for block in blocks if block.hash in live]
            if blocks and live_blocks:
                waste = (len(blocks) - len(live_blocks)) / len(blocks)
                if waste < threshold:
                    continue
            if live_blocks:
                loaded = self._load_block_volume(job_id, volume.id)
                pairs = [(block.hash, loaded[block.hash]) for block in live_blocks]
                replacement = self._write_block_volume(job_id, pairs)
                for digest, data in pairs:
                    self.index.put_block(
                        job_id,
                        BlockRef(hash=digest, size=len(data), volume_id=replacement.id),
                        overwrite=True,
                    )
                rewritten += 1
            else:
                deleted += 1
            dead = [block.hash for block in blocks if block.hash not in live]
            self.index.delete_blocks(job_id, dead)
            self._delete_volume_pair(job_id, volume, now)
        return {"volumes_rewritten": rewritten, "volumes_deleted": deleted}

    def _delete_volume_pair(self, job_id: str, volume: VolumeRef, now: datetime) -> None:
        self._retire(job_id, volume, now)
        if not volume.counterpart:
            return
        other = self.index.get_volume_by_name(job_id, volume.counterpart)
        if other is not None:
            self._retire(job_id, other, now)
        else:
            try:
                self.volumes.delete(volume.counterpart)
            except Retained:
                pass

    def verify(self, job_id: str, *, full: bool = False, sample: int | None = None) -> dict:
        issues: list[str] = []
        every = self.index.list_volumes(job_id)
        volumes = [row for row in every if row.state == "available"]
        remote = set(self.volumes.list(self._prefix(job_id)))
        indexed = {row.name for row in volumes}
        missing = sorted(indexed - remote)
        extra = sorted(remote - {row.name for row in every})
        issues.extend(f"missing remote object {name}" for name in missing)
        dblocks = [row for row in volumes if row.kind == "dblock"]
        count = len(dblocks) if full else (self._settings().verify_samples if sample is None else sample)
        count = max(0, min(count, len(dblocks)))
        chosen = self._rng.sample(dblocks, count) if count else []
        for volume in chosen:
            try:
                blob = self.volumes.get(volume.name)
            except FileNotFoundError:
                issues.append(f"missing {volume.name}")
                continue
            if sha256_hex(blob) != volume.hash:
                issues.append(f"hash mismatch for {volume.name}")
                continue
            try:
                payload = decode_payload(decompress(blob))
            except (IntegrityError, BgbError) as exc:
                issues.append(f"{volume.name}: {exc}")
                continue
            for digest, data in payload.blocks.items():
                try:
                    ref = self.index.get_block(job_id, digest)
                except NotFound:
                    issues.append(f"block {digest} is not in the index")
                    continue
                if ref.volume_id != volume.id or ref.size != len(data):
                    issues.append(f"block {digest} does not match its index record")
        return {
            "ok": not issues,
            "issues": issues,
            "missing": missing,
            "extra": extra,
            "checked_volumes": len(chosen),
            "remote_objects": len(remote),
        }

    def prune_orphans(self, job_id: str) -> list[str]:
        """Delete stored objects the index does not know. Under the lease, so no upload is in flight."""
        with self.leased(job_id):
            indexed = {row.name for row in self.index.list_volumes(job_id)}
            removed = []
            for name in self.volumes.list(self._prefix(job_id)):
                if name not in indexed:
                    try:
                        self.volumes.delete(name)
                    except Retained:
                        continue
                    removed.append(name)
            return removed

    def read_file(self, job_id: str, fileset_id: str, path: str) -> tuple[bytes, FileEntry]:
        entry = self.index.get_entry(job_id, fileset_id, path)
        return self._read_entry(job_id, entry, {}), entry

    def _read_entry(self, job_id: str, entry: FileEntry, cache: dict) -> bytes:
        hashes = self.index.get_blockset(job_id, entry.blockset_id)
        out = bytearray()
        for digest in hashes:
            block = self.index.get_block(job_id, digest)
            if block.volume_id not in cache:
                cache[block.volume_id] = self._load_block_volume(job_id, block.volume_id)
            chunk = cache[block.volume_id].get(digest)
            if chunk is None:
                raise IntegrityError(f"block {digest} is missing from its volume")
            out += chunk
        data = bytes(out)
        if sha256_hex(data) != entry.content_hash:
            raise IntegrityError(f"restored {entry.path} does not match its content hash")
        return data

    def _load_block_volume(self, job_id: str, volume_id: str) -> dict[str, bytes]:
        volume = self.index.get_volume(job_id, volume_id)
        blob = self.volumes.get(volume.name)
        if sha256_hex(blob) != volume.hash:
            raise IntegrityError(f"volume {volume.name} hash mismatch")
        payload = decode_payload(decompress(blob))
        if payload.type != "blocks":
            raise IntegrityError(f"{volume.name} is not a block volume")
        return payload.blocks

    def rebuild(self, job_id: str) -> dict:
        with self.leased(job_id):
            return self._rebuild(job_id)

    def _rebuild(self, job_id: str) -> dict:
        names = self.volumes.list(self._prefix(job_id))
        decoded = []
        for name in names:
            blob = self.volumes.get(name)
            payload = decode_payload(decompress(blob))
            decoded.append((name, blob, payload))
        self.index.clear_backup_data(job_id)
        filesets = 0
        for name, blob, payload in decoded:
            if payload.type != "blocks":
                continue
            volume = self._remember(job_id, name, blob, "dblock", len(payload.blocks))
            for digest, data in payload.blocks.items():
                self.index.put_block(
                    job_id,
                    BlockRef(hash=digest, size=len(data), volume_id=volume.id),
                    overwrite=True,
                )
        for name, blob, payload in decoded:
            if payload.type != "fileset":
                continue
            volume = self._remember(job_id, name, blob, "dlist", len(payload.entries))
            entries: list[FileEntry] = []
            for row in payload.entries:
                hashes = list(row.get("hashes") or [])
                if blockset_id(hashes) != row["blockset_id"]:
                    raise IntegrityError(f"fileset hash list for {row.get('path')} does not match its blockset id")
                self.index.put_blockset(job_id, row["blockset_id"], hashes)
                entries.append(
                    FileEntry(
                        path=row["path"],
                        source_id=row["source_id"],
                        scope=row["scope"],
                        size=row["size"],
                        mtime=row.get("mtime"),
                        revision=row["revision"],
                        blockset_id=row["blockset_id"],
                        content_hash=row["content_hash"],
                        metadata=row.get("metadata") or {},
                    )
                )
            fileset_id = payload.header.get("fileset_id") or uuid.uuid4().hex
            self.index.put_fileset(
                FileSet(
                    id=fileset_id,
                    job_id=job_id,
                    created_at=payload.header.get("created_at") or now_iso(),
                    volume_id=volume.id,
                    file_count=len(entries),
                    bytes=sum(entry.size for entry in entries),
                ),
                entries,
            )
            filesets += 1
        for name, blob, payload in decoded:
            if payload.type == "index":
                self._remember(job_id, name, blob, "dindex", len(payload.header.get("entries") or []))
        if hasattr(self.index, "flush"):
            self.index.flush()
        return {"filesets": filesets, "objects": len(decoded)}

    def _remember(self, job_id: str, name: str, blob: bytes, kind: str, count: int) -> VolumeRef:
        volume = VolumeRef(
            id=uuid.uuid4().hex,
            name=name,
            kind=kind,
            size=len(blob),
            hash=sha256_hex(blob),
            state="available",
            created_at=now_iso(),
            block_count=count,
        )
        self.index.put_volume(job_id, volume)
        return volume


def busy(run: Run, *, horizon: timedelta = timedelta(hours=24)) -> bool:
    if run.status not in {"queued", "running"}:
        return False
    if not run.started_at:
        return True
    return datetime.now(timezone.utc) - parse_time(run.started_at) < horizon
