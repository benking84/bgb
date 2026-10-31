# Epic 9: Workspace Source Coverage: Keep, Chat, Calendar and Tasks

**Status:** Draft for review
**Author:** Ben, with Claude
**Date:** 2026-10-31
**Scope:** bgb repository (`src/bgb/sources/`, `src/bgb/googleapi.py`, `web/`, `README.md`, `REVIEW.md`)
**Related:** Epic 3 in `epics.md` (every user, mailbox and drive covered, failures named) sets the rules for warnings and failed users that these new sources must follow.
**Builds on:** Epic 1 test conventions (priorities, recorded Google API responses in Story 1.6, integrity suite in Story 1.5). No dependency on Epic 8 beyond a working PR pipeline.

---

## 1. Goal

A bgb backup covers the Workspace data a user would expect to get back after an account is deleted or damaged, not only mail and files.

1. **Keep is backed up**, not refused, with its gaps stated. The Keep API omits labels, colours, reminders and pinned or archived state, so those are not captured. Note text, checklists and attachments are.
2. **Chat is backed up**: spaces, group chats and direct messages the user belongs to, with attachments.
3. **Calendar and Tasks are backed up**, since they are small, have clean read APIs, and are commonly missed.
4. Every source says clearly what it does not cover, in the UI and the README, so nobody assumes a backup is complete when it is not.

## 2. Current coverage (observed in the repo)

| Workspace data | Today | Notes |
|---|---|---|
| Gmail | Backed up | `.eml` per message, history ID incremental |
| Drive (My Drive, shared drives) | Backed up | Docs, Sheets, Slides, Drawings exported. Forms and shortcuts skipped and reported |
| Contacts | Backed up | People API connections, sync token incremental |
| Keep | **Refused** | `catalog.py` marks it unsupported and `keep.py` raises `UnsupportedSource`. The architecture research branch (`_bmad-output/planning-artifacts/research/technical-google-workspace-backup-architecture-rev-2026-10-31/`) updated the reason: the API exists but omits labels, colours, reminders and pinned or archived state |
| Chat | Not present | |
| Calendar | Not present | |
| Tasks | Not present | |
| Forms (structure and responses) | Skipped by Drive | See open question Q3 |
| Groups conversations, Sites, Vault holds | Not present | Out of scope, see section 6 |

## 3. What the APIs allow (checked 2026-10-31)

Checked against Google's developer documentation and, for Chat, secondary sources. Each source story starts with a spike to confirm the points marked "confirm" in a real domain before building.

| Source | API and scope | Access model | Confirm in spike |
|---|---|---|---|
| Keep | Google Keep API v1, `https://www.googleapis.com/auth/keep.readonly`. `notes.list` (filter on `createTime`, `updateTime`, `trashTime`, `trashed`), notes get, attachment download through `media.download` | Built for Workspace administrators. A service account with domain-wide delegation can impersonate any user in the domain. **Not available from the API:** labels, colours, reminders, pinned and archived state (architecture research, 2026-10-31) | Whether `notes.list` returns notes shared with the user as well as owned notes; how checklists, labels and permissions appear in the `Note` resource; whether trashed notes should be kept |
| Chat | Google Chat API v1, `chat.spaces.readonly`, `chat.messages.readonly`, plus `chat.memberships.readonly` for member lists | User authentication. The `chat.app.*` scopes cannot be used with domain-wide delegation, so bgb impersonates each user with delegation and reads the spaces that user is in | That delegation with these user scopes is accepted in the domain; behaviour for spaces that include external users (one developer report says message listing fails for them); how attachments stored in Drive versus uploaded to Chat are downloaded; incremental strategy for edited and deleted messages |
| Calendar | Calendar API v3, `calendar.readonly`. `calendarList.list`, `events.list` with `syncToken` | Delegation, per user | Handling of recurring events (store the series and exceptions, not expanded instances); calendars the user subscribes to but does not own |
| Tasks | Tasks API v1, `tasks.readonly`. `tasklists.list`, `tasks.list` with `updatedMin` and `showDeleted` | Delegation, per user | Whether `updatedMin` with `showDeleted` and `showHidden` is enough to detect every change |

**Every new scope must be added to the domain-wide delegation entry in the Admin console before it works.** A customer who upgrades bgb without doing that gets permission errors. Story 9.1 handles this.

## 4. Assumptions and decisions

