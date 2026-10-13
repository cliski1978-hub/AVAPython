# Phase 5 extension — Conversation Attachment Extraction, Step 1

Step 1 is implemented. Extraction stops at a normalized backend result. It is
not connected to runs, prompts, context budgeting, Run Inspector, or the Prompt
Window Indicator. No public endpoint, schema migration, extracted-text cache,
third-party dependency, or frontend change was introduced.

## Existing attachment flow

Migration 0003 stores metadata in `attachments`: attachment ID, display filename,
media type, authoritative byte size, opaque storage key, nullable owner type/ID,
lifecycle status, and creation timestamp. `AttachmentRepository` has memory and
SQLite implementations. It never stores or extracts content bytes.

`AttachmentService.create_attachment` coordinates pending metadata, byte-store
write/verification, and available metadata. Its content key is
`attachments/{attachment_id}/content`, derived from the backend ID rather than
the filename. `AttachmentContentStore` supplies independent readable streams;
memory and local-filesystem adapters already implement it. Local files stay
beneath the configured `AVA_ATTACHMENT_STORAGE_ROOT`. Metadata persistence and
content storage remain independently configurable.

Conversation uploads use `POST /conversations/{conversation_id}/attachments`.
The owner pair is exactly `conversation` plus the durable Conversation ID.
Existing generic download uses `AttachmentService.open_attachment_content`,
which rejects pending/failed metadata and reports missing stored bytes.
Conversation-scoped delete checks Conversation existence and exact attachment
ownership, returning not-found for a mismatched owner. The new extraction
service follows that same ownership rule before opening content.

`AVA_ATTACHMENT_MAX_SIZE_BYTES` already bounds uploads (default 25 MiB).
Extraction reuses this setting, checks metadata size, and reads in chunks of at
most 64 KiB with an actual-byte cap of the configured maximum plus one sentinel
byte. This also bounds legacy/direct-service uploads and understated metadata.
Streams close on success, read failure, and oversize rejection.

## New abstraction and service

`AttachmentTextExtractor` owns the conservative text-type/decoding policy.
`AttachmentExtractionService` coordinates existing metadata/content services and
the Conversation repository. It is composed as
`app.state.attachment_extraction_service` and accepts an injectable extractor.
Application callers use:

```python
result = app.state.attachment_extraction_service.extract(
    conversation_id, attachment_id,
)
```

Missing Conversations, missing attachments, mismatched Conversation owners,
unassociated attachments, and Message/Document-owned attachments return `None`.
The caller must translate that into its existing not-found behavior. This is
ownership validation, not a new authentication/authorization system.

An internal immutable `AttachmentExtractionResult` carries attachment ID,
filename, media type, extraction status, optional text, and optional safe error
code/message. It exposes no storage key or path. Extraction status is independent
of the stored attachment lifecycle; failures do not mark an available attachment
failed or mutate any stored record or byte.

| Outcome | Behavior |
| --- | --- |
| `success` | Exact decoded text, including Markdown/JSON/CSV formatting; empty text is valid. |
| `unsupported` | `attachment_type_unsupported`; no random decode or byte-store read. |
| `failed` | Safe code/message for invalid UTF-8, binary controls, unavailable lifecycle, storage read failure, or configured size-limit rejection. |

Supported extensions are `.txt`, `.md`, `.json`, and `.csv`, case-insensitively
after trimming the filename. Supported extensions work with generic or incorrect
MIME metadata. An explicit unsupported extension wins over client MIME metadata;
extensionless files may use `text/plain`, `text/markdown`, `text/csv`, or
`application/json`, including MIME parameters.

Decoding uses strict `utf-8-sig`: ordinary UTF-8 and a leading UTF-8 BOM work,
while invalid bytes fail without replacement characters or guessed legacy
encodings. NUL, C0 controls other than tab/newline/carriage return, and DEL/C1
controls fail as binary content. No JSON parsing, CSV transformation, Markdown
rendering, normalization of authored whitespace, or newline conversion occurs.

