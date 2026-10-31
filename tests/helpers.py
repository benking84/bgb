from __future__ import annotations

import io
from pathlib import Path

from bgb.engine import Engine
from bgb.errors import SecretNotFound
from bgb.index.memory import MemoryIndex
from bgb.models import Job, Scan, ScopeScan, SourceObject
from bgb.runtime import Runtime
from bgb.secretstore import FileSecrets
from bgb.storage import MemoryVolumeStore
from bgb.util import now_iso


class DictSecrets:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    def get(self, name: str) -> bytes:
        try:
            return self.data[name]
        except KeyError as exc:
            raise SecretNotFound(name) from exc

    def put(self, name: str, data: bytes) -> None:
        self.data[name] = data


class BytesSource:
    name = "mem"
    id_prefix = "mem:"

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.opens = 0

    def scan(self, job: Job) -> Scan:
        objects = []
        for path, data in self.files.items():
            objects.append(
                SourceObject(
                    source_id=f"mem:{path}",
                    scope="mem:main",
                    path=f"mem/{path}",
                    revision=_revision(data),
                    mtime=None,
                    metadata={"name": path},
                    opener=self._opener(data),
                )
            )
        return Scan(
            scopes=[ScopeScan("mem:main", "full", objects)],
            state={"n": len(objects)},
            warnings=[],
        )

    def _opener(self, data: bytes):
        def open_file(body: bytes = data):
            self.opens += 1
            return io.BytesIO(body)

        return open_file


def _revision(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def make_engine(
    tmp: Path, *, block_size: int = 32, volume_size: int = 4096, source=None, index=None
):
    index = index if index is not None else MemoryIndex()
    settings = index.get_settings()
    settings.block_size = block_size
    settings.volume_size = volume_size
    settings.verify_samples = 1
    settings.compact_waste_threshold = 0.25
    index.save_settings(settings)
    secrets = FileSecrets(tmp / "secrets")
    volumes = MemoryVolumeStore()
    holder = {"source": source}

    def sources_for(job, _settings):
        if holder["source"] is not None:
            return [holder["source"]]
        from bgb.sources.factory import build_sources

        return build_sources(job, _settings, secrets)

    engine = Engine(index, volumes, sources_for)
    runtime = Runtime(index, volumes, secrets, tmp)
    runtime.engine = engine
    return runtime, holder


def job(**overrides) -> Job:
    payload = {
        "id": "job1",
        "name": "Test",
        "users": ["ada@example.com"],
        "sources": ["gmail"],
        "retention": "versions:5",
        "block_size": 32,
        "volume_size": 4096,
        "created_at": now_iso(),
        "demo": False,
    }
    payload.update(overrides)
    return Job(**payload)
