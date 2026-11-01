from __future__ import annotations

import hashlib
import io
import json

from bgb.models import Job, Scan, ScopeScan, SourceObject


class ContactsSource:
    """Backup People API connections as one JSON object per contact."""

    name = "contacts"
    id_prefix = "contacts:"

    def __init__(self, client, users: list[str]):
        self.client = client
        self.users = [user.strip().lower() for user in users if user.strip()]

    def scan(self, job: Job) -> Scan:
        previous = ((job.source_state or {}).get(self.name) or {}).get("users") or {}
        scopes: list[ScopeScan] = []
        warnings: list[str] = []
        users: dict[str, dict] = {}
        for user in self.users:
            cursor = (previous.get(user) or {}).get("sync_token")
            if cursor:
                page = self._drain(user, sync_token=cursor)
                if page is None:
                    warnings.append(
                        f"Contacts sync token for {user} expired; listing the address book"
                    )
                    people, token = self._full(user)
                    scopes.append(self._scope_full(user, people))
                else:
                    people, deleted, token = page
                    scopes.append(self._scope_incremental(user, people, deleted))
            else:
                people, token = self._full(user)
                scopes.append(self._scope_full(user, people))
            users[user] = {"sync_token": token or ""}
        return Scan(scopes=scopes, state={"users": users}, warnings=warnings)

    def _full(self, user: str) -> tuple[list[dict], str | None]:
        people: list[dict] = []
        token = None
        sync = None
        while True:
            page = self.client.list_connections(user, page_token=token, sync_token=None)
            people.extend(page.get("people") or [])
            sync = page.get("sync_token") or sync
            token = page.get("next_page")
            if not token:
                break
        return people, sync

    def _drain(self, user: str, sync_token: str):
        people: list[dict] = []
        deleted: list[str] = []
        token = None
        sync = sync_token
        first = True
        while True:
            page = self.client.list_connections(
                user,
                page_token=token,
                sync_token=sync_token if first else None,
            )
            first = False
            if page is None or page.get("expired"):
                return None
            people.extend(page.get("people") or [])
            deleted.extend(page.get("deleted") or [])
            sync = page.get("sync_token") or sync
            token = page.get("next_page")
            if not token:
                break
        return people, deleted, sync

    def _scope_full(self, user: str, people: list[dict]) -> ScopeScan:
        return ScopeScan(
            scope=f"contacts:{user}",
            mode="full",
            objects=[self._object(user, person) for person in people],
        )

    def _scope_incremental(
        self, user: str, people: list[dict], deleted: list[str]
    ) -> ScopeScan:
        return ScopeScan(
            scope=f"contacts:{user}",
            mode="incremental",
            objects=[self._object(user, person) for person in people],
            deleted_ids=[f"contacts:{user}:{resource}" for resource in deleted],
        )

    def _object(self, user: str, person: dict) -> SourceObject:
        resource = person.get("resourceName") or "unknown"
        payload = json.dumps(person, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(payload).hexdigest()
        leaf = resource.split("/")[-1]

        def open_person(body: bytes = payload):
            return io.BytesIO(body)

        return SourceObject(
            source_id=f"contacts:{user}:{resource}",
            scope=f"contacts:{user}",
            path=f"contacts/{user}/{leaf}.json",
            revision=digest,
            mtime=None,
            metadata={"resource": resource, "user": user},
            opener=open_person,
        )
