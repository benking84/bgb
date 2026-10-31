---
status: blocked
---

# BMad Build Auto Result

Status: blocked
Blocking condition: unclear intent. The invocation named no story, spec file or description to implement.

Notes for the next run:
- Pass a story, for example `2-2-runs-that-die-are-marked-timed-out` (first backlog story with new work in Epic 2), or a spec file path.
- The working tree is not clean (uncommitted planning files and other sessions' changes to `pyproject.toml`, `tests/helpers.py`, `tests/integration/`), so step 1's version-control check would also halt until that is resolved.
- This workflow requires blocking (synchronous) subagents; in this session subagents run in the background, which the workflow does not allow.
