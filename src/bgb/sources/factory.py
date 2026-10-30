from __future__ import annotations

from bgb.errors import ConfigError
from bgb.googleapi import (
    GoogleAuth,
    GoogleContactsClient,
    GoogleDirectory,
    GoogleDriveClient,
    GoogleGmailClient,
)
from bgb.models import Job, Settings
from bgb.sources.catalog import SUPPORTED_SOURCES
from bgb.sources.contacts import ContactsSource
from bgb.sources.demo import demo_sources
from bgb.sources.drive import DriveSource
from bgb.sources.gmail import GmailSource


def resolve_users(job: Job, settings: Settings, secrets) -> list[str]:
    if job.users:
        return [user.strip().lower() for user in job.users if user.strip()]
    if not job.all_users:
        raise ConfigError("Choose at least one user, or back up every user in the domain")
    if settings.auth_mode == "oauth":
        raise ConfigError("OAuth mode can only back up the user who granted consent. List that user explicitly.")
    auth = GoogleAuth(settings, secrets)
    return GoogleDirectory(auth, settings.admin_email).list_user_emails()


def build_sources(job: Job, settings: Settings, secrets):
    unknown = [name for name in job.sources if name not in SUPPORTED_SOURCES]
    if unknown:
        raise ConfigError(f"unsupported sources: {', '.join(unknown)}")
    if job.demo:
        return demo_sources(job)
    users = resolve_users(job, settings, secrets)
    if not users:
        raise ConfigError("the directory query returned no users")
    auth = GoogleAuth(settings, secrets)
    actor = (settings.admin_email or (users[0] if users else "")).lower()
    sources = []
    if "gmail" in job.sources:
        sources.append(GmailSource(GoogleGmailClient(auth), users))
    if "drive" in job.sources:
        sources.append(
            DriveSource(
                GoogleDriveClient(auth),
                users,
                include_shared=job.include_shared_drives,
                shared_actor=actor,
            )
        )
    if "contacts" in job.sources:
        sources.append(ContactsSource(GoogleContactsClient(auth), users))
    return sources


def probe_connection(settings: Settings, secrets) -> dict:
    if settings.auth_mode == "oauth":
        auth = GoogleAuth(settings, secrets)
        if not auth.available():
            return {
                "ok": True,
                "mode": "local",
                "detail": "No OAuth refresh token stored yet. Sample jobs still run without Google.",
            }
        return {
            "ok": True,
            "mode": "oauth",
            "detail": "OAuth refresh token is present. A backup will mint an access token on the first call.",
        }
    auth = GoogleAuth(settings, secrets)
    if not auth.available():
        return {
            "ok": True,
            "mode": "local",
            "detail": "No Workspace service account stored. Sample jobs still run against fixture mail and Drive.",
        }
    if not settings.admin_email:
        return {
            "ok": False,
            "mode": "service_account",
            "detail": "Set the Workspace admin email. Domain-wide delegation impersonates that user to list accounts.",
        }
    try:
        emails = GoogleDirectory(auth, settings.admin_email).list_user_emails()
    except Exception as exc:
        return {"ok": False, "mode": "service_account", "detail": str(exc)}
    return {
        "ok": True,
        "mode": "service_account",
        "detail": f"Directory API listed {len(emails)} users.",
    }
