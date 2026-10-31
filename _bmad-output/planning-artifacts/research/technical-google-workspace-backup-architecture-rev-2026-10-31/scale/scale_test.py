"""Synthetic scale harness for bgb. No Google or GCP calls.

Runs the real engine, GmailSource and DriveSource against fake API clients that
count calls. Reports JSON on stdout.

  python scale_test.py resume   # killed first backup, then rerun
  python scale_test.py memory SIZE_MB   # one Drive file of SIZE_MB, peak RSS
  python scale_test.py blocks   # block and index lookup counts by block size
  python scale_test.py busy     # run_due after a killed run
"""
from __future__ import annotations

import io
import json
import random
import resource
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bgb.engine import Engine
from bgb.index.memory import MemoryIndex
from bgb.models import Job, Run
from bgb.sources.drive import DriveSource
from bgb.sources.gmail import GmailSource
from bgb.storage import LocalVolumeStore
from bgb.util import now_iso

KIB = 1024
MIB = 1024 * KIB
# Gmail quota units, verified 2026-10-31 (developers.google.com/workspace/gmail/api/reference/quota)
UNITS_META = 20
UNITS_RAW = 60
UNITS_PER_USER_MIN = 6000


class Killed(BaseException):
    """Stands in for a Cloud Run timeout kill: the engine's except Exception does not see it."""


def body(i: int, size: int) -> bytes:
    return random.Random(i).randbytes(size)


class FakeGmail:
    def __init__(self, count: int, size: int, kill_after: int | None):
        self.count, self.size, self.kill_after = count, size, kill_after
        self.meta_calls = 0
        self.raw_calls = 0

    def get_profile(self, user):
        return {"historyId": "1"}

    def list_message_ids(self, user, token):
        page = int(token or 0)
        ids = [f"m{i}" for i in range(page, min(page + 500, self.count))]
        nxt = page + 500
        return ids, (str(nxt) if nxt < self.count else None)

    def get_metadata(self, user, mid):
        self.meta_calls += 1
        return {"id": mid, "labelIds": ["INBOX"], "internalDate": "1760000000000", "snippet": "", "subject": mid}

    def get_raw(self, user, mid):
        if self.kill_after is not None and self.raw_calls >= self.kill_after:
            raise Killed()
        self.raw_calls += 1
        return body(int(mid[1:]), self.size)

    def get_message(self, user, mid):
        # After the fix: one raw fetch returns labels too, so no metadata call.
        return {"id": mid, "raw": self.get_raw(user, mid), "labelIds": ["INBOX"], "internalDate": "1760000000000"}

    def list_history(self, user, start):
        return {"historyId": "2", "records": []}


class RandomStream(io.RawIOBase):
    def __init__(self, size):
        self.left, self.rng, self.buffer = size, random.Random(1), bytearray()

    def readable(self):
        return True

    def read(self, n=-1):
        while self.left and len(self.buffer) < n:
            take = min(8 * MIB, self.left)
            self.buffer += self.rng.randbytes(take)
            self.left -= take
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        return out


class FakeDrive:
    def __init__(self, size: int):
        self.size = size

    def list_files(self, user, drive_id, token):
        return [{"id": "big", "name": "big.mp4", "mimeType": "video/mp4", "md5Checksum": "x",
                 "size": str(self.size), "parents": ["root"], "modifiedTime": "2026-10-01T00:00:00Z"}], None

    def list_shared_drives(self, user):
        return []

    def start_token(self, user, drive_id):
        return "t1"

    def list_changes(self, user, token, drive_id):
        return {"changes": [], "token": "t1"}

    def get_file(self, user, file_id):
        return {"id": "root", "name": "My Drive", "mimeType": "application/vnd.google-apps.folder"}

    def download(self, user, file_id):
        # After the fix the client returns a stream; this one generates 8 MiB at a time.
        return RandomStream(self.size)

    def export(self, user, file_id, mime):
        raise AssertionError("not used")


def engine_for(tmp: Path, source, *, block_size: int, volume_size: int = 50 * MIB):
    index = MemoryIndex()
    settings = index.get_settings()
    settings.block_size = block_size
    settings.volume_size = volume_size
    index.save_settings(settings)
    engine = Engine(index, LocalVolumeStore(tmp / "volumes"), lambda job, _s: [source])
    return engine, index


def make_job(block_size: int, sources=("gmail",)) -> Job:
    return Job(id="scale", name="scale", users=["ada@example.com"], sources=list(sources),
               retention="versions:5", block_size=block_size, volume_size=50 * MIB,
               created_at=now_iso(), demo=False)


def count_has_block(index):
    calls = {"n": 0}
    original = index.has_block

    def wrapped(job_id, digest):
        calls["n"] += 1
        return original(job_id, digest)

    index.has_block = wrapped
    return calls


