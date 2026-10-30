from __future__ import annotations

from bgb.errors import UnsupportedSource
from bgb.models import Job, Scan


class KeepSource:
    """Placeholder for Google Keep.

    Keep has no supported Workspace API for domain-wide export. The plugin is
    registered so a future source can be added without changing the engine.
    """

    name = "keep"
    id_prefix = "keep:"

    def scan(self, job: Job) -> Scan:
        raise UnsupportedSource(
            "Google Keep has no supported Workspace API for domain-wide backup. "
            "Google Takeout is a one-shot export, not a source this service can poll."
        )
