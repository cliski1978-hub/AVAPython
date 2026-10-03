# AVA Phase 5.76A — Project Files Validation and Diff Stabilization

Phase 5.76A revalidated Project Files persistence/API/client behavior, checked the migration and ownership boundaries, and recorded the execution environment's restrictions. No UI, RAG/indexing, prompt, model, or runtime feature was added. Phase 5.77 was not started.

## Ruff formatting audit

The preceding Phase 5.76 run reported that a broad Ruff format command reformatted 94 backend source files, but its output did not preserve the filename manifest. The current workspace also contains extensive uncommitted work from earlier Phase 5 steps; there is no clean pre-format snapshot from which to reconstruct exact prior text.

I identified and restored 28 tracked backend source files whose current diff had no non-whitespace changes (`git diff --ignore-all-space` was empty). The guard checked each file before restoring it to `HEAD`. This removed only whitespace-only differences. I left all files with semantic differences untouched. The remaining 66 of the originally reported 94 cannot be reliably attributed one by one as Phase 5.76 formatting, earlier phase work, or both without the missing filename manifest and prior snapshot. They were preserved rather than risking unrelated edits.

The resulting classification is therefore evidence-bounded:

| Category | Result |
| --- | --- |
| A. Intentional Phase 5.76 semantic changes | Present in the migration 0018, Project File metadata/content adapters, service, API, composition, storage configuration, contracts, and typed-client lifecycle. Shared integration files also contain earlier Phase 5 changes. |
| B. Phase 5.76 tests/documentation | Project File lifecycle and regression tests, Phase 5.76 implementation record, and this validation record. |
| C. Formatting-only changes safely removed | 28 files restored. |
| D. Pre-existing unrelated changes | Preserved; no reliable pre-format baseline exists to count them separately. |
| E. Mixed/unattributable changes | Remaining formatting candidates were not individually separable from earlier semantic edits; preserved. |

Accordingly, the audit did not use reset/checkout/restore cleanup. The broad 94-file count is recorded, but an exact per-file A–E tally for the other 66 cannot be asserted from the available repository state. The shared workspace had 267 dirty paths before this record was added; unrelated Phase 5 work remains present.

## Scope and migration review

Migration 0017 remains Project Execution Defaults and migration 0018 is Project Files; the ordered registry contains both once, with no skipped version. The Phase 5.76 production scope is limited to Project File metadata/content persistence, Project deletion cleanup, routes, composition/configuration, public contracts, and typed API-client methods. Project files remain separate from Conversation/message/run attachments. No Phase 5.76 semantic change was found in execution selection, effective prompt resolution, prompt injection, model/runtime selection, or conversation history. Existing changes in those areas belong to earlier Phase 5 work and were preserved. No embeddings, chunks, vectors, or indexing records were added.

## Validation results

| Check | Result |
| --- | --- |
| Focused backend Project File/domain/migration/architecture tests | **176 passed** |
| Upload compensation, Project-delete rollback, and cleanup-failure regressions | **4 passed** |
| Backend Ruff | **Passed** (`ruff check src tests`) |
| Ruff format check | **Passed**, 19 Phase 5.76 Python files already formatted |
| Backend mypy | **Passed**, 234 source files |
| API-client tests and typecheck | **Passed**, 111 tests |
| Contracts tests and typecheck | **Passed**, 41 tests |
| Frontend workspace tests and typechecks | **Passed**; 10 workspace projects, 6 opt-in tests skipped |
| Python client tests/Ruff/mypy | **Passed**, 10 tests; 3 source files typechecked |
| Web production build | **Passed** |
| Desktop production build | **Passed** |
| `git diff --check` | **Passed** |

Typed-client tests exercise `uploadProjectFile`, `listProjectFiles`, `getProjectFile`, `downloadProjectFile`, and `deleteProjectFile`. The Web and Desktop builds both completed; Vite emitted its existing large-chunk advisory.

## Disposable SQLite/API lifecycle

The canonical backend startup script was attempted with disposable database and content paths. Uvicorn failed before startup while creating its listener with `PermissionError: [Errno 1] Operation not permitted`; `/health` therefore could not be reached over loopback in this sandbox. The temporary database/content paths were removed. This is an environment restriction, not an application startup exception.

To validate the same HTTP routes without a socket, an ASGITransport integration run used a temporary relational SQLite database and local content directory. It passed:

- Exact text upload `AVA PROJECT FILE VALIDATION 576A` and binary upload containing `00`, `FF`, and non-UTF-8 bytes.
- Public metadata, content type, byte size, Project ownership, list/get, deterministic ordering, and absence of `content_ref`.
- Exact text and binary download bytes; Unicode filename metadata and encoded `Content-Disposition`.
- Duplicate display names with distinct IDs/content references and their independent bytes.
- Safe cross-Project GET/DELETE not-found behavior, followed by the successful owner download.
- Database restart/reopen with the same SQLite file and content root; all four files and exact bytes remained available.
- Single-file deletion and Project deletion cleanup while a second Project remained intact.
- Schema version **18**, `PRAGMA integrity_check` = **ok**, and `PRAGMA foreign_key_check` = **no rows**.

Because the ASGI run uses the application transport directly, it does not certify TCP listener startup. No non-disposable user Project or database was touched. Temporary lifecycle data was cleaned automatically.

## Canonical harness limitation

`./scripts/test_all.sh` was attempted once after the safe format-only restorations. It collected 2,490 backend tests, passed architecture and the early attachment suites, then made no progress after entering `tests/test_attachment_restart_recovery.py`; the 90-second bounded run timed out there.

A minimal independent `TestClient(FastAPI())` reproduction printed `constructed` and then stalled inside `TestClient.__enter__` before application lifespan startup. `faulthandler` showed the thread waiting in AnyIO's `from_thread`/`run_blocking_portal`, reached from Starlette `testclient.py:516`. The same environment prevents Uvicorn socket creation. Project Files tests use ASGITransport and pass, and the disposable route lifecycle above passes. This establishes the canonical harness/listener failures as sandbox limitations; no Project Files-specific failure was observed.

## Status

```text
Phase 5.76 implementation: certified under the external-blocker policy
Phase 5.76A validation/stabilization: complete with the sandbox limitations above
Phase 5.77 Project Files UI: not started
```