| # | Item | Impact if wrong |
|---|---|---|
| A1 | Each new source follows the existing plugin contract (`scan(job) -> Scan` with full and incremental `ScopeScan`s and a per user cursor in `source_state`), like `ContactsSource`. The engine, retention and dedup do not change. | If Chat volume needs a different shape (for example one file per message is too many objects), Story 9.3 records the alternative before building it. |
| A2 | Stored format is the API's own JSON, one file per item, plus attachments as their original bytes. No conversion to other formats in this epic (for example no `.ics` for Calendar). | A human readable export can be added later from the JSON. |
| A3 | OAuth mode (single user) gets the same new scopes as service account mode, so a single user can back up their own Keep, Chat, Calendar and Tasks. | If a scope is not grantable in OAuth mode for this OAuth client, that source is marked service account only in the catalog. |
| A4 | Shared objects are stored once. A Chat space with five members is backed up once, not five times, using the same pattern Drive uses for shared drives. Block level dedup would save the bytes anyway, but a single copy keeps the fileset readable. | None expected. |
| D2 | **Decided 2026-10-31 (Ben): back up Keep with its gaps flagged**, rather than leave it unsupported. A partial copy of note content is better than none, provided nobody is led to think it is complete. | If customers rely on labels or reminders, Keep restore will not bring them back. Story 9.2 and Story 9.6 must say so wherever Keep is offered. |
| D1 | **Decision needed:** should trashed Keep notes, deleted Chat messages (where the API exposes them) and deleted Tasks be kept in the backup until retention removes them? | Recommendation: yes. A backup that drops an item the moment it is deleted does not protect against deletion. Retention already handles old versions. |

## 5. Stories

Stories 9.1 and 9.2 should land first. Keep is the source the product currently says it cannot back up, and the scope changes in 9.1 are needed by every later story.

---

### Story 9.1: Source catalog, scopes and delegation check

**As** an administrator, **I want** bgb to tell me exactly which scopes to authorise and to check them before a run, **so that** adding a source does not fail halfway through a backup with a permission error.

**Acceptance criteria**
- `SOURCE_CATALOG` lists Keep (supported), Chat, Calendar and Tasks, each with its scopes and a one line description that states what is not covered.
- `required_scopes()` returns the union for the selected sources, and the README delegation table is generated from, or checked against, the catalog in a unit test, so they cannot drift.
- The settings connection probe checks every scope needed by the sources in saved jobs, by requesting a delegated token for the admin user with each scope, and reports the missing ones by name.
- A job that selects a source whose scope is missing fails before any upload, with a message naming the scope and the Admin console path.
- OAuth mode requests the new scopes (A3).

**Tasks**
- [ ] Extend `catalog.py` and `googleapi.py` scope constants.
- [ ] Add the scope check to `probe_connection` and to job start.
- [ ] Update the README delegation table and the upgrade note: "after upgrading, add these scopes to the delegation entry".
- [ ] Tests: catalog and README agree (P1); missing scope fails fast with a clear message (P1).

---

### Story 9.2: Back up Google Keep

**As** a Workspace user, **I want** my Keep notes, checklists and attachments backed up, **so that** I can recover them if they are deleted or my account is lost.

**Acceptance criteria**
- **Gaps are stated (D2):** the catalog description, the job form, each Keep run summary and the README say that labels, colours, reminders and pinned or archived state are not backed up, because the Keep API does not expose them.
- Spike first (section 3): the result is recorded in the story notes, including whether shared notes are returned and how they are stored once.
- `KeepSource` replaces the placeholder. For each user it stores one JSON file per note (`keep/<user>/<note id>.json`) and each attachment as its original bytes beside it.
- Later runs fetch only notes with `updateTime` after the stored cursor, and detect notes removed since the last run with a full ID listing, following decision D1 for trashed notes.
- `UnsupportedSource` is no longer raised for Keep. The README, REVIEW.md and the UI describe Keep as supported with the gaps above, replacing the "not supported yet" wording from the architecture review branch.
- Recorded response tests in the style of Epic 1 Story 1.6 cover: first full scan, incremental scan, a note with attachments, a checklist note, a trashed note, HTTP 429 with backoff, and 403 for a user without Keep enabled (P1).
- The integrity round trip in Epic 1 Story 1.5 includes Keep data (P0).

**Tasks**
- [ ] Spike against a test user.
- [ ] Add `GoogleKeepClient` to `googleapi.py` and `KeepSource` to `sources/keep.py`.
- [ ] Add Keep fixtures to the demo data so the Northwind sample and E2E journeys show a Keep fileset.
- [ ] Update docs.

---

### Story 9.3: Back up Google Chat

**As** a Workspace user, **I want** my Chat spaces, group chats and direct messages backed up with their attachments, **so that** conversations and shared files are not lost.

**Acceptance criteria**
- Spike first (section 3): confirms delegation with Chat user scopes, behaviour for spaces with external members, attachment download, and the incremental strategy. The spike also measures message volume for a typical user to confirm A1 (one file per message is acceptable) or record the alternative.
- For each user, bgb lists the spaces the user is a member of (`spaces.list`), and backs up each space once across all users (A4). A space is attributed to every member in the run summary.
- Each space stores its metadata, its member list, and its messages as JSON, with threads preserved through the message `thread` field. Attachments are stored as original bytes. Attachments that are Drive files are recorded as links, since Drive backup covers the file.
- Later runs fetch only messages created or updated since the stored cursor per space. Edited messages store the new version. Deleted messages follow decision D1.
- Spaces that cannot be read (for example external spaces, if the spike confirms the limitation) are listed in the run warnings by name, not silently skipped.
- Recorded response tests cover: a DM, a group chat, a named space with threads, an attachment, an edited message, a space shared by two users in the same job (stored once), an unreadable space, and HTTP 429 (P1).

