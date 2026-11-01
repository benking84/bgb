from __future__ import annotations

import time
from typing import Any

from bgb.errors import NotFound
from bgb.models import BlockRef, FileEntry, FileSet, Job, Run, Settings, VolumeRef
from bgb.util import from_dict

_PART = 400
_BATCH = 400


class FirestoreIndex:
    """Block index, job config, runs, and fileset entries in Cloud Firestore.

    Block hashes are document ids so the dedup lookup is a single get. Block
    lists are sharded at 400 hashes so a large file stays under the 1 MiB
    document limit. See REVIEW.md for the scale limits of per-file documents.
    """

    def __init__(self, client: Any):
        self.db = client

    def flush(self) -> None:
        return None

    def _job(self, job_id: str):
        return self.db.collection("jobs").document(job_id)

    def upsert_job(self, job: Job) -> None:
        self._job(job.id).set(job.to_dict())

    def get_job(self, job_id: str) -> Job:
        snap = self._job(job_id).get()
        if not snap.exists:
            raise NotFound(f"job {job_id} not found")
        return from_dict(Job, snap.to_dict() or {})

    def list_jobs(self) -> list[Job]:
        rows = [
            from_dict(Job, snap.to_dict() or {})
            for snap in self.db.collection("jobs").stream()
        ]
        return sorted(rows, key=lambda job: job.created_at, reverse=True)

    def delete_job(self, job_id: str) -> None:
        self.clear_backup_data(job_id)
        self._delete_query(self.db.collection("runs").where("job_id", "==", job_id))
        self._job(job_id).delete()

    def add_run(self, run: Run) -> None:
        # Top-level so a run id is a direct get. A collection-group query would
        # need an extra composite index and is not worth it for this lookup.
        self.db.collection("runs").document(run.id).set(run.to_dict())

    def update_run(self, run: Run) -> None:
        self.add_run(run)

    def get_run(self, run_id: str) -> Run:
        snap = self.db.collection("runs").document(run_id).get()
        if not snap.exists:
            raise NotFound(f"run {run_id} not found")
        return from_dict(Run, snap.to_dict() or {})

    def list_runs(self, job_id: str) -> list[Run]:
        rows = [
            from_dict(Run, snap.to_dict() or {})
            for snap in self.db.collection("runs")
            .where("job_id", "==", job_id)
            .stream()
        ]
        return sorted(rows, key=lambda run: run.started_at or "", reverse=True)

    def put_fileset(self, fileset: FileSet, entries: list[FileEntry]) -> None:
        ref = self._job(fileset.job_id).collection("filesets").document(fileset.id)
        ref.set(fileset.to_dict())
        col = ref.collection("entries")
        self._delete_collection(col)
        self._batched_set(
            col, [(_entry_id(entry), entry.to_dict()) for entry in entries]
        )

    def list_filesets(self, job_id: str) -> list[FileSet]:
        rows = [
            from_dict(FileSet, snap.to_dict() or {})
            for snap in self._job(job_id).collection("filesets").stream()
        ]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    def get_fileset(self, job_id: str, fileset_id: str) -> FileSet:
        snap = self._job(job_id).collection("filesets").document(fileset_id).get()
        if not snap.exists:
            raise NotFound(f"fileset {fileset_id} not found")
        return from_dict(FileSet, snap.to_dict() or {})

    def list_entries(
        self,
        job_id: str,
        fileset_id: str,
        *,
        prefix: str = "",
        cursor: str = "",
        limit: int = 200,
    ) -> tuple[list[FileEntry], str]:
        query = self._entries(job_id, fileset_id).order_by("path")
        if prefix:
            query = query.where("path", ">=", prefix).where(
                "path", "<", prefix + "\uf8ff"
            )
        if cursor:
            query = query.where("path", ">", cursor)
        rows = [
            from_dict(FileEntry, snap.to_dict() or {})
            for snap in query.limit(limit + 1).stream()
        ]
        page = rows[:limit]
        next_cursor = page[-1].path if len(rows) > limit and page else ""
        return page, next_cursor

    def iter_entries(self, job_id: str, fileset_id: str) -> list[FileEntry]:
        return [
            from_dict(FileEntry, snap.to_dict() or {})
            for snap in self._entries(job_id, fileset_id).stream()
        ]

    def get_entry(self, job_id: str, fileset_id: str, path: str) -> FileEntry:
        matches = list(
            self._entries(job_id, fileset_id)
            .where("path", "==", path)
            .limit(1)
            .stream()
        )
        if not matches:
            raise NotFound(f"file {path} is not in this version")
        return from_dict(FileEntry, matches[0].to_dict() or {})

    def delete_fileset(self, job_id: str, fileset_id: str) -> None:
        ref = self._job(job_id).collection("filesets").document(fileset_id)
        self._delete_collection(ref.collection("entries"))
        ref.delete()

    def has_block(self, job_id: str, digest: str) -> bool:
        return self._job(job_id).collection("blocks").document(digest).get().exists

    def get_block(self, job_id: str, digest: str) -> BlockRef:
        snap = self._job(job_id).collection("blocks").document(digest).get()
        if not snap.exists:
            raise NotFound(f"block {digest} not found")
        return from_dict(BlockRef, snap.to_dict() or {})

    def put_block(
        self, job_id: str, block: BlockRef, *, overwrite: bool = False
    ) -> bool:
        ref = self._job(job_id).collection("blocks").document(block.hash)
        if overwrite:
            ref.set(block.to_dict())
            return True
        try:
            ref.create(block.to_dict())
            return True
        except Exception as exc:
            if exc.__class__.__name__ in {"AlreadyExists", "Conflict"}:
                return False
            raise

    def blocks_for_volume(self, job_id: str, volume_id: str) -> list[BlockRef]:
        query = (
            self._job(job_id).collection("blocks").where("volume_id", "==", volume_id)
        )
        return [from_dict(BlockRef, snap.to_dict() or {}) for snap in query.stream()]

    def delete_blocks(self, job_id: str, hashes: list[str]) -> None:
        col = self._job(job_id).collection("blocks")
        batch = self.db.batch()
        count = 0
        for digest in hashes:
            batch.delete(col.document(digest))
            count += 1
            if count == _BATCH:
                batch.commit()
                batch = self.db.batch()
                count = 0
        if count:
            batch.commit()

    def count_blocks(self, job_id: str) -> int:
        count = 0
        for _ in self._job(job_id).collection("blocks").select([]).stream():
            count += 1
        return count

    def put_blockset(self, job_id: str, blockset_id: str, hashes: list[str]) -> None:
        ref = self._job(job_id).collection("blocksets").document(blockset_id)
        parts = [
            hashes[index : index + _PART] for index in range(0, len(hashes), _PART)
        ] or [[]]
        ref.set({"id": blockset_id, "count": len(hashes), "parts": len(parts)})
        self._batched_set(
            ref.collection("parts"),
            [(str(index), {"hashes": part}) for index, part in enumerate(parts)],
        )

    def get_blockset(self, job_id: str, blockset_id: str) -> list[str]:
        ref = self._job(job_id).collection("blocksets").document(blockset_id)
        snap = ref.get()
        if not snap.exists:
            raise NotFound(f"blockset {blockset_id} not found")
        hashes: list[str] = []
        parts = list(ref.collection("parts").stream())
        parts.sort(key=lambda item: int(item.id))
        for part in parts:
            hashes.extend((part.to_dict() or {}).get("hashes") or [])
        return hashes

    def put_volume(self, job_id: str, volume: VolumeRef) -> None:
        self._job(job_id).collection("volumes").document(volume.id).set(
            volume.to_dict()
        )

    def get_volume(self, job_id: str, volume_id: str) -> VolumeRef:
        snap = self._job(job_id).collection("volumes").document(volume_id).get()
        if not snap.exists:
            raise NotFound(f"volume {volume_id} not found")
        return from_dict(VolumeRef, snap.to_dict() or {})

    def get_volume_by_name(self, job_id: str, name: str) -> VolumeRef | None:
        matches = list(
            self._job(job_id)
            .collection("volumes")
            .where("name", "==", name)
            .limit(1)
            .stream()
        )
        if not matches:
            return None
        return from_dict(VolumeRef, matches[0].to_dict() or {})

    def list_volumes(self, job_id: str) -> list[VolumeRef]:
        return [
            from_dict(VolumeRef, snap.to_dict() or {})
            for snap in self._job(job_id).collection("volumes").stream()
        ]

    def delete_volume(self, job_id: str, volume_id: str) -> None:
        self._job(job_id).collection("volumes").document(volume_id).delete()

    def clear_backup_data(self, job_id: str) -> None:
        job = self._job(job_id)
        for snap in job.collection("filesets").stream():
            self._delete_collection(snap.reference.collection("entries"))
            snap.reference.delete()
        for snap in job.collection("blocksets").stream():
            self._delete_collection(snap.reference.collection("parts"))
            snap.reference.delete()
        self._delete_collection(job.collection("blocks"))
        self._delete_collection(job.collection("volumes"))
        self._delete_collection(job.collection("checkpoint"))

    def missing_blocks(self, job_id: str, hashes: list[str]) -> list[str]:
        col = self._job(job_id).collection("blocks")
        missing: list[str] = []
        for start in range(0, len(hashes), 300):
            chunk = hashes[start : start + 300]
            found = {
                snap.id
                for snap in self.db.get_all([col.document(digest) for digest in chunk])
                if snap.exists
            }
            missing.extend(digest for digest in chunk if digest not in found)
        return missing

    def put_checkpoint(self, job_id: str, entries: list[FileEntry]) -> None:
        col = self._job(job_id).collection("checkpoint")
        self._batched_set(
            col, [(_entry_id(entry), entry.to_dict()) for entry in entries]
        )

    def list_checkpoint(self, job_id: str) -> list[FileEntry]:
        return [
            from_dict(FileEntry, snap.to_dict() or {})
            for snap in self._job(job_id).collection("checkpoint").stream()
        ]

    def clear_checkpoint(self, job_id: str) -> None:
        self._delete_collection(self._job(job_id).collection("checkpoint"))

    def acquire_lease(self, job_id: str, holder: str, ttl: float) -> bool:
        """Take or renew the job's lease in a transaction, so two executions cannot both hold it."""
        from google.cloud import firestore

        ref = self.db.collection("leases").document(job_id)

        @firestore.transactional
        def take(transaction) -> bool:
            snap = ref.get(transaction=transaction)
            now = time.time()
            current = snap.to_dict() if snap.exists else None
            if (
                current
                and current.get("holder") != holder
                and float(current.get("expires") or 0) > now
            ):
                return False
            transaction.set(
                ref, {"job_id": job_id, "holder": holder, "expires": now + ttl}
            )
            return True

        return take(self.db.transaction())

    def release_lease(self, job_id: str, holder: str) -> None:
        from google.cloud import firestore

        ref = self.db.collection("leases").document(job_id)

        @firestore.transactional
        def drop(transaction) -> None:
            snap = ref.get(transaction=transaction)
            if snap.exists and (snap.to_dict() or {}).get("holder") == holder:
                transaction.delete(ref)

        drop(self.db.transaction())

    def lease_holder(self, job_id: str) -> str | None:
        snap = self.db.collection("leases").document(job_id).get()
        current = snap.to_dict() if snap.exists else None
        if current and float(current.get("expires") or 0) > time.time():
            return current.get("holder")
        return None

    def get_settings(self) -> Settings:
        snap = self.db.collection("settings").document("global").get()
        if not snap.exists:
            return Settings()
        return from_dict(Settings, snap.to_dict() or {})

    def save_settings(self, settings: Settings) -> None:
        self.db.collection("settings").document("global").set(settings.to_dict())

    def _entries(self, job_id: str, fileset_id: str):
        return (
            self._job(job_id)
            .collection("filesets")
            .document(fileset_id)
            .collection("entries")
        )

    def _batched_set(self, collection, rows: list[tuple[str, dict]]) -> None:
        batch = self.db.batch()
        count = 0
        for doc_id, payload in rows:
            batch.set(collection.document(doc_id), payload)
            count += 1
            if count == _BATCH:
                batch.commit()
                batch = self.db.batch()
                count = 0
        if count:
            batch.commit()

    def _delete_collection(self, collection) -> None:
        self._delete_query(collection)

    def _delete_query(self, query) -> None:
        while True:
            docs = list(query.limit(_BATCH).stream())
            if not docs:
                return
            batch = self.db.batch()
            for doc in docs:
                batch.delete(doc.reference)
            batch.commit()


def _entry_id(entry: FileEntry) -> str:
    import hashlib

    return hashlib.sha256(entry.source_id.encode()).hexdigest()
