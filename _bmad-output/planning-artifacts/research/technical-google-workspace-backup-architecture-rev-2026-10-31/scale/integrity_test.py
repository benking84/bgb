"""Index loss and corruption scenarios for bgb. No Google or GCP calls.

  python integrity_test.py rebuild      # wipe the index, rebuild from volumes, restore everything
  python integrity_test.py compaction   # retention + compaction, then wipe and rebuild
  python integrity_test.py race         # compaction from a second process during a backup
  python integrity_test.py rebuildcost SIZE_MB  # bytes read and peak memory for a rebuild
"""
from __future__ import annotations

import io
import json
import random
import resource
import sys
import tempfile
from pathlib import Path

from bgb.engine import Engine
from bgb.errors import BgbError, IntegrityError, NotFound
from bgb.index.memory import MemoryIndex
from bgb.models import Job, Scan, ScopeScan, SourceObject
from bgb.storage import LocalVolumeStore
from bgb.util import now_iso

KIB = 1024
MIB = 1024 * KIB


class Files:
    """A source whose contents the test changes between runs."""

    name = "mem"
    id_prefix = "mem:"

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.hook = None

    def scan(self, job):
        objects = []
        for path, data in self.files.items():
            def opener(body=data, p=path):
                if self.hook:
                    self.hook(p)
                return io.BytesIO(body)
            objects.append(SourceObject(source_id=f"mem:{path}", scope="mem:main", path=f"mem/{path}",
                                        revision=str(hash(data)), mtime=None, metadata={}, opener=opener))
        return Scan(scopes=[ScopeScan("mem:main", "full", objects)], state={}, warnings=[])


def blob(seed: int, size: int) -> bytes:
    return random.Random(seed).randbytes(size)


def setup(tmp: Path, source, *, retention="versions:10", block=100 * KIB, volume=4 * MIB):
    index = MemoryIndex()
    settings = index.get_settings()
    settings.block_size, settings.volume_size = block, volume
    settings.compact_waste_threshold = 0.25
    index.save_settings(settings)
    store = LocalVolumeStore(tmp / "volumes")
    index.upsert_job(Job(id="j", name="j", users=["a@x"], sources=["mem"], retention=retention,
                         block_size=block, volume_size=volume, created_at=now_iso(), demo=False))
    return Engine(index, store, lambda job, _s: [source]), index, store


def restore_all(engine, index) -> dict:
    ok, failed = 0, []
    for fileset in index.list_filesets("j"):
        for entry in index.iter_entries("j", fileset.id):
            try:
                engine.read_file("j", fileset.id, entry.path)
                ok += 1
            except (BgbError, NotFound, IntegrityError, KeyError) as exc:
                failed.append(f"{entry.path}: {type(exc).__name__}")
    return {"restored": ok, "failed": failed}


def rebuild():
    with tempfile.TemporaryDirectory() as tmp:
        src = Files()
        engine, index, _ = setup(Path(tmp), src)
        for run in range(3):
            src.files = {f"f{i}": blob(i * 10 + (run if i % 3 == 0 else 0), 300 * KIB) for i in range(30)}
            engine.run_backup("j")
        before = restore_all(engine, index)
        index.clear_backup_data("j")  # total loss of backup records in Firestore
        after_loss = restore_all(engine, index)
        engine.rebuild("j")
        after = restore_all(engine, index)
        return {"before": before["restored"], "after_index_loss": after_loss["restored"],
                "after_rebuild": after["restored"], "failures": after["failed"],
                "verify": engine.verify("j", full=True)["ok"]}


def compaction():
    with tempfile.TemporaryDirectory() as tmp:
        src = Files()
        engine, index, _ = setup(Path(tmp), src, retention="versions:2")
        for run in range(6):
            src.files = {f"f{i}": blob(run * 100 + i, 300 * KIB) for i in range(20)}
            src.files["stable"] = blob(9999, 2 * MIB)
            engine.run_backup("j")
        before = restore_all(engine, index)
        index.clear_backup_data("j")
        engine.rebuild("j")
        after = restore_all(engine, index)
        return {"filesets_kept": len(index.list_filesets("j")), "restored_before": before["restored"],
                "restored_after_rebuild": after["restored"], "failures": after["failed"],
                "verify_full": engine.verify("j", full=True)["ok"]}


