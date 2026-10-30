from __future__ import annotations

SOURCE_CATALOG = [
    {
        "name": "gmail",
        "title": "Gmail",
        "supported": True,
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        "description": "Every message as an RFC822 (.eml) file, including labels. Incremental after the first run via the Gmail history API.",
    },
    {
        "name": "drive",
        "title": "Google Drive",
        "supported": True,
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "description": "My Drive for each selected user, plus each shared drive once. Docs, Sheets, Slides, and Drawings are exported.",
    },
    {
        "name": "contacts",
        "title": "Google Contacts",
        "supported": True,
        "scopes": ["https://www.googleapis.com/auth/contacts.readonly"],
        "description": "People API connections as JSON, one file per contact, with sync tokens for later runs.",
    },
    {
        "name": "keep",
        "title": "Google Keep",
        "supported": False,
        "scopes": [],
        "description": "No supported Workspace API. The plugin slot is reserved; Takeout is not a live source.",
    },
]

DIRECTORY_SCOPE = "https://www.googleapis.com/auth/admin.directory.user.readonly"
SUPPORTED_SOURCES = {item["name"] for item in SOURCE_CATALOG if item["supported"]}
