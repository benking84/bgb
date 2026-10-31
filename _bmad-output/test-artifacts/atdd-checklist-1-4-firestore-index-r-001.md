---
stepsCompleted: ['step-01-preflight-and-context', 'step-02-generation-mode', 'step-03-test-strategy', 'step-04-generate-tests', 'step-05-validate-and-complete']
lastStep: 'step-05-validate-and-complete'
lastSaved: '2026-10-31'
workflowType: 'testarch-atdd'
storyId: '1.4'
storyKey: '1-4-firestore-index-r-001'
storyFile: '_bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md'
atddChecklistPath: '_bmad-output/test-artifacts/atdd-checklist-1-4-firestore-index-r-001.md'
generatedTestFiles:
  - tests/integration/conftest.py
  - tests/integration/test_firestore_index.py
inputDocuments:
  - _bmad-output/test-artifacts/test-design-epic-1.md
  - _bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md
  - REVIEW.md
  - src/bgb/index/firestore.py
  - src/bgb/index/memory.py
  - tests/helpers.py
  - tests/test_api.py
  - tests/test_engine.py
  - resources/knowledge/data-factories.md
  - resources/knowledge/component-tdd.md
  - resources/knowledge/test-quality.md
  - resources/knowledge/test-healing-patterns.md
  - resources/knowledge/test-levels-framework.md
  - resources/knowledge/test-priorities-matrix.md
  - resources/knowledge/ci-burn-in.md
acceptanceCriteria:
  - { id: AC-1, idSource: generated, text: 'Every index implementation stores a block hash once: the first put_block returns True, a repeat returns False and keeps the original volume.' }
  - { id: AC-2, idSource: generated, text: 'A block list longer than 400 hashes round trips through the index unchanged and in order.' }
  - { id: AC-3, idSource: generated, text: 'A backup that writes more than 500 documents completes on the Firestore index with every entry recorded.' }
  - { id: AC-4, idSource: generated, text: 'The Northwind demo backup on the Firestore index restores the handbook byte for byte, matching the recorded SHA-256.' }
---

# ATDD Checklist - Epic 1, Story 1.4: Firestore index acceptance tests (R-001)

**Date:** 2026-10-31
**Author:** Ben (prepared with Murat, TEA)
**Primary test level:** Integration (pytest against the Firestore emulator)
**Status:** Red phase complete. Green phase deferred: R-001 accepted by Ben on 2026-10-31 (waiver W-001)

---

## Story Summary

R-001 is the only risk in the Epic 1 test design that blocks release (score 9). Production runs `FirestoreIndex` (`BGB_INDEX=firestore`), and `src/bgb/index/firestore.py` has 0% coverage. These tests make the Firestore index prove the same behaviour as the in-memory and JSON file indexes, plus the two Firestore-specific limits named in REVIEW.md.

**As** the team operating bgb, **we want** the production index tested on every PR, **so that** a defect cannot lose index entries while the tests on the fakes stay green.

---

## Acceptance Criteria

The epic stories carry no `AC-n` ids, so these were assigned in order from the R-001 rows of the test design.

1. **AC-1** Every index implementation stores a block hash once: the first `put_block` returns `True`, a repeat returns `False` and keeps the original volume.
2. **AC-2** A block list longer than 400 hashes round trips through the index unchanged and in order.
3. **AC-3** A backup that writes more than 500 documents completes on the Firestore index with every entry recorded.
4. **AC-4** The Northwind demo backup on the Firestore index restores the handbook byte for byte, matching the recorded SHA-256.

---

## Story Integration Metadata

- **Story ID:** `1.4`
- **Story Key:** `1-4-firestore-index-r-001`
- **Story File:** `_bmad-output/planning-artifacts/epics/epic-1-pipeline-quality-gates.md` (Stories 1.4 and 1.5)
- **Risk:** R-001 in `_bmad-output/test-artifacts/test-design-epic-1.md`
- **Checklist Path:** `_bmad-output/test-artifacts/atdd-checklist-1-4-firestore-index-r-001.md`

