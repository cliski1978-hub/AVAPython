# Phase 5.75 — Project Files Domain

**Status: COMPLETE**

Phase 5.75 defines Project-owned file metadata, its content boundary, a metadata repository port, and storage-neutral public contracts. It adds no adapter, persistence, migration, route, upload/download transport, UI, execution behavior, prompt behavior, or knowledge/RAG capability.

## Existing attachment and content architecture

AVA's attachment design separates two concerns:

- `AttachmentRecord` and `AttachmentRepository` own attachment metadata.
- `AttachmentContentStore` owns byte streams through opaque `storage_key` values; the local adapter keeps physical paths behind infrastructure.

Attachment metadata supports nullable owner pairs for Document, Conversation, or Message ownership. Attachments have their own status lifecycle and upload service. Conversation hard-delete coordination removes conversation and message-owned attachment metadata and coordinates their storage keys for content cleanup. That owner model and lifecycle do not define Project file ownership.

The existing content port is binary-only at the method level, but its contract is explicitly attachment-scoped: keys are per-attachment and immutable, and its implementations and lifecycle are named for attachments. No generic AVA content port exists. This phase therefore defines a distinct `ProjectFileContentPort` (`write`, `read`, `delete`, `exists`) and deliberately adds no storage adapter. This keeps Project file identity/lifecycle separate without changing or aliasing conversation attachments. A future shared content abstraction would require its own explicit refactor.

The existing attachment content metadata has no canonical content hash; its contract explicitly defers checksum support. Project files therefore add no hash field. AVA has no general attachment upload-size policy: zero-byte files are accepted. The 10 MiB OpenHands file-tool limit is runtime sandbox policy, not a general upload limit, so Project file size limits are deferred.

## Domain and ownership

`ProjectFileRecord` is an immutable metadata snapshot with these fields:

```text
id, project_id, file_name, content_type, size_bytes, content_ref,
created_at, updated_at
```

The ID is opaque and stable; the future ProjectFileService will mint UUID4 identities. `project_id` is required and identifies the sole owning Project. The same physical source added to another Project will later be represented by a separate ProjectFile resource. Duplicate filenames within one Project are allowed because identity is the record ID, not its display name.

`file_name` preserves the authored Unicode display name and is never a path. `content_ref` is an internal opaque AVA reference to separately stored bytes. `content_type` is optional metadata and has no parsing semantics. `size_bytes` is a non-negative integer, including zero; the future service records the content port's measured byte count. Timestamps must be timezone-aware.

The record intentionally has no content bytes, conversation/message/run linkage, runtime/model/provider linkage, source/origin, archive flag, version, hash, extraction/parsing state, embedding/index state, vector-store identity, or retrieval data.

## Ports and lifecycle boundaries

`ProjectFileRepository` is metadata-only and defines:

```text
create(record)
get(file_id)
list_by_project(project_id)
delete(file_id)
delete_by_project(project_id)
```

List order is filename Unicode `casefold()` ascending, then `created_at` ascending, then ID ascending. Delete operations return the removed metadata record(s), allowing a future service to coordinate owned content cleanup; the repository itself never reads, writes, or returns bytes. It does not look up Projects; future service operations validate Project existence through existing Project infrastructure.

`ProjectFileContentPort` is a separate binary port with an opaque reference. It has no filesystem/object-storage adapter in this phase and exposes no provider URL or path. A future ProjectFileService owns Project validation, metadata creation, content coordination, listing, reading, deletion, and Project-level cleanup.

Project files are hard-delete-only. Archiving a Project preserves its files; they remain subject to the archived Project's access/manage policy. Deleting a Project file deletes both its metadata and owned content. Deleting a Project deletes its Project file metadata and content. Future infrastructure must coordinate these cross-store effects: metadata failure cannot leave content irreversibly orphaned, and content failure cannot be reported as completed metadata cleanup. This phase adds no transaction/saga abstraction.

## Public contracts and security boundary

The internal `ProjectFileRecord` includes `content_ref`; public `ProjectFileResponse` does not. `CreateProjectFileRequest` carries only `file_name` and optional `content_type`; the future upload transport carries bytes separately. The public collection contract remains scoped to one `project_id`. No Python client or API routes are added.

The existing error contract already has the generic `not_found` category and string `error_code`. The future service/API may use the stable `project_file_not_found` code alongside existing `project_not_found`; this phase adds no error alias or registration.

The future upload implementation must treat filename, MIME type, and extension as untrusted metadata. A filename must never be used as a filesystem path or storage key. Infrastructure must generate an opaque storage location and perform traversal-safe resolution. Access to a Project file requires access to its owning Project; authorization is not implemented here.

The future knowledge flow may consume Project files as source resources:

```text
ProjectFileRecord.id → future knowledge ingestion/indexing
```

The record ID is the stable source identity; no separate knowledge document ID is introduced. A future content replacement must invalidate/rebuild dependent indexes. The Project File domain has no dependency on embeddings, vector stores, retrievers, or language models. Files remain inert: no conversation prompt inclusion, retrieval, run creation, execution selection, Project instructions, or CORE prompt behavior changes.

## Validation

Domain tests cover required identity/ownership/content references, Unicode names, zero-byte files, negative and non-integer sizes, aware timestamps, trimmed/case-folded Project filename normalization, metadata-only record shape, distinct attachment and Project-file types, and repository/content port shapes. Contract tests cover create/response/list shapes, optional content type, zero and negative sizes, aware timestamps, and exclusion of content references and storage locations. Architecture tests prevent domain/port/contract imports from storage adapters, execution/provider layers, or future knowledge/RAG modules. TypeScript tests pin the matching public metadata shapes.

Validation passed: the focused backend set (Project file domain, Project file
contracts, and architecture guards) reported **149 passed**; TypeScript
contracts reported **41 passed**; focused Ruff and mypy checks passed; and
`git diff --check` passed. The mutation check temporarily exposed `content_ref`
on `ProjectFileResponse`; the safe-metadata contract test failed (**1 failed**)
as expected. The field was removed and the focused tests passed again.

No persistence implementation, schema migration, API route, Project Files UI, execution change, prompt change, or knowledge/RAG implementation was added. The existing Project Files tab remains a placeholder.