def race():
    """Two overlapping executions of one job (separate processes, so separate locks).

    Run 2 drops 'report'; its blocks stay indexed because their volume is under the
    compaction threshold. Run 3 brings 'report' back and dedups against those blocks.
    While run 3 is ingesting, a second execution backs up, prunes run 2 by retention and
    compacts, deleting the blocks run 3 just reused. Run 3 then commits its fileset."""
    import hashlib

    with tempfile.TemporaryDirectory() as tmp:
        src = Files()
        engine, index, store = setup(Path(tmp), src, retention="versions:1")
        later = Files()
        later.files = {f"x{i}": blob(500 + i, 100 * KIB) for i in range(4)}
        other = Engine(index, store, lambda job, _s: [later])  # second execution, own lock
        stable = blob(2, 3200 * KIB)
        report = blob(1, 800 * KIB)
        src.files = {"a_stable": stable, "b_report": report}
        engine.run_backup("j")                     # run 1: stable + report share a volume
        src.files = {"a_stable": stable}
        engine.run_backup("j")                     # run 2: report dead, volume waste 20%, kept
        report_hashes = {hashlib.sha256(report[i:i + 100 * KIB]).hexdigest() for i in range(0, len(report), 100 * KIB)}
        original = index.has_block
        fired = {"done": False}

        def has_block(job_id, digest):
            hit = original(job_id, digest)
            if hit and digest in report_hashes and not fired["done"]:
                fired["done"] = True
                try:
                    other.run_backup("j")          # overlapping execution: retention + compaction
                    fired["other"] = "ran"
                except BgbError as exc:            # after the fix the lease refuses it
                    fired["other"] = f"refused: {exc}"
            return hit
        index.has_block = has_block
        src.files = {"a_stable": stable, "b_report": report}
        run3 = engine.run_backup("j")               # run 3: report back, dedups against dead blocks
        index.has_block = original
        verify = engine.verify("j", full=True)
        latest = index.list_filesets("j")[-1]
        try:
            engine.read_file("j", latest.id, "mem/b_report")
            restore = "ok"
        except (BgbError, NotFound, IntegrityError) as exc:
            restore = f"failed: {type(exc).__name__}: {exc}"
        return {"second_execution": fired.get("other"), "run3_status": run3.status, "verify_full_ok": verify["ok"],
                "verify_issues": verify["issues"][:3], "restore_report_from_run3": restore}


def rebuildcost(size_mb: int):
    with tempfile.TemporaryDirectory() as tmp:
        src = Files()
        engine, index, store = setup(Path(tmp), src, volume=50 * MIB)
        src.files = {f"f{i}": blob(i, 8 * MIB) for i in range(size_mb // 8)}
        engine.run_backup("j")
        src.files = {}
        total = sum((Path(tmp) / "volumes").rglob("*") and [p.stat().st_size for p in (Path(tmp) / "volumes").rglob("*") if p.is_file()])
        small = sum(p.stat().st_size for p in (Path(tmp) / "volumes").rglob("*") if p.is_file() and ("dindex" in str(p) or "dlist" in str(p)))
        read = {"bytes": 0}
        original = store.get

        def counted(name):
            data = original(name)
            read["bytes"] += len(data)
            return data
        store.get = counted
        index.clear_backup_data("j")
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        engine.rebuild("j")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        scale = 1 if sys.platform == "darwin" else 1024
        return {"backup_mb": size_mb, "bucket_mb": round(total / MIB), "dindex_plus_dlist_mb": round(small / MIB, 2),
                "rebuild_read_mb": round(read["bytes"] / MIB), "peak_rss_mb": round(peak * scale / MIB),
                "rss_before_mb": round(base * scale / MIB)}


if __name__ == "__main__":
    cmd = sys.argv[1]
    result = {"rebuild": rebuild, "compaction": compaction, "race": race}.get(cmd)
    print(json.dumps(result() if result else rebuildcost(int(sys.argv[2])), indent=1))