---

## Red-Phase Test Scaffolds Created

All four tests are in `tests/integration/test_firestore_index.py`, marked `integration` and `p0`, and skipped at module level with the reason "ATDD red phase: Firestore emulator harness not built yet (Story 1.4)".

| Test | AC | Runs against | First assertion that can fail |
|---|---|---|---|
| `test_ac1_put_block_stores_a_hash_once_on_every_index` | AC-1 | memory, file, firestore | `second is False` (dedup on a repeated hash) |
| `test_ac2_block_list_over_400_hashes_round_trips_in_order` | AC-2 | memory, file, firestore | `get_blockset(...) == hashes` with 801 hashes (three Firestore parts) |
| `test_ac3_backup_over_500_writes_completes_on_firestore` | AC-3 | firestore | `run.status == "completed"` with 600 files |
| `test_ac4_northwind_restore_is_byte_identical_on_firestore` | AC-4 | firestore | `downloaded.content == HANDBOOK` |

8 test items in all, because AC-1 and AC-2 run once per index.

**Verified in this session:**
- With the skip in place: the suite reports 20 passed, 8 skipped. The existing tests are unaffected.
- With the skip removed (a scratch copy): the 4 memory and file variants pass, which proves the test logic against the fakes. The 4 Firestore variants skip because no emulator was running here. Docker was not running, and the Firestore emulator component was not installed. **No test has run against Firestore yet.**

---

## Data Factories Created

None needed. Data comes from:
- `_digest(seed)` in the test file: deterministic SHA-256 block hashes.
- `BytesSource` and `job()` in `tests/helpers.py`: 600 distinct small files for AC-3.
- The Northwind demo job (`/api/demo/seed`) for AC-4.

---

## Fixtures Created

`tests/integration/conftest.py`:

- `firestore_client`: skips when `FIRESTORE_EMULATOR_HOST` is unset. Otherwise it clears the emulator's `bgb-test` project through the emulator REST endpoint, yields a `firestore.Client`, and closes it after the test.
- `index`: parametrised over `memory`, `file` and `firestore`. One assertion set covers every implementation.
- `firestore_index`: a `FirestoreIndex` on the emulator client.

Supporting change: `tests/helpers.py` `make_engine` now takes an optional `index=` argument. The default stays `MemoryIndex`, so existing callers are unchanged.

Supporting change: `pyproject.toml` registers the `integration` and `p0` markers.

---

## Mock Requirements

None. The Firestore emulator is a real local service, not a mock. Volume storage stays `MemoryVolumeStore`, because the GCS store is R-005 and has its own tests.

---

## Required data-testid Attributes

N/A. This run creates no UI tests.

---

## Implementation Checklist

The production code under test already exists. Green phase means building the harness that runs it, not writing new product code.

### Harness (unblocks all four tests)

- [ ] Add `docker-compose.test.yml` with the Firestore emulator: `gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators`, running `gcloud emulators firestore start --host-port=0.0.0.0:8080`.
- [ ] Document the local run in the README: start the emulator, set `FIRESTORE_EMULATOR_HOST=localhost:8080`, then run `pytest -m integration`.
- [ ] Add a Cloud Build step that starts the emulator as a background container on the `cloudbuild` network and sets `FIRESTORE_EMULATOR_HOST` for the test step.
- [ ] **Set `BGB_REQUIRE_EMULATOR=1` in every CI test step.** The `firestore_client` fixture skips locally when the emulator is missing, but fails under that flag, so a broken CI harness cannot show as green. The flag is already in the fixture.
- [ ] Remove the module-level `pytest.mark.skip` from `tests/integration/test_firestore_index.py`.
- [ ] Run `pytest -m integration` and fix whatever the Firestore variants expose.

### Things the green phase may expose (from reading `firestore.py`, not yet observed)

