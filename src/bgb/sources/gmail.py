from __future__ import annotations

import io
from datetime import datetime, timezone

from bgb.models import Job, Scan, ScopeScan, SourceObject


class GmailSource:
    """Backup each user's mailbox as one RFC822 object per message.

    Messages are addressed by id, so label changes do not re-read the body.
    Incremental runs use users.history when the stored history id is still valid.
    New messages are read with one raw fetch, which also returns labels and date,
    so a full scan lists ids only. Only label-only changes call the metadata endpoint.
    """

    name = "gmail"
    id_prefix = "gmail:"

    def __init__(self, client, users: list[str]):
        self.client = client
        self.users = [user.strip().lower() for user in users if user.strip()]

    def scan(self, job: Job) -> Scan:
        previous = ((job.source_state or {}).get(self.name) or {}).get("users") or {}
        scopes: list[ScopeScan] = []
        warnings: list[str] = []
        new_users: dict[str, dict] = {}
        for user in self.users:
            profile = self.client.get_profile(user)
            history_id = str(profile["historyId"])
            cursor = (previous.get(user) or {}).get("history_id")
            if not cursor:
                scopes.append(self._full(user))
            else:
                history = self.client.list_history(user, cursor)
                if history is None:
                    warnings.append(f"Gmail history for {user} expired; scanning the mailbox")
                    scopes.append(self._full(user))
                else:
                    scopes.append(self._incremental(user, history))
                    history_id = str(history.get("historyId") or history_id)
            new_users[user] = {"history_id": history_id}
        return Scan(scopes=scopes, state={"users": new_users}, warnings=warnings)

    def _full(self, user: str) -> ScopeScan:
        objects: list[SourceObject] = []
        token = None
        while True:
            ids, token = self.client.list_message_ids(user, token)
            objects.extend(self._object(user, {"id": message_id}) for message_id in ids)
            if not token:
                break
        return ScopeScan(scope=f"gmail:{user}", mode="full", objects=objects)

    def _incremental(self, user: str, history: dict) -> ScopeScan:
        state: dict[str, str] = {}
        deleted: set[str] = set()
        for record in history.get("records") or []:
            for message_id in record.get("deleted") or []:
                deleted.add(message_id)
                state.pop(message_id, None)
            for message_id in record.get("added") or []:
                deleted.discard(message_id)
                state[message_id] = "added"
            for message_id in record.get("label_changed") or []:
                if message_id not in deleted and message_id not in state:
                    state[message_id] = "labels"
        objects = [
            self._object(user, self.client.get_metadata(user, message_id) if kind == "labels" else {"id": message_id})
            for message_id, kind in state.items()
        ]
        deleted_ids = [f"gmail:{user}:{message_id}" for message_id in deleted]
        return ScopeScan(
            scope=f"gmail:{user}",
            mode="incremental",
            objects=objects,
            deleted_ids=deleted_ids,
        )

    def _object(self, user: str, meta: dict) -> SourceObject:
        """Build the object. Fields missing from ``meta`` are filled when the body is read."""
        message_id = meta["id"]
        obj = SourceObject(
            source_id=f"gmail:{user}:{message_id}",
            scope=f"gmail:{user}",
            path=f"gmail/{user}/messages/{message_id}.eml",
            revision=message_id,
            mtime=_from_millis(meta.get("internalDate")),
            metadata=_metadata(user, meta) if "labelIds" in meta else {},
            opener=None,
        )

        def open_raw(owner: str = user, mid: str = message_id):
            message = self.client.get_message(owner, mid)
            raw = message["raw"]
            obj.metadata.update(_metadata(owner, dict(message, subject=_subject(raw))))
            obj.mtime = obj.mtime or _from_millis(message.get("internalDate"))
            return io.BytesIO(raw)

        obj.opener = open_raw
        return obj


def _metadata(user: str, meta: dict) -> dict:
    return {
        "subject": meta.get("subject") or "",
        "labels": list(meta.get("labelIds") or []),
        "snippet": meta.get("snippet") or "",
        "user": user,
    }


def _subject(raw: bytes) -> str:
    from email.header import decode_header, make_header
    from email.parser import BytesHeaderParser

    try:
        value = BytesHeaderParser().parsebytes(raw[:65536]).get("Subject") or ""
        return str(make_header(decode_header(value)))
    except Exception:
        return ""


def _from_millis(value) -> str | None:
    if not value:
        return None
    try:
        stamp = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
