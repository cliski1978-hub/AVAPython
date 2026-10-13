# AVA Phase 5.76 — Project Files Persistence, API, and Client

Phase 5.76 gives Project Files durable metadata, independently managed binary content, Project-scoped HTTP operations, and typed shared-client methods. Project Files remain inert data resources. The UI, automatic parsing, execution context, embeddings, chunking, retrieval, vector storage, and RAG remain unimplemented.

## Persistence and storage

Migration **0018** creates `project_files` with the Phase 5.75 metadata fields: ID, owning Project ID, display filename, optional content type, measured byte size, opaque content reference, and timestamps. Migration **0023** adds a trimmed, Unicode case-folded filename key and a unique constraint over `(project_id, normalized_file_name)`. Filename uniqueness is Project-scoped; a different Project may use the same name. Memory and SQLite repositories use the same deterministic order: case-folded filename, creation timestamp, then ID.

Binary bytes are kept behind `ProjectFileContentPort`; the Project-file port and adapters do not use Conversation Attachment ownership. The memory adapter supports tests and ephemeral deployments. The local adapter streams in 1 MiB blocks to a temporary file and atomically links the completed bytes under the configured root. It accepts only generated 32-character lowercase hexadecimal references. The user filename never participates in physical path construction. Configure local storage with `AVA_PROJECT_FILE_STORAGE=local` and `AVA_PROJECT_FILE_STORAGE_ROOT=/path/managed/by/ava`; metadata persistence remains selected independently by `AVA_PERSISTENCE`.

## Lifecycle and transaction behavior

Uploads validate Project and display metadata, reject an existing normalized filename before writing content, generate a UUID file ID and independent UUID-hex content reference, stream bytes to content storage, derive `size_bytes` from the adapter's byte count, then persist metadata. The database uniqueness constraint arbitrates concurrent uploads; a losing write removes its temporary content and returns a conflict. If other metadata persistence fails, the just-written content is deleted. If compensation fails or unexpectedly finds no just-written content, the service logs the internal file ID and raises a recoverable storage/consistency error; it never logs file bytes. Migration 0023 stops without changing records when it finds preexisting normalized duplicates and reports the conflicting Project/file IDs.

Single-file and Project deletion commit metadata deletion before deleting binary content. SQLite Project deletion collects content references first and deletes the Project and cascading file metadata in one transaction. A transaction failure leaves both metadata and bytes intact. A later content cleanup failure is reported explicitly after metadata commit; it may leave an orphaned binary object for repair, while the application and metadata database remain usable. Memory Project deletion removes the Project-owned metadata together with its existing conversation membership and CORE assignment cleanup.

Archived Projects retain files and remain readable and writable. Empty files are supported. Duplicate filenames are rejected within a Project with HTTP 409; the same filename remains valid in another Project. Deleting a file releases its name for re-upload. Filenames and content types are metadata only; MIME values containing response-header control characters fall back to `application/octet-stream` for downloads.

## HTTP and typed client

Project routes are:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/projects/{project_id}/files` | Multipart upload (`file`, optional explicit `file_name`, optional `content_type`) |
| `GET` | `/projects/{project_id}/files` | Ordered metadata list |
| `GET` | `/projects/{project_id}/files/{file_id}` | Metadata lookup |
| `GET` | `/projects/{project_id}/files/{file_id}/content` | Streamed download with safe UTF-8 `Content-Disposition` |
| `DELETE` | `/projects/{project_id}/files/{file_id}` | Metadata and owned content deletion |

Wrong-Project access uses `project_file_not_found` so the API does not reveal whether another Project owns the ID. Missing Projects use the existing `project_not_found` error. Public metadata contracts never include `content_ref` or filesystem information. Shared TypeScript methods use `FormData` for upload and `ApiClient.requestBlob` for downloads; no Python-client mirror exists for this resource API.

## Boundaries and validation

Routes depend on `ProjectFileService`; the service depends on Project, metadata, and content ports. Composition chooses the memory or local content adapter. URLs accept only Project and file IDs; callers cannot supply a storage reference or path. Uploads are not parsed, executed, attached to Conversations, or injected into prompts or runs.

Focused evidence is recorded in `backend/tests/test_project_files.py`, migration tests, Project API tests, Project-file domain/architecture tests, and the API-client Project tests. Local filesystem content is streamed to and from disk; multipart parsing uses FastAPI/Starlette's spooled upload abstraction, with no application-defined upload size cap.

## Phase 5.76A validation and stabilization

Phase 5.76A added a disposable SQLite/ASGI lifecycle validation and documented the sandbox-only limits on the canonical TestClient and TCP server paths. The full test and diff details are in [AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md](AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md). The Project Files implementation is certified under the documented external-blocker policy; a real loopback server could not bind in this restricted shell.
