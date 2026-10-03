# Phase 5.58 — Project CRUD Service and Public API

Phase 5.58 adds application-level Project lifecycle behavior and exposes it
through the public API and typed API client. Projects remain standalone
metadata records in this phase.

## Service behavior

`ProjectService` owns name normalization, timestamps, archive semantics, and
not-found mapping. Creation trims the name and rejects a blank result with an
AVA-owned validation error. Duplicate display names are allowed. The service
generates a UUID4 identifier, uses aware UTC timestamps, initializes
`updated_at` to `created_at`, and starts the Project unarchived. Description
and instructions are preserved exactly, including `None` and empty strings.

Updates require a name, which is trimmed and validated. The existing request
contract makes description and instructions optional: omitting either field
preserves its stored value, while explicitly sending `null` clears it. Updates
preserve `id`, `created_at`, and archive state, and advance `updated_at`.
Project instructions are persisted metadata only and are not used to construct
run context or model prompts.

Archive and restore use a dedicated idempotent mutation. Repeating the
current state leaves the record and timestamp unchanged. Archived Projects
remain in list results. The canonical ordering remains:

```text
is_archived ASC, case-insensitive name ASC, created_at ASC, id ASC
```

Delete permanently removes the standalone Project metadata row. A missing
Project, including a repeated delete, raises the same `project_not_found`
application error. No conversation or file cleanup exists in this phase.
Future linkage work may extend service-level cleanup while retaining the
public delete contract.

## Public API and typed client

The API exposes:

```text
POST   /projects                 201 Created
GET    /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
PATCH  /projects/{project_id}/archive
DELETE /projects/{project_id}    204 No Content
```

Successful reads and writes use the shared `ProjectResponse` contract. Lists
return `ProjectListResponse`. Unknown IDs return HTTP 404 with the stable
`project_not_found` error code. Request validation errors use the normal AVA
validation response. The typed API client implements list, get, create,
update, archive/restore, and delete; it handles the empty 204 response and
propagates `ApiError` failures.

The memory and SQLite repositories implement the same delete result and list
ordering. Relational lifecycle tests cover create, update, archive, restore,
and delete across database reopen.

## Scope boundary

This phase adds no Project UI, conversation linkage, Project files, execution
defaults, prompt injection, RAG, or knowledge behavior. In particular,
instructions remain inert data. Delete currently removes only the standalone
Project metadata row.
