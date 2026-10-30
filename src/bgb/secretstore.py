from __future__ import annotations

import os
from pathlib import Path

from bgb.errors import SecretNotFound


class FileSecrets:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = name.replace("/", "_")
        if not safe or safe in {".", ".."}:
            raise SecretNotFound(name)
        return self.root / safe

    def get(self, name: str) -> bytes:
        path = self._path(name)
        if not path.exists():
            raise SecretNotFound(name)
        return path.read_bytes()

    def put(self, name: str, data: bytes) -> None:
        path = self._path(name)
        path.write_bytes(data)
        path.chmod(0o600)


class GcpSecrets:
    def __init__(self, project: str):
        from google.cloud import secretmanager

        self.project = project
        self.client = secretmanager.SecretManagerServiceClient()

    def get(self, name: str) -> bytes:
        from google.api_core.exceptions import NotFound

        path = name
        if not name.startswith("projects/"):
            path = f"projects/{self.project}/secrets/{name}/versions/latest"
        elif "/versions/" not in name:
            path = name + "/versions/latest"
        try:
            response = self.client.access_secret_version(name=path)
        except NotFound as exc:
            raise SecretNotFound(name) from exc
        return response.payload.data

    def put(self, name: str, data: bytes) -> None:
        raise SecretNotFound("refusing to write secrets from the Cloud Run process; use Secret Manager")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}
