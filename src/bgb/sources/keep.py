from __future__ import annotations

from bgb.errors import UnsupportedSource
from bgb.models import Job, Scan


class KeepSource:
    """Placeholder for Google Keep.

    Google's Keep API is open to enterprise admins through domain-wide
    delegation, but its notes omit labels, colours, reminders, and pinned or
    archived state, so a restore would lose them. The plugin is registered so
    a Keep source can be added without changing the engine.
    """

    name = "keep"
    id_prefix = "keep:"

    def scan(self, job: Job) -> Scan:
        raise UnsupportedSource(
            "Google Keep is not supported yet. Google's Keep API omits labels, colours, reminders, "
            "and pinned or archived state, so a backup from it would not restore those."
        )
