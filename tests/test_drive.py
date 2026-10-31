import hashlib
import io

from bgb.models import Job
from bgb.sources.drive import FOLDER, DriveSource
from bgb.util import now_iso
from tests.helpers import job, make_engine

PDF = b"P" * 128
SHEET = b"PK\x03\x04budget"


class FakeDrive:
    def __init__(self):
        self.files = {
            "folder": {
                "id": "folder",
                "name": "Policies",
                "mimeType": FOLDER,
                "parents": [],
                "trashed": False,
            },
            "handbook": {
                "id": "handbook",
                "name": "handbook.pdf",
                "mimeType": "application/pdf",
                "parents": ["folder"],
                "md5Checksum": hashlib.md5(PDF).hexdigest(),
                "modifiedTime": "2026-09-01T00:00:00Z",
                "trashed": False,
            },
            "budget": {
                "id": "budget",
                "name": "Budget",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": [],
                "modifiedTime": "2026-10-01T00:00:00Z",
                "trashed": False,
            },
            "form": {
                "id": "form",
                "name": "Parking",
                "mimeType": "application/vnd.google-apps.form",
                "parents": [],
                "trashed": False,
            },
            "link": {
                "id": "link",
                "name": "shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
                "parents": [],
                "trashed": False,
            },
            "trash": {
                "id": "trash",
                "name": "old.pdf",
                "mimeType": "application/pdf",
                "parents": [],
                "trashed": True,
                "md5Checksum": "abc",
            },
            "shared-folder": {
                "id": "shared-folder",
                "name": "Published",
                "mimeType": FOLDER,
                "parents": [],
                "driveId": "d1",
                "trashed": False,
            },
            "shared-pdf": {
                "id": "shared-pdf",
                "name": "handbook.pdf",
                "mimeType": "application/pdf",
                "parents": ["shared-folder"],
                "driveId": "d1",
                "md5Checksum": hashlib.md5(PDF).hexdigest(),
                "modifiedTime": "2026-09-01T00:00:00Z",
                "trashed": False,
            },
        }
        self.downloads: list[str] = []
        self.exports: list[str] = []
        self.changes = None
        self.expire = False

    def list_files(self, user, drive_id, page_token):
        if drive_id == "d1":
            ids = ["shared-folder", "shared-pdf"]
        elif user == "ada@example.com":
            ids = ["folder", "handbook", "budget", "form", "link", "trash"]
        else:
            ids = []
        return [self.files[item] for item in ids], None

    def list_shared_drives(self, user):
        return [{"id": "d1", "name": "Faculty Commons"}]

    def start_token(self, user, drive_id):
        return "t1"

    def list_changes(self, user, token, drive_id):
        if self.expire or token != "t1":
            return None
        return (
            self.changes if self.changes is not None else {"changes": [], "token": "t1"}
        )

    def get_file(self, user, file_id):
        if file_id not in self.files:
            raise FileNotFoundError(file_id)
        return self.files[file_id]

    def download(self, user, file_id):
        self.downloads.append(file_id)
        if file_id in {"handbook", "shared-pdf"}:
            return io.BytesIO(PDF)
        raise FileNotFoundError(file_id)

    def export(self, user, file_id, mime):
        self.exports.append(file_id)
        assert mime.endswith("spreadsheetml.sheet")
        return io.BytesIO(SHEET)


def test_drive_exports_docs_skips_unsupported_and_lists_shared_once():
    client = FakeDrive()
    source = DriveSource(
        client,
        ["ada@example.com", "grace@example.com"],
        include_shared=True,
        shared_actor="ada@example.com",
    )
    scan = source.scan(
        Job(id="j", name="n", include_shared_drives=True, created_at=now_iso())
    )
    paths = [obj.path for scope in scan.scopes for obj in scope.objects]
    assert "drive/users/ada@example.com/Policies/handbook.pdf" in paths
    assert "drive/users/ada@example.com/Budget.xlsx" in paths
    assert "drive/shared/d1/Published/handbook.pdf" in paths
    assert not any(
        "shortcut" in path or "Parking" in path or "old.pdf" in path for path in paths
    )
    assert any("form" in warning for warning in scan.warnings)
    ids = [obj.source_id for scope in scan.scopes for obj in scope.objects]
    assert ids.count("drive:shared-pdf") == 1
    assert ids.count("drive:handbook") == 1
    budget = next(
        obj
        for scope in scan.scopes
        for obj in scope.objects
        if obj.source_id == "drive:budget"
    )
    assert budget.opener().read() == SHEET
    handbook = next(
        obj
        for scope in scan.scopes
        for obj in scope.objects
        if obj.source_id == "drive:handbook"
    )
    assert handbook.opener().read() == PDF


def test_drive_rename_reuses_blocks_and_removal_drops_the_file(tmp_path):
    client = FakeDrive()
    source = DriveSource(
        client,
        ["ada@example.com"],
        include_shared=False,
        shared_actor="ada@example.com",
    )
    runtime, holder = make_engine(
        tmp_path, block_size=32, volume_size=10_000, source=source
    )
    holder["source"] = source
    runtime.index.upsert_job(
        job(
            users=["ada@example.com"],
            sources=["drive"],
            block_size=32,
            volume_size=10_000,
            include_shared_drives=False,
        )
    )
    runtime.engine.run_backup("job1")
    assert "handbook" in client.downloads
    assert "budget" in client.exports
    downloads = len(client.downloads)
    exports = len(client.exports)

    client.files["handbook"] = dict(client.files["handbook"], name="renamed.pdf")
    client.changes = {
        "changes": [
            {"fileId": "handbook", "removed": False, "file": client.files["handbook"]}
        ],
        "token": "t1",
    }
    second = runtime.engine.run_backup("job1")
    assert len(client.downloads) == downloads
    assert second.stats["files_read"] == 0
    fileset = runtime.index.list_filesets("job1")[0]
    paths = [row.path for row in runtime.index.iter_entries("job1", fileset.id)]
    assert "drive/users/ada@example.com/Policies/renamed.pdf" in paths

    client.changes = {
        "changes": [{"fileId": "handbook", "removed": True, "file": None}],
        "token": "t1",
    }
    runtime.engine.run_backup("job1")
    fileset = runtime.index.list_filesets("job1")[0]
    paths = [row.path for row in runtime.index.iter_entries("job1", fileset.id)]
    assert not any(path.endswith(("renamed.pdf", "handbook.pdf")) for path in paths)
    assert exports == len(client.exports)


def test_expired_change_token_falls_back_to_a_full_scan():
    client = FakeDrive()
    source = DriveSource(
        client, ["ada@example.com"], include_shared=False, shared_actor=""
    )
    job = Job(
        id="j",
        name="n",
        created_at=now_iso(),
        source_state={"drive": {"users": {"ada@example.com": {"token": "old"}}}},
    )
    client.expire = True
    scan = source.scan(job)
    assert scan.scopes[0].mode == "full"
    assert scan.state["users"]["ada@example.com"]["token"] == "t1"