The backend dependency manifest and implementation contain no supported PDF or
DOCX extraction facility. Both return `unsupported`, as do images, archives,
executables, and unknown formats. No document-processing stack was installed.
Project Files retain their independent ownership/content ports.

## Files changed by this step

- `backend/src/ava/contracts/attachment_extraction.py` — internal result/status.
- `backend/src/ava/services/attachment_extraction_service.py` — extractor and application service.
- `backend/src/ava/api/app.py` — one import and service composition using existing resources/size setting.
- `backend/tests/test_attachment_extraction.py` — extraction and architecture regressions.
- This implementation/validation record.

The checkout already contained extensive unrelated changes. Those were preserved;
the complete Git diff is not the diff of this step alone.

## Validation

The new tests exercise both memory and SQLite metadata over the existing local
content store, text preservation for all four types, BOM/Unicode/empty text,
MIME fallback and spoof rejection, invalid encoding, binary controls, exact
Conversation ownership, lifecycle rejection, missing/open/read failures,
stream closure, independent attachment preservation, metadata/actual-byte bounds,
real multipart upload, cold persistence reopen, and absence of extraction imports
in execution/runtime/route layers.

| Check | Result |
| --- | --- |
| New extraction suite | 50 passed. |
| Extraction + Conversation attachment/service/local storage/relational repository regressions | 140 passed. |
| Backend Ruff, `src tests` | Passed. |
| New production modules, strict mypy | Passed, 2 source files. |
| Full backend mypy | 14 existing errors across settings, OpenHands, context compaction, deletion coordinator, Conversation routes, and native run-inspection code. |
| Canonical harness, restricted environment | Stalled at the existing attachment restart TestClient boundary; interrupted. |
| Canonical harness, local socket access | Incomplete: interrupted after stalling in `test_partial_assistant_content.py`; 1,523 passed, 25 failed, 6 skipped, 7 warnings at interruption. No later harness stages ran. |
| Failure baseline comparison | All 25 backend failures reproduced in a temporary copy with only this extraction feature removed: 25 failed. Shared checkout was not reset or modified for the comparison. |
| Frontend package tests, separate run | Contracts 42, API client 114, UI core 77, Agent UI 314, Settings 212, Documents 70 passed. Workspace: 237 passed, 6 failed, 6 skipped; failures are existing AppWorkspace/RunInspector cases. |
| Desktop tests, separate run | 11 passed. |
| Frontend lint/type checks | Failed on existing Settings model context-window contract mismatches. |
| Python client | 10 passed; Ruff and strict mypy passed. |
| `git diff --check` | Passed. |

No full-stack green certification is claimed. Builds were not repeated because
there is no frontend or packaging change and frontend type checks already fail.

## Manual upload and restart smoke

A disposable SQLite/local-content AVA backend ran on `127.0.0.1:8001`; the shared
Web UI ran on `localhost:5175`. Validation-only CORS allowed that UI origin. A
new Conversation was created through the browser, and the browser file chooser
uploaded `test.md` containing `AVA-ATTACHMENT-EXTRACTION-7319` plus an unsupported
PNG. Both appeared in the Conversation attachment list as available resources.

The composed backend extraction service read the stored metadata/content and
returned `success` with the exact marker, and `unsupported` for the PNG. The
backend process was stopped normally and relaunched over the same database and
content root. A fresh extraction-service invocation returned byte-for-byte
identical serialized results; browser reload reconstructed both attachments,
with the existing “File contents are not included in runs yet” notice intact.
No extraction API was added to conduct the smoke test.

The screenshot is saved at `/tmp/ava-attachment-extraction-restart.png`. Only
disposable validation data was created. Validation servers were stopped after
the smoke test; no user database or settings were changed.

## Step 2 considerations

Step 2 must decide how a not-found/unsupported/failed result participates in
context construction. It must explicitly select Conversation-owned attachments,
preserve ownership validation, and separately define token budgets, ordering,
truncation, and run-owned snapshots. Extraction remains on-demand with no cache;
UTF-8-only text support and the configured attachment byte limit apply. There is
no OCR, PDF/DOCX parsing, RAG, retrieval, embedding, chunking, or prompt inclusion.

Step 2 has not started.
