from __future__ import annotations

import hashlib
import io

from bgb.models import Job
from bgb.sources.contacts import ContactsSource
from bgb.sources.drive import FOLDER, DriveSource
from bgb.sources.gmail import GmailSource

HANDBOOK = ("The Northwind faculty handbook. " * 80).encode()
BUDGET_EXPORT = b"PK\x03\x04northwind-budget-sheet"
NOTES = b"Grace's lab notes\nDo not file the handbook twice.\n"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class DemoGmail:
    def __init__(self):
        self.messages = {
            "ada@northwind.example": {
                "m-welcome": {
                    "id": "m-welcome",
                    "labelIds": ["INBOX", "UNREAD"],
                    "internalDate": "1760000000000",
                    "snippet": "Welcome to Northwind",
                    "subject": "Welcome to Northwind",
                    "raw": b"Subject: Welcome to Northwind\r\n\r\nThe term starts Monday.\r\n",
                },
                "m-policy": {
                    "id": "m-policy",
                    "labelIds": ["INBOX"],
                    "internalDate": "1760100000000",
                    "snippet": "Please read the handbook",
                    "subject": "Handbook",
                    "raw": b"Subject: Handbook\r\n\r\nThe handbook is in Drive.\r\n",
                },
            },
            "grace@northwind.example": {
                "m-notes": {
                    "id": "m-notes",
                    "labelIds": ["INBOX"],
                    "internalDate": "1760200000000",
                    "snippet": "Lab notes",
                    "subject": "Lab notes",
                    "raw": b"Subject: Lab notes\r\n\r\nSee the shared drive.\r\n",
                }
            },
        }
        self.raw_reads: list[tuple[str, str]] = []

    def get_profile(self, user: str) -> dict:
        return {"emailAddress": user, "historyId": "10"}

    def list_message_ids(self, user: str, page_token: str | None):
        return list(self.messages.get(user, {})), None

    def get_metadata(self, user: str, message_id: str) -> dict:
        row = self.messages[user][message_id]
        return {
            key: row[key]
            for key in ("id", "labelIds", "internalDate", "snippet", "subject")
        }

    def get_message(self, user: str, message_id: str) -> dict:
        self.raw_reads.append((user, message_id))
        return dict(
            self.get_metadata(user, message_id),
            raw=self.messages[user][message_id]["raw"],
        )

    def list_history(self, user: str, start: str):
        if start != "10":
            return None
        return {"historyId": "10", "records": []}