def resume(count=5000, size=75 * KIB, kill_after=2000):
    out = {"messages": count, "message_kib": size // KIB, "kill_after_raw": kill_after, "runs": []}
    with tempfile.TemporaryDirectory() as tmp:
        gmail = FakeGmail(count, size, kill_after)
        source = GmailSource(gmail, ["ada@example.com"])
        engine, index = engine_for(Path(tmp), source, block_size=100 * KIB)
        index.upsert_job(make_job(100 * KIB))
        for attempt, kill in enumerate([kill_after, kill_after, None], start=1):
            gmail.kill_after = kill
            gmail.meta_calls = gmail.raw_calls = 0
            volumes_before = len(index.list_volumes("scale"))
            status = "completed"
            started = time.time()
            try:
                engine.run_backup("scale")
            except Killed:
                status = "killed (timeout)"
            units = gmail.meta_calls * UNITS_META + gmail.raw_calls * UNITS_RAW
            latest = index.list_runs("scale")[0]
            out["runs"].append({
                "run": attempt,
                "outcome": status,
                "run_record_status": latest.status,
                "metadata_calls": gmail.meta_calls,
                "raw_downloads": gmail.raw_calls,
                "quota_units": units,
                "quota_minutes_at_6000_per_user": round(units / UNITS_PER_USER_MIN, 1),
                "volumes_written": len(index.list_volumes("scale")) - volumes_before,
                "filesets_total": len(index.list_filesets("scale")),
                "local_seconds": round(time.time() - started, 1),
            })
    per_msg = UNITS_RAW  # one raw fetch per message after the fix
    out["ceiling_msgs_per_min_per_user"] = UNITS_PER_USER_MIN / per_msg
    out["hours_for_100k_msgs_at_ceiling"] = round(100_000 / (UNITS_PER_USER_MIN / per_msg) / 60, 1)
    return out


def memory(size_mb: int):
    size = size_mb * MIB
    with tempfile.TemporaryDirectory() as tmp:
        drive = FakeDrive(size)
        source = DriveSource(drive, ["ada@example.com"], include_shared=False, shared_actor="")
        engine, index = engine_for(Path(tmp), source, block_size=100 * KIB)
        index.upsert_job(make_job(100 * KIB, sources=("drive",)))
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        run = engine.run_backup("scale")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # macOS reports bytes, Linux KiB
    return {"file_mb": size_mb, "status": run.status,
            "baseline_rss_mb": round(base * scale / MIB), "peak_rss_mb": round(peak * scale / MIB),
            "peak_over_file": round(peak * scale / size, 2)}


def blocks(total_mb=200, file_mb=8):
    out = []
    for block_size in (100 * KIB, 1 * MIB):
        with tempfile.TemporaryDirectory() as tmp:
            files = total_mb // file_mb
            from tests.helpers import BytesSource
            source = BytesSource({f"f{i}.bin": body(i, file_mb * MIB) for i in range(files)})
            engine, index = engine_for(Path(tmp), source, block_size=block_size)
            index.upsert_job(make_job(block_size, sources=("mem",)))
            calls = count_has_block(index)
            started = time.time()
            engine.run_backup("scale")
            elapsed = time.time() - started
            lookups = calls["n"]
            out.append({
                "block_kib": block_size // KIB,
                "data_mb": total_mb,
                "index_lookups": lookups,
                "lookups_per_tib": lookups * (1024 * 1024 // total_mb),
                "local_mb_per_s": round(total_mb / elapsed, 1),
                "hours_per_tib_if_10ms_per_lookup": round(lookups * (1024 * 1024 // total_mb) * 0.01 / 3600, 1),
            })
    return out


def busy():
    index = MemoryIndex()
    job = make_job(100 * KIB)
    job.schedule = "0 * * * *"
    index.upsert_job(job)
    killed_at = datetime.now(timezone.utc) - timedelta(hours=5)
    index.add_run(Run(id="r1", job_id="scale", status="running", phase="blocks",
                      started_at=killed_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
    from bgb.runtime import Runtime
    rt = Runtime.__new__(Runtime)
    rt.index = index
    rt.engine = None  # run_due must not reach the engine if the guard holds
    try:
        started = rt.run_due()
        result = f"skipped ({len(started)} runs started)"
    except AttributeError:
        result = "started a run"
    return {"killed_run_age_hours": 5, "job_timeout_hours": 4, "busy_horizon_hours": 24, "run_due": result}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "resume":
        print(json.dumps(resume(), indent=1))
    elif cmd == "memory":
        print(json.dumps(memory(int(sys.argv[2])), indent=1))
    elif cmd == "blocks":
        print(json.dumps(blocks(), indent=1))
    elif cmd == "busy":
        print(json.dumps(busy(), indent=1))
