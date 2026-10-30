from __future__ import annotations

import base64
import io
import json
import time

from bgb.errors import ConfigError, SecretNotFound
from bgb.sources.catalog import DIRECTORY_SCOPE, SOURCE_CATALOG

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CONTACTS_SCOPES = ["https://www.googleapis.com/auth/contacts.readonly"]
ADMIN_SCOPES = [DIRECTORY_SCOPE]
OAUTH_SCOPES = GMAIL_SCOPES + DRIVE_SCOPES + CONTACTS_SCOPES


def _execute(build_request, attempts: int = 5):
    from googleapiclient.errors import HttpError

    last = None
    for attempt in range(attempts):
        try:
            return build_request().execute()
        except HttpError as exc:
            last = exc
            status = getattr(exc.resp, "status", None)
            if status in {429, 500, 503} and attempt + 1 < attempts:
                time.sleep(min(2**attempt, 16))
                continue
            raise
    raise last  # pragma: no cover


def _b64(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _message_ids(rows) -> list[str]:
    found = []
    for row in rows or []:
        if isinstance(row, str):
            found.append(row)
        elif isinstance(row, dict) and "message" in row:
            found.append(row["message"]["id"])
        elif isinstance(row, dict) and "id" in row:
            found.append(row["id"])
    return found


class GoogleAuth:
    def __init__(self, settings, secrets):
        self.settings = settings
        self.secrets = secrets
        self._services: dict = {}

    def available(self) -> bool:
        if self.settings.auth_mode == "oauth":
            try:
                self.secrets.get(self.settings.oauth_secret)
                return True
            except SecretNotFound:
                return False
        if self._service_account_info() is not None:
            return True
        return bool(self.settings.service_account_email)

    def service(self, api: str, version: str, subject: str, scopes: list[str]):
        key = (api, version, subject, tuple(scopes), self.settings.auth_mode)
        if key not in self._services:
            from googleapiclient.discovery import build

            creds = self.credentials(subject, scopes)
            self._services[key] = build(api, version, credentials=creds, cache_discovery=False)
        return self._services[key]

    def credentials(self, subject: str, scopes: list[str]):
        if self.settings.auth_mode == "oauth":
            return self._oauth(scopes)
        info = self._service_account_info()
        from google.oauth2 import service_account

        if info is not None:
            base = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            return base.with_subject(subject)
        email = self.settings.service_account_email
        if not email:
            raise ConfigError(
                "No Workspace service account. Put the JSON key in Secret Manager "
                f"({self.settings.service_account_secret}) or set the service account email for keyless signing."
            )
        import google.auth
        from google.auth import iam
        from google.auth.transport.requests import Request

        source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        signer = iam.Signer(Request(), source, email)
        return service_account.Credentials(
            signer=signer,
            service_account_email=email,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=scopes,
            subject=subject,
        )

    def _oauth(self, scopes: list[str]):
        from google.oauth2.credentials import Credentials

        try:
            raw = self.secrets.get(self.settings.oauth_secret)
        except SecretNotFound as exc:
            raise ConfigError(
                f"OAuth client secret {self.settings.oauth_secret} was not found"
            ) from exc
        data = json.loads(raw)
        return Credentials(
            token=None,
            refresh_token=data["refresh_token"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=scopes,
        )

    def _service_account_info(self):
        try:
            raw = self.secrets.get(self.settings.service_account_secret)
        except SecretNotFound:
            return None
        if not raw.strip():
            return None
        return json.loads(raw)


class GoogleGmailClient:
    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    def _svc(self, user: str):
        return self.auth.service("gmail", "v1", user, GMAIL_SCOPES)

    def get_profile(self, user: str) -> dict:
        return _execute(lambda: self._svc(user).users().getProfile(userId=user))

    def list_message_ids(self, user: str, page_token: str | None):
        response = _execute(
            lambda: self._svc(user).users().messages().list(
                userId=user, pageToken=page_token, maxResults=500
            )
        )
        return [row["id"] for row in response.get("messages") or []], response.get("nextPageToken")

    def get_metadata(self, user: str, message_id: str) -> dict:
        response = _execute(
            lambda: self._svc(user).users().messages().get(
                userId=user,
                id=message_id,
                format="metadata",
                metadataHeaders=["Subject"],
            )
        )
        subject = ""
        for header in (response.get("payload") or {}).get("headers") or []:
            if str(header.get("name", "")).lower() == "subject":
                subject = header.get("value") or ""
        return {
            "id": response["id"],
            "labelIds": response.get("labelIds") or [],
            "internalDate": response.get("internalDate"),
            "snippet": response.get("snippet") or "",
            "subject": subject,
        }

    def get_raw(self, user: str, message_id: str) -> bytes:
        response = _execute(
            lambda: self._svc(user).users().messages().get(userId=user, id=message_id, format="raw")
        )
        return _b64(response["raw"])

    def list_history(self, user: str, start: str):
        from googleapiclient.errors import HttpError

        records = []
        token = None
        history_id = start
        try:
            while True:
                response = _execute(
                    lambda token=token: self._svc(user).users().history().list(
                        userId=user,
                        startHistoryId=start,
                        pageToken=token,
                        historyTypes=["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
                    )
                )
                history_id = str(response.get("historyId") or history_id)
                for item in response.get("history") or []:
                    records.append(
                        {
                            "added": _message_ids(item.get("messagesAdded")),
                            "deleted": _message_ids(item.get("messagesDeleted")),
                            "label_changed": _message_ids(item.get("labelsAdded"))
                            + _message_ids(item.get("labelsRemoved")),
                        }
                    )
                token = response.get("nextPageToken")
                if not token:
                    break
        except HttpError as exc:
            if getattr(exc.resp, "status", None) in {400, 404}:
                return None
            raise
        return {"historyId": history_id, "records": records}


_DRIVE_FIELDS = (
    "id,name,mimeType,size,md5Checksum,modifiedTime,parents,driveId,headRevisionId,trashed"
)


class GoogleDriveClient:
    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    def _svc(self, user: str):
        return self.auth.service("drive", "v3", user, DRIVE_SCOPES)

    def list_files(self, user: str, drive_id: str | None, page_token: str | None):
        kwargs = {
            "pageSize": 1000,
            "supportsAllDrives": True,
            "fields": f"nextPageToken, files({_DRIVE_FIELDS})",
            "q": "trashed = false",
            "pageToken": page_token,
        }
        if drive_id:
            kwargs["corpora"] = "drive"
            kwargs["driveId"] = drive_id
            kwargs["includeItemsFromAllDrives"] = True
        else:
            kwargs["corpora"] = "user"
            kwargs["includeItemsFromAllDrives"] = False
        response = _execute(lambda: self._svc(user).files().list(**kwargs))
        return response.get("files") or [], response.get("nextPageToken")

    def list_shared_drives(self, user: str) -> list[dict]:
        drives = []
        token = None
        while True:
            response = _execute(lambda token=token: self._svc(user).drives().list(pageSize=100, pageToken=token))
            drives.extend({"id": row["id"], "name": row.get("name") or row["id"]} for row in response.get("drives") or [])
            token = response.get("nextPageToken")
            if not token:
                return drives

    def start_token(self, user: str, drive_id: str | None) -> str:
        kwargs = {"supportsAllDrives": True}
        if drive_id:
            kwargs["driveId"] = drive_id
        response = _execute(lambda: self._svc(user).changes().getStartPageToken(**kwargs))
        return response["startPageToken"]

    def list_changes(self, user: str, token: str, drive_id: str | None):
        from googleapiclient.errors import HttpError

        changes = []
        page = token
        new_token = token
        try:
            while True:
                kwargs = {
                    "pageToken": page,
                    "includeRemoved": True,
                    "supportsAllDrives": True,
                    "pageSize": 1000,
                    "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({_DRIVE_FIELDS}))",
                }
                if drive_id:
                    kwargs["driveId"] = drive_id
                    kwargs["includeItemsFromAllDrives"] = True
                else:
                    kwargs["restrictToMyDrive"] = True
                    kwargs["includeItemsFromAllDrives"] = False
                response = _execute(lambda kwargs=kwargs: self._svc(user).changes().list(**kwargs))
                changes.extend(response.get("changes") or [])
                if response.get("newStartPageToken"):
                    new_token = response["newStartPageToken"]
                page = response.get("nextPageToken")
                if not page:
                    break
        except HttpError as exc:
            if getattr(exc.resp, "status", None) in {400, 404}:
                return None
            raise
        return {"changes": changes, "token": new_token}

    def get_file(self, user: str, file_id: str) -> dict:
        from googleapiclient.errors import HttpError

        try:
            return _execute(
                lambda: self._svc(user).files().get(
                    fileId=file_id, supportsAllDrives=True, fields=_DRIVE_FIELDS
                )
            )
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 404:
                raise FileNotFoundError(file_id) from exc
            raise

    def download(self, user: str, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        request = self._svc(user).files().get_media(fileId=file_id, supportsAllDrives=True)
        return _download(request)

    def export(self, user: str, file_id: str, mime: str) -> bytes:
        request = self._svc(user).files().export_media(fileId=file_id, mimeType=mime)
        return _download(request)


def _download(request) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


class GoogleDirectory:
    def __init__(self, auth: GoogleAuth, admin_email: str):
        self.auth = auth
        self.admin_email = admin_email

    def list_user_emails(self) -> list[str]:
        if not self.admin_email:
            raise ConfigError("admin_email is required to list Workspace users")
        service = self.auth.service("admin", "directory_v1", self.admin_email, ADMIN_SCOPES)
        emails: list[str] = []
        token = None
        while True:
            response = _execute(
                lambda token=token: service.users().list(
                    customer="my_customer",
                    maxResults=500,
                    orderBy="email",
                    query="isSuspended=false",
                    pageToken=token,
                )
            )
            emails.extend(row["primaryEmail"].lower() for row in response.get("users") or [] if row.get("primaryEmail"))
            token = response.get("nextPageToken")
            if not token:
                return emails


class GoogleContactsClient:
    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    def list_connections(self, user: str, page_token: str | None = None, sync_token: str | None = None):
        from googleapiclient.errors import HttpError

        service = self.auth.service("people", "v1", user, CONTACTS_SCOPES)
        kwargs = {
            "resourceName": "people/me",
            "pageSize": 1000,
            "personFields": "names,emailAddresses,phoneNumbers,organizations,biographies,metadata",
            "requestSyncToken": True,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if sync_token:
            kwargs["syncToken"] = sync_token
        try:
            response = _execute(lambda: service.people().connections().list(**kwargs))
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 410:
                return {"expired": True, "people": [], "deleted": [], "next_page": None, "sync_token": None}
            raise
        people = []
        deleted = []
        for person in response.get("connections") or []:
            if (person.get("metadata") or {}).get("deleted"):
                if person.get("resourceName"):
                    deleted.append(person["resourceName"])
            else:
                people.append(person)
        return {
            "expired": False,
            "people": people,
            "deleted": deleted,
            "next_page": response.get("nextPageToken"),
            "sync_token": response.get("nextSyncToken"),
        }


def required_scopes(include_directory: bool) -> list[str]:
    scopes: list[str] = []
    for item in SOURCE_CATALOG:
        if item["supported"]:
            scopes.extend(item["scopes"])
    if include_directory:
        scopes.append(DIRECTORY_SCOPE)
    return list(dict.fromkeys(scopes))
