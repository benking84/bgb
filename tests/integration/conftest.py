from __future__ import annotations

import os
import uuid

import httpx
import pytest

from bgb.index.memory import FileIndex, MemoryIndex

EMULATOR_PROJECT = "bgb-test"


@pytest.fixture
def firestore_client():
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip()
    if not host:
        if os.environ.get("BGB_REQUIRE_EMULATOR") == "1":
            pytest.fail("BGB_REQUIRE_EMULATOR=1 but FIRESTORE_EMULATOR_HOST is not set")
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set; start the Firestore emulator")
    from google.cloud import firestore

    httpx.delete(
        f"http://{host}/emulator/v1/projects/{EMULATOR_PROJECT}/databases/(default)/documents"
    ).raise_for_status()
    client = firestore.Client(project=EMULATOR_PROJECT)
    yield client
    client.close()


@pytest.fixture(params=["memory", "file", "firestore"])
def index(request, tmp_path):
    if request.param == "memory":
        return MemoryIndex()
    if request.param == "file":
        return FileIndex(tmp_path / f"index-{uuid.uuid4().hex}.json")
    from bgb.index.firestore import FirestoreIndex

    return FirestoreIndex(request.getfixturevalue("firestore_client"))


@pytest.fixture
def firestore_index(firestore_client):
    from bgb.index.firestore import FirestoreIndex

    return FirestoreIndex(firestore_client)
