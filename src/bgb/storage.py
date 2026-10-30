from __future__ import annotations

from pathlib import Path


class MemoryVolumeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, name: str, data: bytes) -> None:
        self.objects[name] = data

    def get(self, name: str) -> bytes:
        try:
            return self.objects[name]
        except KeyError as exc:
            raise FileNotFoundError(name) from exc

    def delete(self, name: str) -> None:
        self.objects.pop(name, None)

    def list(self, prefix: str = "") -> list[str]:
        return sorted(name for name in self.objects if name.startswith(prefix))


class LocalVolumeStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError(f"unsafe object name {name!r}")
        path = (self.root / name).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"unsafe object name {name!r}")
        return path

    def put(self, name: str, data: bytes) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, name: str) -> bytes:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(name)
        return path.read_bytes()

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()

    def list(self, prefix: str = "") -> list[str]:
        if not self.root.exists():
            return []
        names = []
        for path in self.root.rglob("*"):
            if path.is_file():
                name = path.relative_to(self.root).as_posix()
                if name.startswith(prefix):
                    names.append(name)
        return sorted(names)


class GCSVolumeStore:
    def __init__(self, bucket_name: str):
        from google.cloud import storage

        client = storage.Client()
        self.client = client
        self.bucket = client.bucket(bucket_name)

    def put(self, name: str, data: bytes) -> None:
        self.bucket.blob(name).upload_from_string(data, content_type="application/octet-stream")

    def get(self, name: str) -> bytes:
        return self.bucket.blob(name).download_as_bytes()

    def delete(self, name: str) -> None:
        blob = self.bucket.blob(name)
        if blob.exists():
            blob.delete()

    def list(self, prefix: str = "") -> list[str]:
        return [blob.name for blob in self.client.list_blobs(self.bucket, prefix=prefix)]
