from __future__ import annotations

import logging
import random
import threading
import uuid
from datetime import datetime, timedelta, timezone

from bgb.errors import BgbError, ConfigError, Conflict, IntegrityError, NotFound
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


class Engine:
    def __init__(self, index, volumes, sources_for, *, prefix: str = "bgb"):
        self.index = index
        self.volumes = volumes
        self.sources_for = sources_for
        self.prefix = prefix
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._rng = random.SystemRandom()

    def _lock(self, job_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(job_id, threading.Lock())

    def _settings(self) -> Settings:
        return self.index.get_settings()

    def _prefix(self, job_id: str) -> str:
        head = (self._settings().gcs_prefix or self.prefix).strip("/")
        return f"{head}/{job_id}/" if head else f"{job_id}/"

    def run_backup(self, job_id: str, run_id: str | None = None, *, clock: datetime | None = None) -> Run:
        lock = self._lock(job_id)
        if not lock.acquire(blocking=False):
            raise Conflict("a backup for this job is already running")
        try:
            return self._run_backup(job_id, run_id, clock)
        finally:
            lock.release()

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
            run.phase = "blocks"
            run.stats = stats
            self.index.update_run(run)
            writer = VolumeWriter(volume_size)
            local_new: set[str] = set()
            entries, new_state = self._collect(
                job, sources, previous, block_size, writer, local_new, stats, run
            )
            self._flush(job_id, writer, stats)
            stats["files"] = len(entries)
            run.phase = "fileset"
            run.stats = stats
            self.index.update_run(run)
            self._write_fileset(job, entries, stats)
            job.source_state = new_state
            job.updated_at = now_iso()
            self.index.upsert_job(job)
            run.phase = "retention"
            self.index.update_run(run)
            removed = self.apply_retention(job, now=clock)
            stats["filesets_removed"] = len(removed)
            run.phase = "compact"
            self.index.update_run(run)
            stats.update(self.compact(job_id))
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

    def _collect(self, job, sources, previous, block_size, writer, local_new, stats, run):
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
                        entries.append(
                            self._ingest(job.id, obj, prev_scope.get(obj.source_id), block_size, writer, local_new, stats, run)
                        )
                    stats["files_deleted"] += sum(1 for sid in prev_scope if sid not in seen)
                else:
                    upserts = {obj.source_id: obj for obj in scope.objects}
                    deleted = set(scope.deleted_ids)
                    stats["files_deleted"] += sum(1 for sid in deleted if sid in prev_scope)
                    for sid, old in prev_scope.items():
                        if sid in deleted:
                            continue
                        if sid in upserts:
                            entries.append(
                                self._ingest(job.id, upserts.pop(sid), old, block_size, writer, local_new, stats, run)
                            )
                        else:
                            entries.append(old)
                            stats["files_unchanged"] += 1
                    for obj in upserts.values():
                        entries.append(self._ingest(job.id, obj, None, block_size, writer, local_new, stats, run))
            for sid, old in owned.items():
                if old.scope not in seen_scopes:
                    stats["files_deleted"] += 1
        return entries, new_state

    def _ingest(self, job_id, obj: SourceObject, old: FileEntry | None, block_size, writer, local_new, stats, run) -> FileEntry:
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
                metadata=dict(obj.metadata),
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
                if block_hash in local_new or self.index.has_block(job_id, block_hash):
                    stats["blocks_reused"] += 1
                    continue
                writer.add(block_hash, chunk)
                local_new.add(block_hash)
                stats["blocks_new"] += 1
                if writer.full():
                    self._flush(job_id, writer, stats)
        stats["files_read"] += 1
        stats["bytes"] += size
        if stats["files_read"] % 20 == 0:
            run.stats = dict(stats)
            self.index.update_run(run)
        identifier = blockset_id(hashes)
        self.index.put_blockset(job_id, identifier, hashes)
        return FileEntry(
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

    def _flush(self, job_id: str, writer: VolumeWriter, stats: dict) -> None:
        if not writer.pending():
            return
        pairs = writer.take()
        volume = self._write_block_volume(job_id, pairs)
        for block_hash, data in pairs:
            self.index.put_block(job_id, BlockRef(hash=block_hash, size=len(data), volume_id=volume.id))
        stats["volumes"] += 1
        stats["stored_bytes"] += volume.size

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
                self.volumes.delete(volume.name)
                self.index.delete_volume(job.id, volume.id)
            self.index.delete_fileset(job.id, fileset_id)
        return delete_ids

    def compact(self, job_id: str) -> dict:
        threshold = self._settings().compact_waste_threshold
        live: set[str] = set()
        for fileset in self.index.list_filesets(job_id):
            for entry in self.index.iter_entries(job_id, fileset.id):
                live.update(self.index.get_blockset(job_id, entry.blockset_id))
        rewritten = 0
        deleted = 0
        for volume in list(self.index.list_volumes(job_id)):
            if volume.kind != "dblock":
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
            self._delete_volume_pair(job_id, volume)
        return {"volumes_rewritten": rewritten, "volumes_deleted": deleted}

    def _delete_volume_pair(self, job_id: str, volume: VolumeRef) -> None:
        self.volumes.delete(volume.name)
        self.index.delete_volume(job_id, volume.id)
        if not volume.counterpart:
            return
        other = self.index.get_volume_by_name(job_id, volume.counterpart)
        self.volumes.delete(volume.counterpart)
        if other is not None:
            self.index.delete_volume(job_id, other.id)

    def verify(self, job_id: str, *, full: bool = False, sample: int | None = None) -> dict:
        issues: list[str] = []
        volumes = [row for row in self.index.list_volumes(job_id) if row.state == "available"]
        remote = set(self.volumes.list(self._prefix(job_id)))
        indexed = {row.name for row in volumes}
        missing = sorted(indexed - remote)
        extra = sorted(remote - indexed)
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
        indexed = {row.name for row in self.index.list_volumes(job_id)}
        removed = []
        for name in self.volumes.list(self._prefix(job_id)):
            if name not in indexed:
                self.volumes.delete(name)
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
