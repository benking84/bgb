from __future__ import annotations

from bgb.models import Job, Scan, ScopeScan, SourceObject

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


class DriveSource:
    """Backup My Drive for each user, and each shared drive once.

    Shared drives are listed as ``shared_actor`` (the Workspace admin, or the
    first user) so a file visible to several people is stored a single time.
    Google Docs, Sheets, Slides, and Drawings are exported. Other Docs types
    and shortcuts are skipped.
    """

    name = "drive"
    id_prefix = "drive:"

    def __init__(self, client, users: list[str], *, include_shared: bool, shared_actor: str):
        self.client = client
        self.users = [user.strip().lower() for user in users if user.strip()]
        self.include_shared = include_shared
        self.shared_actor = (shared_actor or "").strip().lower()

    def scan(self, job: Job) -> Scan:
        previous = (job.source_state or {}).get(self.name) or {}
        warnings: list[str] = []
        scopes: list[ScopeScan] = []
        user_state: dict[str, dict] = {}
        for user in self.users:
            scope, token, notes = self._scan_root(
                actor=user,
                drive_id=None,
                root=f"drive/users/{user}",
                scope_id=f"drive:user:{user}",
                cursor=(previous.get("users") or {}).get(user) or {},
            )
            warnings.extend(notes)
            scopes.append(scope)
            user_state[user] = {"token": token}
        shared_state: dict[str, dict] = {}
        if self.include_shared:
            actor = self.shared_actor or (self.users[0] if self.users else "")
            if not actor:
                warnings.append("shared drives skipped: no admin or user to list them")
            else:
                for drive in self.client.list_shared_drives(actor):
                    drive_id = drive["id"]
                    scope, token, notes = self._scan_root(
                        actor=actor,
                        drive_id=drive_id,
                        root=f"drive/shared/{drive_id}",
                        scope_id=f"drive:shared:{drive_id}",
                        cursor=(previous.get("shared") or {}).get(drive_id) or {},
                    )
                    warnings.extend(notes)
                    scopes.append(scope)
                    shared_state[drive_id] = {"token": token, "name": drive.get("name") or drive_id}
        return Scan(
            scopes=scopes,
            state={"users": user_state, "shared": shared_state},
            warnings=warnings,
        )

    def _scan_root(self, *, actor, drive_id, root, scope_id, cursor):
        token = (cursor or {}).get("token")
        if token:
            changes = self.client.list_changes(actor, token, drive_id)
            folder_edit = False
            if changes is not None:
                folder_edit = any(
                    ((change.get("file") or {}).get("mimeType") == FOLDER)
                    for change in changes.get("changes") or []
                )
            if changes is not None and not folder_edit:
                scope, notes = self._from_changes(actor, changes, root, scope_id)
                return scope, changes.get("token") or token, notes
        fresh = self.client.start_token(actor, drive_id)
        files = self._list_all(actor, drive_id)
        scope, notes = self._from_listing(actor, files, root, scope_id)
        return scope, fresh, notes

    def _list_all(self, actor: str, drive_id: str | None) -> list[dict]:
        files: list[dict] = []
        token = None
        while True:
            page, token = self.client.list_files(actor, drive_id, token)
            files.extend(page)
            if not token:
                break
        return files

    def _from_listing(self, actor, files, root, scope_id):
        by_id = {item["id"]: item for item in files}
        objects: list[SourceObject] = []
        warnings: list[str] = []
        skipped: set[str] = set()
        used: set[str] = set()
        for item in files:
            obj, skip = self._consider(actor, item, by_id.get, root, scope_id, used)
            if skip:
                skipped.add(skip)
            if obj:
                objects.append(obj)
        warnings.extend(_skip_warnings(skipped, root))
        return ScopeScan(scope=scope_id, mode="full", objects=objects), warnings

    def _from_changes(self, actor, changes, root, scope_id):
        cache: dict[str, dict | None] = {}
        for change in changes.get("changes") or []:
            file = change.get("file")
            if file and file.get("id"):
                cache[file["id"]] = file

        def lookup(file_id: str):
            if file_id not in cache:
                try:
                    cache[file_id] = self.client.get_file(actor, file_id)
                except FileNotFoundError:
                    cache[file_id] = None
            return cache[file_id]

        objects: list[SourceObject] = []
        deleted: list[str] = []
        skipped: set[str] = set()
        used: set[str] = set()
        for change in changes.get("changes") or []:
            file_id = change["fileId"]
            file = change.get("file")
            if change.get("removed") or (file or {}).get("trashed"):
                deleted.append(f"drive:{file_id}")
                continue
            if file is None:
                file = lookup(file_id)
            if not file:
                deleted.append(f"drive:{file_id}")
                continue
            obj, skip = self._consider(actor, file, lookup, root, scope_id, used)
            if skip:
                skipped.add(skip)
                if skip:
                    deleted.append(f"drive:{file_id}")
            elif obj:
                objects.append(obj)
        return (
            ScopeScan(scope=scope_id, mode="incremental", objects=objects, deleted_ids=deleted),
            _skip_warnings(skipped, root),
        )

    def _consider(self, actor, file, lookup, root, scope_id, used):
        mime = file.get("mimeType") or ""
        if file.get("trashed") or mime in {FOLDER, SHORTCUT}:
            return None, None
        export = EXPORTS.get(mime)
        if mime.startswith("application/vnd.google-apps.") and export is None:
            return None, mime
        file_id = file["id"]
        path = _unique(_join(root, _chain(file, lookup)), file_id, used)
        used.add(path)

        def open_file(owner: str = actor, fid: str = file_id, exported=export):
            # The client returns a stream, so a large file is never held in memory whole.
            if exported:
                return self.client.export(owner, fid, exported[0])
            return self.client.download(owner, fid)

        return (
            SourceObject(
                source_id=f"drive:{file_id}",
                scope=scope_id,
                path=path,
                revision=_revision(file),
                mtime=file.get("modifiedTime"),
                metadata={
                    "file_id": file_id,
                    "mime": mime,
                    "name": file.get("name") or file_id,
                    "drive_id": file.get("driveId") or "",
                    "md5": file.get("md5Checksum") or "",
                },
                opener=open_file,
            ),
            None,
        )


