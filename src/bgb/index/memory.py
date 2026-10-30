from __future__ import annotations

import json
import threading
from pathlib import Path

from bgb.errors import NotFound
from bgb.models import BlockRef, FileEntry, FileSet, Job, Run, Settings, VolumeRef
from bgb.util import from_dict


class MemoryIndex:
    """In-process index used by tests and as the base of the local JSON index."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.runs: dict[str, Run] = {}
        self.filesets: dict[tuple[str, str], FileSet] = {}
        self.entries: dict[tuple[str, str], list[FileEntry]] = {}
        self.blocks: dict[tuple[str, str], BlockRef] = {}
        self.by_volume: dict[tuple[str, str], set[str]] = {}
        self.blocksets: dict[tuple[str, str], list[str]] = {}
        self.volumes: dict[tuple[str, str], VolumeRef] = {}
        self.settings = Settings()
        self._lock = threading.RLock()

    def flush(self) -> None:
        return None

    def upsert_job(self, job: Job) -> None:
        with self._lock:
            self.jobs[job.id] = job

    def get_job(self, job_id: str) -> Job:
        with self._lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise NotFound(f"job {job_id} not found")
        return job

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def delete_job(self, job_id: str) -> None:
        with self._lock:
            self.jobs.pop(job_id, None)
            self.clear_backup_data(job_id)
            for run_id, run in list(self.runs.items()):
                if run.job_id == job_id:
                    self.runs.pop(run_id, None)

    def add_run(self, run: Run) -> None:
        with self._lock:
            self.runs[run.id] = run

    def update_run(self, run: Run) -> None:
        with self._lock:
            self.runs[run.id] = run

    def get_run(self, run_id: str) -> Run:
        with self._lock:
            run = self.runs.get(run_id)
        if run is None:
            raise NotFound(f"run {run_id} not found")
        return run

    def list_runs(self, job_id: str) -> list[Run]:
        with self._lock:
            rows = [run for run in self.runs.values() if run.job_id == job_id]
        return sorted(rows, key=lambda run: run.started_at or "", reverse=True)

    def put_fileset(self, fileset: FileSet, entries: list[FileEntry]) -> None:
        with self._lock:
            self.filesets[(fileset.job_id, fileset.id)] = fileset
            self.entries[(fileset.job_id, fileset.id)] = list(entries)

    def list_filesets(self, job_id: str) -> list[FileSet]:
        with self._lock:
            rows = [row for (owner, _), row in self.filesets.items() if owner == job_id]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    def get_fileset(self, job_id: str, fileset_id: str) -> FileSet:
        with self._lock:
            row = self.filesets.get((job_id, fileset_id))
        if row is None:
            raise NotFound(f"fileset {fileset_id} not found")
        return row

    def list_entries(
        self,
        job_id: str,
        fileset_id: str,
        *,
        prefix: str = "",
        cursor: str = "",
        limit: int = 200,
    ) -> tuple[list[FileEntry], str]:
        with self._lock:
            rows = list(self.entries.get((job_id, fileset_id), []))
        rows = [row for row in rows if row.path.startswith(prefix) and (not cursor or row.path > cursor)]
        rows.sort(key=lambda row: row.path)
        page = rows[:limit]
        next_cursor = page[-1].path if len(rows) > limit and page else ""
        return page, next_cursor

    def iter_entries(self, job_id: str, fileset_id: str) -> list[FileEntry]:
        with self._lock:
            return list(self.entries.get((job_id, fileset_id), []))

    def get_entry(self, job_id: str, fileset_id: str, path: str) -> FileEntry:
        with self._lock:
            for row in self.entries.get((job_id, fileset_id), []):
                if row.path == path:
                    return row
        raise NotFound(f"file {path} is not in this version")

    def delete_fileset(self, job_id: str, fileset_id: str) -> None:
        with self._lock:
            self.filesets.pop((job_id, fileset_id), None)
            self.entries.pop((job_id, fileset_id), None)

    def has_block(self, job_id: str, digest: str) -> bool:
        with self._lock:
            return (job_id, digest) in self.blocks

    def get_block(self, job_id: str, digest: str) -> BlockRef:
        with self._lock:
            row = self.blocks.get((job_id, digest))
        if row is None:
            raise NotFound(f"block {digest} not found")
        return row

    def put_block(self, job_id: str, block: BlockRef, *, overwrite: bool = False) -> bool:
        with self._lock:
            key = (job_id, block.hash)
            existing = self.blocks.get(key)
            if existing and not overwrite:
                return False
            if existing and existing.volume_id != block.volume_id:
                self.by_volume.get((job_id, existing.volume_id), set()).discard(block.hash)
            self.blocks[key] = block
            self.by_volume.setdefault((job_id, block.volume_id), set()).add(block.hash)
            return True

    def blocks_for_volume(self, job_id: str, volume_id: str) -> list[BlockRef]:
        with self._lock:
            hashes = self.by_volume.get((job_id, volume_id), set())
            return [self.blocks[(job_id, digest)] for digest in hashes if (job_id, digest) in self.blocks]

    def delete_blocks(self, job_id: str, hashes: list[str]) -> None:
        with self._lock:
            for digest in hashes:
                row = self.blocks.pop((job_id, digest), None)
                if row:
                    self.by_volume.get((job_id, row.volume_id), set()).discard(digest)

    def count_blocks(self, job_id: str) -> int:
        with self._lock:
            return sum(1 for owner, _ in self.blocks if owner == job_id)

    def put_blockset(self, job_id: str, blockset_id: str, hashes: list[str]) -> None:
        with self._lock:
            self.blocksets[(job_id, blockset_id)] = list(hashes)

    def get_blockset(self, job_id: str, blockset_id: str) -> list[str]:
        with self._lock:
            row = self.blocksets.get((job_id, blockset_id))
        if row is None:
            raise NotFound(f"blockset {blockset_id} not found")
        return list(row)

    def put_volume(self, job_id: str, volume: VolumeRef) -> None:
        with self._lock:
            self.volumes[(job_id, volume.id)] = volume

    def get_volume(self, job_id: str, volume_id: str) -> VolumeRef:
        with self._lock:
            row = self.volumes.get((job_id, volume_id))
        if row is None:
            raise NotFound(f"volume {volume_id} not found")
        return row

    def get_volume_by_name(self, job_id: str, name: str) -> VolumeRef | None:
        with self._lock:
            for (owner, _), row in self.volumes.items():
                if owner == job_id and row.name == name:
                    return row
        return None

    def list_volumes(self, job_id: str) -> list[VolumeRef]:
        with self._lock:
            return [row for (owner, _), row in self.volumes.items() if owner == job_id]

    def delete_volume(self, job_id: str, volume_id: str) -> None:
        with self._lock:
            self.volumes.pop((job_id, volume_id), None)
            self.by_volume.pop((job_id, volume_id), None)

    def clear_backup_data(self, job_id: str) -> None:
        with self._lock:
            self.filesets = {key: value for key, value in self.filesets.items() if key[0] != job_id}
            self.entries = {key: value for key, value in self.entries.items() if key[0] != job_id}
            self.blocks = {key: value for key, value in self.blocks.items() if key[0] != job_id}
            self.by_volume = {key: value for key, value in self.by_volume.items() if key[0] != job_id}
            self.blocksets = {key: value for key, value in self.blocksets.items() if key[0] != job_id}
            self.volumes = {key: value for key, value in self.volumes.items() if key[0] != job_id}

    def get_settings(self) -> Settings:
        with self._lock:
            return self.settings

    def save_settings(self, settings: Settings) -> None:
        with self._lock:
            self.settings = settings


class FileIndex(MemoryIndex):
    """JSON snapshot of MemoryIndex for local dev. Production uses FirestoreIndex."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        if path.exists():
            self._load()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "settings": self.settings.to_dict(),
                "jobs": [job.to_dict() for job in self.jobs.values()],
                "runs": [run.to_dict() for run in self.runs.values()],
                "filesets": [row.to_dict() for row in self.filesets.values()],
                "entries": {
                    f"{job_id}/{fileset_id}": [entry.to_dict() for entry in rows]
                    for (job_id, fileset_id), rows in self.entries.items()
                },
                "blocks": [dict(block.to_dict(), job_id=job_id) for (job_id, _), block in self.blocks.items()],
                "blocksets": [
                    {"job_id": job_id, "id": blockset_id, "hashes": hashes}
                    for (job_id, blockset_id), hashes in self.blocksets.items()
                ],
                "volumes": [dict(volume.to_dict(), job_id=job_id) for (job_id, _), volume in self.volumes.items()],
            }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self.path)

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.settings = from_dict(Settings, payload.get("settings") or {})
        for row in payload.get("jobs") or []:
            self.jobs[row["id"]] = from_dict(Job, row)
        for row in payload.get("runs") or []:
            self.runs[row["id"]] = from_dict(Run, row)
        for row in payload.get("filesets") or []:
            fileset = from_dict(FileSet, row)
            self.filesets[(fileset.job_id, fileset.id)] = fileset
        for key, rows in (payload.get("entries") or {}).items():
            job_id, fileset_id = key.split("/", 1)
            self.entries[(job_id, fileset_id)] = [from_dict(FileEntry, row) for row in rows]
        for row in payload.get("blocks") or []:
            job_id = row["job_id"]
            block = from_dict(BlockRef, row)
            self.blocks[(job_id, block.hash)] = block
            self.by_volume.setdefault((job_id, block.volume_id), set()).add(block.hash)
        for row in payload.get("blocksets") or []:
            self.blocksets[(row["job_id"], row["id"])] = list(row["hashes"])
        for row in payload.get("volumes") or []:
            volume = from_dict(VolumeRef, row)
            self.volumes[(row["job_id"], volume.id)] = volume
