"""R-001: the Firestore index is what production runs, so it must behave like the fakes.

Red phase. Remove the skip marker once the Firestore emulator runs locally and in
CI (epic Story 1.4). See _bmad-output/test-artifacts/atdd-checklist-1-4-firestore-index-r-001.md.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from bgb.api.app import create_app
from bgb.models import BlockRef
from bgb.sources.demo import HANDBOOK
from tests.helpers import BytesSource, job, make_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.p0,
    pytest.mark.skip(
        reason="ATDD red phase: Firestore emulator harness not built yet (Story 1.4)"
    ),
]


def _digest(seed: int) -> str:
    return hashlib.sha256(f"block-{seed}".encode()).hexdigest()


def test_ac1_put_block_stores_a_hash_once_on_every_index(index):
    block = BlockRef(hash=_digest(1), size=32, volume_id="vol-1")

    first = index.put_block("job1", block)
    second = index.put_block(
        "job1", BlockRef(hash=block.hash, size=32, volume_id="vol-2")
    )

    assert second is False
    assert first is True
    assert index.get_block("job1", block.hash).volume_id == "vol-1"
    assert index.count_blocks("job1") == 1


def test_ac2_block_list_over_400_hashes_round_trips_in_order(index):
    hashes = [_digest(seed) for seed in range(801)]

    index.put_blockset("job1", "bs-large", hashes)

    assert index.get_blockset("job1", "bs-large") == hashes


def test_ac3_backup_over_500_writes_completes_on_firestore(tmp_path, firestore_index):
    files = {f"file-{n:04}.bin": f"distinct body {n}".encode() for n in range(600)}
    runtime, _holder = make_engine(
        tmp_path, source=BytesSource(files), index=firestore_index
    )
    runtime.index.upsert_job(job())

    run = runtime.engine.run_backup("job1")

    assert run.status == "completed", run.error
    fileset = runtime.index.list_filesets("job1")[0]
    assert fileset.file_count == 600
    assert len(runtime.index.iter_entries("job1", fileset.id)) == 600


def test_ac4_northwind_restore_is_byte_identical_on_firestore(
    tmp_path, firestore_index
):
    runtime, _holder = make_engine(tmp_path, index=firestore_index)
    client = TestClient(create_app(runtime))
    client.post("/api/demo/seed")
    client.post("/api/jobs/northwind/run?wait=true")
    fileset = runtime.index.list_filesets("northwind")[0]
    handbook = "drive/users/ada@northwind.example/Policies/handbook.pdf"

    downloaded = client.get(
        f"/api/jobs/northwind/filesets/{fileset.id}/content",
        params={"path": handbook},
    )

    assert downloaded.content == HANDBOOK
    entry = runtime.index.get_entry("northwind", fileset.id, handbook)
    assert hashlib.sha256(downloaded.content).hexdigest() == entry.content_hash
