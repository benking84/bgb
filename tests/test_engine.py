import hashlib

import pytest

from bgb.errors import IntegrityError, NotFound
from bgb.index.memory import FileIndex
from bgb.models import FileSet, VolumeRef
from bgb.util import now_iso
from bgb.volume import compress, decode_payload, decompress, encode_blocks
from tests.helpers import BytesSource, job, make_engine


def test_compress_roundtrip_and_tamper():
    blob = compress(b"handbook")
    assert decompress(blob) == b"handbook"
    flipped = bytearray(blob)
    flipped[-1] ^= 0x01
    with pytest.raises(IntegrityError):
        decompress(bytes(flipped))


def test_block_payload_detects_a_flipped_byte():
    data = b"hello"
    payload = bytearray(encode_blocks([(hashlib.sha256(data).hexdigest(), data)]))
    payload[-1] ^= 0x01
    with pytest.raises(IntegrityError):
        decode_payload(bytes(payload))


def test_dedup_restore_and_second_backup_skips_reads(tmp_path):
    body = b"A" * 100
    source = BytesSource({"one.bin": body, "two.bin": body, "other.bin": b"B" * 40})
    runtime, _holder = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job())
    first = runtime.engine.run_backup("job1")
    assert first.status == "completed"
    assert first.stats["blocks_new"] > 0
    assert first.stats["blocks_reused"] >= 1
    opens_after_first = source.opens
    fileset = runtime.index.list_filesets("job1")[0]
    data, entry = runtime.engine.read_file("job1", fileset.id, "mem/one.bin")
    assert data == body
    assert entry.content_hash == hashlib.sha256(body).hexdigest()
    report = runtime.engine.verify("job1", full=True)
    assert report["ok"] is True
    assert report["checked_volumes"] >= 1

    second = runtime.engine.run_backup("job1")
    assert second.stats["blocks_new"] == 0
    assert second.stats["files_read"] == 0
    assert second.stats["files_unchanged"] == 3
    assert source.opens == opens_after_first

    source.files["other.bin"] = b"B" * 32 + b"C" * 8
    third = runtime.engine.run_backup("job1")
    assert third.stats["files_read"] == 1
    assert third.stats["blocks_new"] >= 1
    assert third.stats["blocks_reused"] >= 1
    restored, _entry = runtime.engine.read_file(
        "job1", runtime.index.list_filesets("job1")[0].id, "mem/other.bin"
    )
    assert restored == source.files["other.bin"]


def test_verify_reports_a_corrupt_volume(tmp_path):
    source = BytesSource({"one.bin": b"Z" * 80})
    runtime, _holder = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job())
    runtime.engine.run_backup("job1")
    volume = next(
        row for row in runtime.index.list_volumes("job1") if row.kind == "dblock"
    )
    blob = bytearray(runtime.volumes.get(volume.name))
    blob[-2] ^= 0xFF
    runtime.volumes.put(volume.name, bytes(blob))
    report = runtime.engine.verify("job1", full=True)
    assert report["ok"] is False
    assert report["issues"]


def test_retention_then_compact_drops_unreferenced_blocks(tmp_path):
    source = BytesSource(
        {"keep.bin": bytes(range(64)), "drop.bin": bytes(range(64, 128))}
    )
    runtime, holder = make_engine(
        tmp_path, block_size=32, volume_size=10_000, source=source
    )
    runtime.index.upsert_job(
        job(retention="versions:1", block_size=32, volume_size=10_000)
    )
    runtime.engine.run_backup("job1")
    first_fileset = runtime.index.list_filesets("job1")[0].id
    assert runtime.index.count_blocks("job1") == 4

    holder["source"] = BytesSource({"keep.bin": bytes(range(64))})
    runtime.engine.run_backup("job1")
    with pytest.raises(NotFound):
        runtime.engine.read_file("job1", first_fileset, "mem/drop.bin")
    kept = runtime.engine.read_file(
        "job1", runtime.index.list_filesets("job1")[0].id, "mem/keep.bin"
    )[0]
    assert kept == bytes(range(64))
    assert runtime.index.count_blocks("job1") == 2
    assert (
        len([row for row in runtime.index.list_volumes("job1") if row.kind == "dblock"])
        == 1
    )


def test_rebuild_index_from_volumes(tmp_path):
    source = BytesSource({"notes.txt": b"restore-me-please" * 4})
    runtime, _holder = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job())
    runtime.engine.run_backup("job1")
    before = runtime.engine.read_file(
        "job1", runtime.index.list_filesets("job1")[0].id, "mem/notes.txt"
    )[0]
    runtime.index.clear_backup_data("job1")
    assert runtime.index.list_filesets("job1") == []
    report = runtime.engine.rebuild("job1")
    assert report["filesets"] == 1
    fileset = runtime.index.list_filesets("job1")[0]
    assert runtime.engine.read_file("job1", fileset.id, "mem/notes.txt")[0] == before


def test_prune_removes_objects_missing_from_the_index(tmp_path):
    source = BytesSource({"a.bin": b"abc"})
    runtime, _holder = make_engine(tmp_path, source=source)
    runtime.index.upsert_job(job())
    runtime.engine.run_backup("job1")
    runtime.volumes.put("bgb/job1/dblock/orphan.bgb", b"nope")
    report = runtime.engine.verify("job1")
    assert "bgb/job1/dblock/orphan.bgb" in report["extra"]
    removed = runtime.engine.prune_orphans("job1")
    assert removed == ["bgb/job1/dblock/orphan.bgb"]
    assert runtime.engine.verify("job1", full=True)["extra"] == []


def test_file_index_reloads_a_job(tmp_path):
    index = FileIndex(tmp_path / "index.json")
    index.upsert_job(job())
    index.put_fileset(
        FileSet(
            id="fs",
            job_id="job1",
            created_at=now_iso(),
            volume_id="v",
            file_count=0,
            bytes=0,
        ),
        [],
    )
    index.put_volume(
        "job1",
        VolumeRef(
            id="v",
            name="bgb/job1/dlist/x.bgb",
            kind="dlist",
            size=1,
            hash="abc",
            state="available",
            created_at=now_iso(),
        ),
    )
    index.flush()
    loaded = FileIndex(tmp_path / "index.json")
    assert loaded.get_job("job1").name == "Test"
    assert loaded.get_fileset("job1", "fs").volume_id == "v"
    assert loaded.get_volume("job1", "v").kind == "dlist"