def _revision(file: dict) -> str:
    return str(file.get("md5Checksum") or file.get("headRevisionId") or file.get("modifiedTime") or file["id"])


def _display(file: dict) -> str:
    name = file.get("name") or file["id"]
    suffix = EXPORTS.get(file.get("mimeType") or "", (None, ""))[1]
    if suffix and not name.endswith(suffix):
        name = f"{name}{suffix}"
    return _segment(name)


def _segment(name: str) -> str:
    cleaned = name.replace("/", "_").replace("\\", "_").strip()
    if cleaned in {"", ".", ".."}:
        return "_"
    return cleaned


def _chain(file: dict, lookup) -> list[str]:
    names = [_display(file)]
    seen = {file["id"]}
    parents = file.get("parents") or []
    parent = parents[0] if parents else None
    while parent and parent not in seen:
        seen.add(parent)
        info = lookup(parent)
        if not info:
            break
        if info.get("mimeType") == FOLDER:
            names.append(_segment(info.get("name") or info["id"]))
        nxt = info.get("parents") or []
        parent = nxt[0] if nxt else None
    names.reverse()
    return names


def _join(root: str, names: list[str]) -> str:
    return "/".join([root, *names])


def _unique(path: str, file_id: str, used: set[str]) -> str:
    if path not in used:
        return path
    parent, _, leaf = path.rpartition("/")
    return f"{parent}/{leaf}~{file_id[-6:]}"


def _skip_warnings(skipped: set[str], root: str) -> list[str]:
    if not skipped:
        return []
    kinds = ", ".join(sorted(skipped))
    return [f"skipped unsupported Drive types under {root}: {kinds}"]