class DemoDrive:
    def __init__(self):
        handbook = {
            "mimeType": "application/pdf",
            "md5Checksum": _md5(HANDBOOK),
            "modifiedTime": "2026-09-01T00:00:00Z",
            "size": str(len(HANDBOOK)),
            "trashed": False,
        }
        self.files = {
            "folder-ada": {
                "id": "folder-ada",
                "name": "Policies",
                "mimeType": FOLDER,
                "parents": [],
                "trashed": False,
            },
            "ada-handbook": {
                "id": "ada-handbook",
                "name": "handbook.pdf",
                "parents": ["folder-ada"],
                **handbook,
            },
            "ada-budget": {
                "id": "ada-budget",
                "name": "Budget",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": [],
                "modifiedTime": "2026-10-01T00:00:00Z",
                "trashed": False,
            },
            "ada-form": {
                "id": "ada-form",
                "name": "Parking form",
                "mimeType": "application/vnd.google-apps.form",
                "parents": [],
                "trashed": False,
            },
            "grace-notes": {
                "id": "grace-notes",
                "name": "notes.txt",
                "mimeType": "text/plain",
                "parents": [],
                "md5Checksum": _md5(NOTES),
                "modifiedTime": "2026-08-01T00:00:00Z",
                "size": str(len(NOTES)),
                "trashed": False,
            },
            "shared-handbook": {
                "id": "shared-handbook",
                "name": "handbook.pdf",
                "parents": ["folder-shared"],
                "driveId": "drive-commons",
                **handbook,
            },
            "folder-shared": {
                "id": "folder-shared",
                "name": "Published",
                "mimeType": FOLDER,
                "parents": [],
                "driveId": "drive-commons",
                "trashed": False,
            },
        }
        self.by_owner = {
            "ada@northwind.example": [
                "folder-ada",
                "ada-handbook",
                "ada-budget",
                "ada-form",
            ],
            "grace@northwind.example": ["grace-notes"],
        }
        self.shared = {
            "drive-commons": ["folder-shared", "shared-handbook"],
        }
        self.shared_meta = [{"id": "drive-commons", "name": "Faculty Commons"}]
        self.downloads: list[str] = []
        self.exports: list[str] = []

    def list_files(self, user: str, drive_id: str | None, page_token: str | None):
        if drive_id:
            ids = self.shared.get(drive_id, [])
        else:
            ids = self.by_owner.get(user, [])
        return [self.files[item] for item in ids], None

    def list_shared_drives(self, user: str) -> list[dict]:
        return list(self.shared_meta)

    def start_token(self, user: str, drive_id: str | None) -> str:
        return "t1"

    def list_changes(self, user: str, token: str, drive_id: str | None):
        if token != "t1":
            return None
        return {"changes": [], "token": "t1"}

    def get_file(self, user: str, file_id: str) -> dict:
        if file_id not in self.files:
            raise FileNotFoundError(file_id)
        return self.files[file_id]

    def download(self, user: str, file_id: str) -> io.BytesIO:
        self.downloads.append(file_id)
        if file_id in {"ada-handbook", "shared-handbook"}:
            return io.BytesIO(HANDBOOK)
        if file_id == "grace-notes":
            return io.BytesIO(NOTES)
        raise FileNotFoundError(file_id)

    def export(self, user: str, file_id: str, mime: str) -> io.BytesIO:
        self.exports.append(file_id)
        if file_id == "ada-budget":
            return io.BytesIO(BUDGET_EXPORT)
        raise FileNotFoundError(file_id)


class DemoContacts:
    def __init__(self):
        self.people = {
            "ada@northwind.example": [
                {
                    "resourceName": "people/c-ada",
                    "names": [{"displayName": "Ada Lovelace"}],
                    "emailAddresses": [{"value": "ada@northwind.example"}],
                }
            ],
            "grace@northwind.example": [
                {
                    "resourceName": "people/c-grace",
                    "names": [{"displayName": "Grace Hopper"}],
                    "emailAddresses": [{"value": "grace@northwind.example"}],
                }
            ],
        }

    def list_connections(
        self, user: str, page_token: str | None = None, sync_token: str | None = None
    ):
        if sync_token:
            if sync_token != "s1":
                return {
                    "expired": True,
                    "people": [],
                    "deleted": [],
                    "next_page": None,
                    "sync_token": None,
                }
            return {
                "expired": False,
                "people": [],
                "deleted": [],
                "next_page": None,
                "sync_token": "s1",
            }
        return {
            "expired": False,
            "people": list(self.people.get(user, [])),
            "deleted": [],
            "next_page": None,
            "sync_token": "s1",
        }


class DemoDirectory:
    def list_user_emails(self) -> list[str]:
        return ["ada@northwind.example", "grace@northwind.example"]


def demo_sources(job: Job):
    users = [
        user.strip().lower() for user in job.users
    ] or DemoDirectory().list_user_emails()
    gmail = DemoGmail()
    drive = DemoDrive()
    contacts = DemoContacts()
    sources = []
    if "gmail" in job.sources:
        sources.append(GmailSource(gmail, users))
    if "drive" in job.sources:
        actor = users[0] if users else ""
        sources.append(
            DriveSource(
                drive,
                users,
                include_shared=job.include_shared_drives,
                shared_actor=actor,
            )
        )
    if "contacts" in job.sources:
        sources.append(ContactsSource(contacts, users))
    return sources
