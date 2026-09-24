# AVA Phase 4 Attachment Architecture Audit

Status: IMPLEMENTED — Step 4.14 (Attachment Metadata Foundation) is COMPLETE as
of the 4.14.H closure slice. This document is the authoritative design record;
deviations and validation results are recorded in the Step 4.14 entry of
`AVA_Phase_4_Implementation_Log.md` (notably: `storage_key` is absent from the
public wire contracts, overriding decision §28's draft shape).

This document records the Step 4.14 architectural decisions for the attachment
metadata foundation. It follows the same audit workflow as
`AVA_Phase_4_Persistence_Architecture_Audit.md`.

## Current state (audit findings)

AVA has **no attachment, file-upload, blob, or physical-content storage
abstraction** anywhere in backend or frontend source today.

- Backend: the only mentions are planning notes: `RunRequest`
  (`ava/contracts/requests.py`) reserves "message, conversation,
  document-reference, and attachment fields" for a future sprint, and
  `MessageRecord` (`ava/repositories/message_repository.py`) states "No
  attachment/streaming machinery exists yet". Document content is canonical
  serialized HTML stored flat in `documents` (current) + `document_revisions`
  (immutable history) — no physical file storage. The only filesystem-path
  usage in the backend is execution/tool infrastructure (sandbox runner,
  workspace contracts, OpenHands file tools), unrelated to persistence.
- Frontend: no `File`/`FormData`/`Blob`/download handling anywhere. The shared
  `ApiClient` is JSON-only. No attachment vocabulary in any production source
  (grep matches are only third-party `node_modules` bundles).
- Two guard points treat `attachment` as forbidden later-phase vocabulary and
  must be updated when Step 4.14 lands (see Migration plan):
  - `backend/tests/test_architecture.py` →
    `test_persistence_schema_introduces_no_later_phase_tables` (forbidden
    tuple contains `"attachment"`).
  - `backend/tests/test_persistence_migrations.py` →
    `test_unknown_legacy_database_is_rejected_without_destructive_rewrite`
    uses `CREATE TABLE attachments` as its "unexpected table" probe.
- Existing design notes: canonical plan §5.4 "Attachments" (future chat
  attachment support via controlled references); persistence audit §4.9.2
  originally scoped Phase 4 attachments to "contracts + repository port only".
  Step 4.14 supersedes that with the metadata/content-store split below.

## Decisions

### 1. Attachment semantic

> An **Attachment** is a durable metadata record describing a file/content
> object associated with an AVA entity. The physical bytes live behind a
> storage-neutral `AttachmentContentStore`, never in the record.

`Document.content` is *editor/domain content* (canonical HTML). An Attachment
is always *external file/blob* data. They do not overlap.

### 2. Metadata vs physical content

Strict separation, mirroring the existing port/adapter pattern:

```
AVA domain/service
      ↓
AttachmentRepository        → durable metadata   (SQLite in relational mode)
AttachmentContentStore      → physical bytes     (local disk / volume / S3 / Azure)
```

SQLite stores metadata only. Provider-specific storage knowledge lives only in
content-store adapters under `infrastructure`.

### 3. Ownership/association model

Recommendation: **Option B — generic owner fields**, with `status` and a
nullable association:

```
owner_type: AttachmentOwnerType | None   ("document" | "conversation" | "message")
owner_id:   str | None                    (non-null only when owner_type is set)
```

- Rejected: Option A (per-concept nullable FKs) — each new owner kind requires
  a migration and index churn.
- Rejected now: Option C (independent `attachment_links` table) — deferred
  until a real many-to-one/multi-association requirement appears.
- B keeps the foundation smallest while staying extensible: a future
  workspace/tool-output owner is just a new `owner_type` value — no schema
  change. Un-associated (general) attachments are allowed via NULLs.

### 4. Attachment identity

`attachment_id` = backend/service-owned UUID (same convention as
`document_id`). Invariant: **identity is never the physical location**; the
record references content only through `storage_key`. Clients never supply ids.

### 5. storage_key semantics

`storage_key` is an **opaque AVA-managed logical reference interpreted only by
the selected `AttachmentContentStore`**. The domain never treats it as a path.
Logical shape: `attachments/{attachment_id}/{file_name}`. Each adapter binds that
logical key to its native placement (local path, Volume location, S3 object key,
Azure blob name) internally. `UNIQUE(storage_key)` in metadata.

### 6. Absolute machine paths forbidden in metadata

Domain metadata must never store absolute paths (`/home/.../file.docx`,
`C:\...`). The local adapter computes the physical path from its configured
root + the logical key at the adapter boundary only.

### 7. Filename semantics

`file_name` is **display/original filename only** — user-facing, may contain
duplicates, never trusted as a key. The storage key always derives from
`attachment_id`, never from the filename. Sanitization is deferred to the
upload slice (strip path components, reject control chars, NFC-normalize,
length caps, reserved-name handling) — not a foundation concern.

### 8. Media type semantics

`media_type: str` — IANA MIME, lowercased, syntax-validated (token form).
Not derived from filename extension. For 4.14 it is **client-provided and
syntax-validated**; a whitelist policy and server-side detection are later
hardening. Never blindly trusted at serve time (safe download headers, no
inline execution).

### 9. Size semantics

`size_bytes: int`, `>= 0` (CHECK constraint), zero-byte files allowed. The
authoritative size is the **result of the content store's `put`**, not a
client claim. Configurable maximum sizes are deferred to hardening.

### 10. Checksum

Classified **useful but deferred**: no upload path exists yet, so enforcing a
sha256 now adds unused complexity. When the orchestration slice lands it should
record `content_sha256` (verified after `put`). To avoid a second migration
immediately after v0003, the plan keeps the v0003 schema foundation-only and
adds verification/checksum as part of orchestration (a later nullable column
or its inclusion in v0003 is an implementation-time micro-decision).

### 11. Immutable vs mutable

Immutable: `attachment_id`, `storage_key`, `created_at`, `owner_type`,
`owner_id`, `media_type`, `size_bytes`. Mutable: `status` only (lifecycle).
`file_name` is treated as immutable in the foundation (no rename feature now).

### 12. Lifecycle/status

Status is part of the foundation (cheap, high value) because upload is
inherently two-resource work that may not share a transaction:

```
pending ──▶ available        (content store reports success + size parity)
pending ──▶ failed           (recoverable/reportable error)
```

Invariant: **`available` ⇒ content exists and its stored size matches
`size_bytes`.** `pending` records are safe to retry/re-upload.

### 13. AttachmentRepository port

Add only what AVA needs; current-vs-future:
`create(record)`, `get(attachment_id)`, `list_for_owner(owner_type, owner_id)`.
`delete` is **deferred** (no destructive-delete requirement; mirrors the
conservative document decision). No content field exists on the metadata port.

### 14. AttachmentContentStore port

Storage-neutral, stream-based from day one (large-file compatible — never
`bytes` in the contract):

```python
class AttachmentContentStore(Protocol):
    def put(self, storage_key: str, source: BinaryIO) -> StoredContentInfo: ...
    def open(self, storage_key: str) -> BinaryIO: ...
    def exists(self, storage_key: str) -> bool: ...
```

`StoredContentInfo` carries `size_bytes` (optionally `sha256` later).
Minimal surface: put/open/exists. `delete` deferred. Implementations: local
disk; later Unity Catalog Volume, S3, Azure Blob.

### 15. Streaming / large files

Ports accept `BinaryIO`/file-like objects; API reads stream
(`StreamingResponse`), writes stream (multipart without a full-body carve-out
beyond framework defaults). No client wholes-file `bytes` path in the domain.
Chunked/resumable multipart is out of scope; the port does not preclude it.

### 16. Relationship to Document.content (unchanged)

`Document.content` remains canonical serialized HTML in `documents` +
`document_revisions` (Step 4.12/4.13). Attachments never move or restructure
that content in 4.14. A future `ContentStore` may later host exported physical
document files, but Step 4.12/4.13 behavior is not destabilized.

### 17. Future physical document storage

Keep the port named **`AttachmentContentStore` now**. It is deliberately
generic (opaque keys + streaming) so it can become a shared
`ContentStore`/`BlobContentStore` later for exported document bytes without a
contract break. Do not over-generalize the name in 4.14.

### 18. Migrations / schema plan

One migration, **v0003** (e.g. `v0003_attachment_metadata`), creating a single
`attachments` table:

```
id            INTEGER PRIMARY KEY AUTOINCREMENT   (stable surrogate, like peers)
attachment_id TEXT NOT NULL UNIQUE                (backend-owned UUID)
file_name     TEXT NOT NULL                       (display metadata)
media_type    TEXT NOT NULL                       (IANA MIME, syntactic)
size_bytes    INTEGER NOT NULL CHECK (size_bytes >= 0)
storage_key   TEXT NOT NULL UNIQUE                (opaque logical reference)
owner_type    TEXT NULL CHECK (owner_type IN ('document','conversation','message'))
owner_id      TEXT NULL
status        TEXT NOT NULL CHECK (status IN ('pending','available','failed'))
created_at    TEXT NOT NULL                       (aware UTC)
```

Constraints: `CHECK (owner_type IS NOT NULL OR owner_id IS NULL)` (no orphan
id), unique `attachment_id` and `storage_key`, and
`CREATE INDEX idx_attachments_owner ON attachments(owner_type, owner_id)` for
owner lookup.

Required guard updates (bundle with 4.14.C, same precedent as Step 4.13
demoting `document_revisions`):
- `test_persistence_schema_introduces_no_later_phase_tables` — remove
  `"attachment"` from the forbidden tuple; expected created list gains
  `attachments` and `idx_attachments_owner`.
- `test_unknown_legacy_database_is_rejected_without_destructive_rewrite` —
  swap the probe table from `attachments` to a still-unknown name (e.g.
  `avatars`).

### 19. In-memory parity

- `InMemoryAttachmentRepository` — required (memory mode + deterministic
  tests), same shape as the other in-memory stores.
- Content store: recommend the real `LocalAttachmentContentStore` against a
  `tmp_path` as the default test adapter rather than a synthetic
  bytes-in-dict store, so containment + streaming behavior is honestly
  exercised. No separate in-memory content store needed.

### 20. Local storage adapter plan

`LocalAttachmentContentStore(root_dir: Path)`:
- configured explicit root (never implicit CWD; default only from
  configuration); storage_key resolved as `root_dir / key`;
- path containment enforcement (`resolve()` must stay under root; reject
  `..`, absolute keys) at every open/put/exists;
- streamed writes via a temp file + atomic rename so a partial write never
  leaves a final key visible;
- never interpolates the user-supplied filename into the physical path.

### 21. Configuration plan

New settings (independent of `AVA_PERSISTENCE`):
- `AVA_ATTACHMENT_STORAGE=memory|local` (default `memory`) →
  `attachment_content_store`;
- `AVA_ATTACHMENT_STORAGE_ROOT=/abs/path` →
  `attachment_content_store_root` (required only when `local`).

Metadata persistence and content storage are independently selectable:
`AVA_PERSISTENCE=relational` with `AVA_ATTACHMENT_STORAGE=local` is valid.

### 22. Databricks compatibility

Future mapping:
- `AttachmentRepository` → Delta/SQL metadata adapter (managed
  table, not a file);
- `AttachmentContentStore` → **Unity Catalog Volume** adapter mapping the
  logical `storage_key` to a Volume-relative location internally.

Documented explicitly: in production the SQLite database file must **not** live
inside DBFS/UC Volumes; only attachment bytes go in Volumes. AVA domain code
never sees volume paths.

### 23. S3 / Azure compatibility

Verified: only the content-store adapter differs
(`S3AttachmentContentStore` = object key from `storage_key`;
`AzureBlobAttachmentContentStore` = blob name from `storage_key`, container
from config). `AttachmentRecord`, `AttachmentService`, API contracts, and
frontend contracts remain unchanged. No provider-specific fields in the record.

### 24. Security requirements (future implementation)

Path-traversal prevention; storage-key confinement to the store root; filename
kept as display metadata only; media type not blindly trusted (safe
`Content-Disposition`; filenames sanitized at download headers; never
inline-execute); size enforcement later; authorization later; malware scanning
later; checksum verification once introduced.

### 25. Lifecycle atomicity / failure recovery

Two-resource work cannot share one transaction. Planned orchestration (not
implemented):

```
service: generate attachment_id + storage_key
  → repository.insert(status=pending)
  → content.put(storage_key, stream)         # staged temp → finalize/promote
  → verify size parity (later sha256)
  → repository.mark(status=available)
  on any failure: mark failed (retryable), best-effort content cleanup
```

Crash cases: content written but metadata insert fails → orphan (future
sweep); metadata `pending` but content never written → detectable, re-upload
allowed; process dies mid-write → staging key never promoted (TTL/orphan
sweep later). Local adapter uses atomic rename; object stores are
single-request puts, so "promote" is trivial. Simplest durable strategy:
**status-gated commit with staged write then finalize**.

### 26. Delete semantics

**Defer all destructive delete** (metadata delete, content delete, soft
delete). No `delete` on either port; no delete endpoints. Orphan cleanup is
hardening (Phase 4.16). Matches the conservative document-delete decision.

### 27. Backend API scope

Smallest scope that proves the whole seam (metadata + content):
- `POST /attachments` — multipart create (owner_type/owner_id/file_name/
  media_type optional + file stream) running the pending→store→verify→available
  orchestration → 201 `AttachmentResponse`;
- `GET /attachments/{attachment_id}` → 200 metadata;
- `GET /attachments/{attachment_id}/content` → streamed bytes with safe
  content-disposition;
- `GET /attachments?owner_type=&owner_id=` → owner-scoped list.

No delete/restore/global list. Note: `python-multipart` is present in the venv
but **not declared** in `backend/pyproject.toml`; 4.14.F must declare it (a
dependency-decision flag for the implementation slice, not a change now).

### 28. Frontend scope

Transport contracts + api-client seam **only**; no UI of any kind:
- contracts: `AttachmentResponse`, `AttachmentListResponse`
  (`attachment_id`, `file_name`, `media_type`, `size_bytes`, `owner_type`,
  `owner_id`, `status`, `created_at`, `storage_key`). `storage_key` is
  backend-owned metadata that the frontend never interprets as a path; bytes
  are fetched only via `GET /attachments/{id}/content`.
- api-client: `createAttachment(client, meta, file: Blob)` (multipart/FormData),
  `getAttachment`, `listAttachments`, `getAttachmentContent` (stream/AoB).
- document-core: no `Attachment` types in 4.14 (not part of editor state).

### 29. Chat/RAG future compatibility

Chat: a future message upload sets `owner_type=message`/`owner_id` on the same
record/ports; `MessageRecord` is unchanged in 4.14. RAG: later ingestion
references attachments as source artifacts via a separate index/vector table;
the base record carries **no** RAG fields (no `indexed`/`chunked`/vector refs).
Source-file identity stays separate from indexing state.

## Recommended Step 4.14 slices

Validated against the repo; matches the proposed sequence with explicit guard
work:

- **4.14.A** attachment domain: `AttachmentRecord`, `AttachmentStatus`,
  `AttachmentOwnerType`, `AttachmentRepository` port + in-memory repository +
  contract tests.
- **4.14.B** `AttachmentContentStore` port (`put`/`open`/`exists`) +
  `StoredContentInfo`; test adapter = local store against tmp dirs; port tests.
- **4.14.C** migration v0003 + `RelationalAttachmentRepository` +
  **required guard updates** (demote `attachment` vocabulary; swap
  unexpected-table probe) + relational parity tests.
- **4.14.D** `LocalAttachmentContentStore` (explicit root, containment, atomic
  writes) + `Settings` (`AVA_ATTACHMENT_STORAGE`/`_ROOT`) + composition wiring.
- **4.14.E** `AttachmentService` orchestration (pending→put→verify→available;
  failure invariants) + crash/failure tests.
- **4.14.F** minimal API: create/list/get/content endpoints, streaming +
  safe headers, error contract; declare `python-multipart`.
- **4.14.G** frontend contracts + api-client seam + mocked-`Blob` tests (no UI).
- **4.14.H** validation, boundary guards (ports/adapters/service), log update.

## Explicitly deferred

Attachment picker/drag-drop/composer/document-browser UI, image preview
gallery, PDF viewer, virus/malware scanning, OCR, RAG ingestion,
vectorization, chunking, document conversion, cloud-specific adapters (S3,
Azure, Volume), signed URLs, multi-part chunked cloud upload, delete UI,
restore, auth, sharing, collaboration, orphan-cleanup sweep, filename/media
policy enforcement, size limits.

## Files inspected

- Backend: `ava/contracts/requests.py`, `ava/contracts/documents.py`,
  `ava/repositories/*.py` (document/document_revision/message ports and
  records), `ava/services/document_service.py`,
  `ava/services/document_write_coordinator.py`,
  `ava/api/app.py`, `ava/api/routes/documents.py`,
  `ava/configuration/settings.py`,
  `ava/infrastructure/composition.py`,
  `ava/infrastructure/persistence/composition.py`,
  `ava/infrastructure/persistence/database.py`, `serialization.py`,
  `migrations/versions/v0001_initial_schema.py`/`v0002_document_revisions.py`,
  `backend/pyproject.toml`,
  `backend/tests/test_architecture.py`, `backend/tests/test_persistence_migrations.py`.
- Frontend: `packages/contracts/src/documents.ts`,
  `packages/api-client/src/client.ts`, `packages/api-client/src/documents.ts`,
  `packages/api-client/src/index.ts`,
  `packages/document-core/src/model/document.ts`, `model/documentContent.ts`,
  `state/DocumentProvider.tsx`, `index.ts`.
- Docs: `AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md` (§5.4),
  `AVA_Phase_4_Persistence_Architecture_Audit.md`,
  `AVA_Phase_4_Implementation_Log.md`, `AVA Development Plan.md`,
  `AVA_Sprint_2_Plan.md`, `.env.example`.

## No production changes

This audit made no production-code, migration, schema, dependency, or
configuration changes. The only artifact produced is this design document.

*Subsequent implementation slices (4.14.A–4.14.G) implemented the design; the
4.14.H closure slice validated it. Production changes live in the
implementation log, not here.*