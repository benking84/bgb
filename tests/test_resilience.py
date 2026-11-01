import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from bgb import engine as engine_module
from bgb.engine import Engine
from bgb.errors import Conflict, IntegrityError
from bgb.googleapi import _retryable
from tests.helpers import BytesSource, job, make_engine


class Killed(BaseException):
    """Stands in for Cloud Run killing the process: the engine's except Exception never sees it."""


class CountingSource(BytesSource):
    def __init__(self, files, *, kill_after=None):
        super().__init__(files)
        self.kill_after = kill_after

    def _opener(self, data):
        def open_file(body: bytes = data):
            if self.kill_after is not None and self.opens >= self.kill_after:
                raise Killed()
            self.opens += 1
            return io.BytesIO(body)

        return open_file


def _files(count, size=200):
    return {
        f"f{index:03d}": bytes([index % 251]) * size + index.to_bytes(4, "big")
        for index in range(count)
    }


def test_killed_run_resumes_without_rereading(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "CHECKPOINT_ENTRIES", 10)
    source = CountingSource(_files(60), kill_after=35)
    runtime, _ = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job(sources=["mem"], block_size=64, volume_size=1024))
    with pytest.raises(Killed):
        runtime.engine.run_backup("job1")
    saved = len(runtime.index.list_checkpoint("job1"))
    assert saved >= 30

    source.kill_after = None
    source.opens = 0
    run = runtime.engine.run_backup("job1")
    assert run.status == "completed"
    assert source.opens == 60 - saved
    assert run.stats["files_resumed"] == saved
    assert runtime.index.list_checkpoint("job1") == []
    statuses = [row.status for row in runtime.index.list_runs("job1")]
    assert statuses.count("failed") == 1  # the killed run is closed as abandoned
    fileset = runtime.index.list_filesets("job1")[0]
    for entry in runtime.index.iter_entries("job1", fileset.id):
        runtime.engine.read_file("job1", fileset.id, entry.path)


def test_second_execution_cannot_run_while_the_lease_is_held(tmp_path):
    source = CountingSource(_files(5))
    runtime, _ = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job(sources=["mem"], block_size=64, volume_size=1024))
    other = Engine(runtime.index, runtime.volumes, lambda _job, _settings: [source])
    assert runtime.index.acquire_lease("job1", runtime.engine.holder, 60)
    with pytest.raises(Conflict):
        other.run_backup("job1")
    with pytest.raises(Conflict):
        other.rebuild("job1")
    with pytest.raises(Conflict):
        other.prune_orphans("job1")
    with pytest.raises(Conflict):
        runtime.start_backup("job1")
    assert runtime.run_due() == []


def test_expired_lease_is_taken_over(tmp_path):
    source = CountingSource(_files(5))
    runtime, _ = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job(sources=["mem"], block_size=64, volume_size=1024))
    runtime.index.acquire_lease("job1", "dead-execution", -1)
    assert runtime.engine.run_backup("job1").status == "completed"


def test_fileset_is_not_saved_when_reused_blocks_vanish(tmp_path):
    shared = bytes(range(256))
    source = CountingSource({"a": shared})
    runtime, _ = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job(sources=["mem"], block_size=64, volume_size=1024))
    runtime.engine.run_backup("job1")
    before = len(runtime.index.list_filesets("job1"))

    original = runtime.index.has_block

    def has_block_then_lose_it(job_id, digest):
        hit = original(job_id, digest)
        if hit:
            runtime.index.delete_blocks(
                job_id, [digest]
            )  # what an unguarded compaction would do
        return hit

    runtime.index.has_block = has_block_then_lose_it
    source.files = {"b": shared}
    with pytest.raises(IntegrityError):
        runtime.engine.run_backup("job1")
    assert len(runtime.index.list_filesets("job1")) == before


def test_retention_defers_deletes_until_objects_are_old_enough(tmp_path):
    source = CountingSource({"a": b"a" * 300})
    runtime, _ = make_engine(tmp_path, source=source)
    runtime.engine.min_object_age = timedelta(days=30)
    runtime.index.upsert_job(
        job(sources=["mem"], block_size=64, volume_size=1024, retention="versions:1")
    )
    runtime.engine.run_backup("job1")
    source.files = {"b": b"b" * 300}
    run = runtime.engine.run_backup("job1")
    assert run.stats["filesets_removed"] == 1
    assert run.stats["volumes_rewritten"] == 0 and run.stats["volumes_deleted"] == 0
    expired = [
        row for row in runtime.index.list_volumes("job1") if row.state == "expired"
    ]
    assert [row.kind for row in expired] == ["dlist"]
    assert expired[0].name in runtime.volumes.objects

    later = datetime.now(UTC) + timedelta(days=31)
    assert runtime.engine.sweep_expired("job1", now=later) == 1
    assert expired[0].name not in runtime.volumes.objects
    assert runtime.engine.verify("job1", full=True)["ok"]


def _http_error(status, body):
    from googleapiclient.errors import HttpError
    from httplib2 import Response

    return HttpError(Response({"status": status}), json.dumps(body).encode())


def test_rate_limit_403_is_retried_but_permission_403_is_not():
    limited = {
        "error": {
            "errors": [{"reason": "userRateLimitExceeded"}],
            "status": "PERMISSION_DENIED",
        }
    }
    denied = {
        "error": {
            "errors": [{"reason": "insufficientPermissions"}],
            "status": "PERMISSION_DENIED",
        }
    }
    assert _retryable(_http_error(403, limited))
    assert not _retryable(_http_error(403, denied))
    assert _retryable(_http_error(429, {}))
    assert not _retryable(_http_error(404, {}))


def test_media_stream_returns_full_blocks_and_holds_one_chunk(monkeypatch):
    from googleapiclient import http

    from bgb.googleapi import MediaStream

    payload = bytes(range(256)) * 40

    class FakeDownload:
        def __init__(self, sink, request, chunksize):
            self.sink, self.offset, self.chunksize = sink, 0, 700

        def next_chunk(self, num_retries=0):
            self.sink.write(payload[self.offset : self.offset + self.chunksize])
            self.offset += self.chunksize
            return None, self.offset >= len(payload)

    monkeypatch.setattr(http, "MediaIoBaseDownload", FakeDownload)
    stream = MediaStream(request=None)
    blocks = []
    while True:
        chunk = stream.read(1000)
        if not chunk:
            break
        assert len(stream._buffer) < 1000 + 700
        blocks.append(chunk)
    assert b"".join(blocks) == payload
    assert all(len(block) == 1000 for block in blocks[:-1])