- [ ] `put_block` detects a duplicate by exception class name (`AlreadyExists` or `Conflict`). Confirm the emulator raises a class with one of those names.
- [ ] `count_blocks` uses `select([])` with an empty field list. Confirm the emulator accepts it.
- [ ] `put_fileset` writes the fileset document, then entries in batches of 400, so it is not atomic. AC-3 checks that the result completes. Crash behaviour between batches is R-003 and has its own tests.

### Secondary branches for green-phase automation (not written as red-phase leaves)

- [ ] AC-1 suite: jobs (upsert, get, list, delete), runs (add, update, list order), filesets and entries (`list_entries` paging and cursor, `get_entry`, `delete_fileset`), volumes (`get_volume_by_name`, `list_volumes`, `delete_volume`), `blocks_for_volume`, `delete_blocks` over 400 hashes, `clear_backup_data`, settings round trip. That brings the test design's AC-1 row to its planned 10 tests.
- [ ] AC-2: an empty block list, exactly 400 hashes (one part), and 401 (two parts). Check that each Firestore part document stays under 1 MiB.
- [ ] AC-3: a second unchanged run over the same 600 files uploads no new blocks.
- [ ] AC-4: also check the shared drive copy of the handbook, run `verify --full`, and confirm a second run reuses all blocks.

**Estimated effort:** ~6 to 10 hours for the harness, plus ~8 to 14 hours for the secondary branches.

---

## Running Tests

```bash
docker compose -f docker-compose.test.yml up -d firestore
```

```bash
FIRESTORE_EMULATOR_HOST=localhost:8080 python3 -m pytest -m integration -rs
```

```bash
python3 -m pytest tests/integration/test_firestore_index.py -k ac2
```

```bash
python3 -m pytest -m integration --cov=bgb.index.firestore --cov-report=term-missing
```

The `docker-compose.test.yml` in the first command does not exist yet. It is the first harness task above.

---

## Red-Green-Refactor Workflow

### RED Phase (complete)

- 4 acceptance tests (8 items) written and skipped.
- Fixtures parametrised across all three index implementations.
- The test logic is proven against the fakes.

### GREEN Phase (deferred by decision W-001, 2026-10-31)

Ben accepted R-001 as sufficiently derisked. The Firestore variants are assumed to pass and were never run. The tests stay skipped in the repo, and the harness work is deferred. The canary job in Story 1.10 is the remaining check against real Firestore. Full record: "Decisions and Waivers" in `test-design-epic-1.md`.

When this is picked up again:

1. Build the emulator harness (Implementation Checklist above).
2. Remove the skip marker.
3. Run against the emulator, fix any defects found in `firestore.py`, and record them.
4. Add the secondary branches.

### REFACTOR Phase

- Move the shared index assertions into a reusable module once the volume store suite (R-005) needs the same pattern.

---

## Next Steps

1. Review this checklist and the generated tests.
2. Build the harness, as the first task of Story 1.4.
3. Run the same ATDD pass for R-002 (API auth) and R-003 (crash recovery).
4. Run `/bmad-testarch-automate` after the harness lands, for the secondary branches.

---

## Knowledge Base References Applied

- `test-levels-framework.md`: integration level, because the in-memory fakes cannot show Firestore behaviour.
- `test-priorities-matrix.md`: all P0, as data integrity with no workaround.
- `test-quality.md`: deterministic data, isolated state per test (the emulator is cleared each time), no hard waits.
- `ci-burn-in.md`: the CI rule that skips must fail when the emulator is required.
- `data-factories.md`, `component-tdd.md`, `test-healing-patterns.md`: loaded; factories not needed at this size.

**Deviations from the workflow:**
- The stack detects as fullstack, and the workflow expects `playwright.config.ts` for that. This run is backend only (pytest), as requested, so the Playwright prerequisite and UI fragments were not applied.
- Progress was written once at the end rather than after each step.