**Tasks**
- [ ] Spike against two test users who share a space and a DM.
- [ ] Add `GoogleChatClient` and `ChatSource`.
- [ ] Add a Chat view to the fileset browser that renders a space as a conversation, or confirm that the generic JSON view is acceptable for now (record which).
- [ ] Update docs.

---

### Story 9.4: Back up Google Calendar

**As** a Workspace user, **I want** my calendars and events backed up, **so that** meetings and their details can be recovered.

**Acceptance criteria**
- For each user, bgb backs up every calendar the user owns: calendar metadata and one JSON file per event, with recurring events stored as the series plus exceptions.
- Subscribed calendars the user does not own are listed in the run summary and not copied, unless the spike shows a reason to include them.
- Later runs use `syncToken`. An expired token (HTTP 410) falls back to a full listing, with a warning, as Contacts does.
- Recorded response tests cover: first scan, incremental with an edited and a cancelled event, a recurring event with one exception, an expired sync token (P1).

**Tasks**
- [ ] Add `GoogleCalendarClient` and `CalendarSource`.
- [ ] Update docs.

---

### Story 9.5: Back up Google Tasks

**As** a Workspace user, **I want** my task lists backed up, **so that** to do items and their due dates can be recovered.

**Acceptance criteria**
- For each user, bgb stores each task list and one JSON file per task, including completed and hidden tasks.
- Later runs use `updatedMin` with `showDeleted` and `showHidden`. Deleted tasks follow decision D1.
- Recorded response tests cover: first scan, incremental with a completed, an edited and a deleted task, and subtasks (`parent` field) (P1).

**Tasks**
- [ ] Add `GoogleTasksClient` and `TasksSource`.
- [ ] Update docs.

---

### Story 9.6: Coverage statement in the UI and docs

**As** an administrator, **I want** to see what a backup does and does not include, **so that** I do not assume something is protected when it is not.

**Acceptance criteria**
- The job form lists every source from the catalog with its description, including the not covered notes (for example "Chat spaces with external members", "Forms responses", if those remain gaps).
- The README has a coverage table matching section 2 of this epic, updated for what was built.
- Each run summary lists items skipped by every source, with a count and a reason, in one place.
- An E2E journey in the style of Epic 1 Story 1.8 creates a job with all sources selected in demo mode and sees a fileset for each (P1).

**Tasks**
- [ ] Update `job-form.tsx` and the run summary view.
- [ ] Update the README and REVIEW.md.

## 6. Out of scope

| Data | Why |
|---|---|
| Google Groups conversations | No read API for group message archives. Groups Migration API is write only. Vault is the supported route |
| Google Sites | New Sites are stored in Drive but cannot be exported through the Drive API |
| Vault holds and exports | Vault is for legal hold and eDiscovery, not operational restore. A Vault export source could be a later epic |
| Admin console configuration, audit logs | Not user data |
| Meet recordings and transcripts | Already stored in Drive and covered by Drive backup |
| Restore back into Workspace | This epic stores data so it can be browsed and downloaded. Restore is Epic 7 in `epics.md` (mailbox and Drive). Restoring Keep, Chat, Calendar and Tasks would extend Epic 7 |

## 7. Changes to the quality gates plan

| Epic 1 location | Change |
|---|---|
| Section 4.3, P2 examples | "Keep refusal message" no longer applies. Replace with "Chat space with external members reported as skipped" |
| Story 1.3, task list | Remove "Keep source is registered and refused with a clear error (P2)" |
| Story 1.8, journeys | Replace "Create a job with Keep selected and see the refusal message (P2)" with "Create a job with all sources selected in demo mode and see a fileset for each (P1)", owned by Story 9.6 |
| Story 1.6 | Unchanged. Its recording and scrubbing approach is reused by Stories 9.2 to 9.5 |

These edits are applied in Epic 1 alongside this draft.

## 8. Open questions

| ID | Question | Recommendation |
|---|---|---|
| Q1 | D1: keep deleted items until retention removes them? | Yes |
| Q2 | Is there a test Workspace user available for the Keep and Chat spikes? Epic 1 D2 says there is no test tenant for nightly live tests. The spikes need one user (two for Chat) for a few hours, not an ongoing tenant. | Use two dummy users in the Aviato domain for the spikes, then delete their data |
| Q3 | Should Forms (questions and responses) be backed up through the Forms API, instead of skipped by Drive? | Add as a later story if customers use Forms for anything they would need back |
