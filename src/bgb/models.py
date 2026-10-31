from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


def _dump(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {key: _dump(item) for key, item in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value


@dataclass
class Settings:
    workspace_domain: str = ""
    admin_email: str = ""
    auth_mode: str = "service_account"
    service_account_secret: str = "bgb-workspace-sa"
    service_account_email: str = ""
    oauth_secret: str = "bgb-oauth-client"
    gcs_bucket: str = ""
    gcs_prefix: str = "bgb"
    block_size: int = 102400
    volume_size: int = 50 * 1024 * 1024
    verify_samples: int = 1
    compact_waste_threshold: float = 0.25

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class Job:
    id: str
    name: str
    description: str = ""
    users: list[str] = field(default_factory=list)
    all_users: bool = False
    sources: list[str] = field(default_factory=lambda: ["gmail", "drive"])
    include_shared_drives: bool = True
    retention: str = "policy:1W:1D,4W:1W,12M:1M"
    schedule: str = ""
    enabled: bool = True
    demo: bool = False
    source_state: dict = field(default_factory=dict)
    block_size: int | None = None
    volume_size: int | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class Run:
    id: str
    job_id: str
    status: str
    phase: str = "queued"
    started_at: str = ""
    finished_at: str | None = None
    error: str | None = None
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class FileSet:
    id: str
    job_id: str
    created_at: str
    volume_id: str
    file_count: int
    bytes: int

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class FileEntry:
    path: str
    source_id: str
    scope: str
    size: int
    mtime: str | None
    revision: str
    blockset_id: str
    content_hash: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class BlockRef:
    hash: str
    size: int
    volume_id: str

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class VolumeRef:
    id: str
    name: str
    kind: str
    size: int
    hash: str
    state: str
    created_at: str
    fileset_id: str | None = None
    counterpart: str | None = None
    block_count: int = 0

    def to_dict(self) -> dict:
        return _dump(self)


@dataclass
class SourceObject:
    source_id: str
    scope: str
    path: str
    revision: str
    mtime: str | None
    metadata: dict
    opener: Callable[[], Any] | None


@dataclass
class ScopeScan:
    scope: str
    mode: str
    objects: list[SourceObject]
    deleted_ids: list[str] = field(default_factory=list)


@dataclass
class Scan:
    scopes: list[ScopeScan]
    state: dict
    warnings: list[str] = field(default_factory=list)
