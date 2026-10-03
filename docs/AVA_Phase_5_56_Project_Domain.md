# Phase 5.56 — Project Domain

## Purpose

AVA Projects establish a durable workspace and context boundary that can later
own conversations and related context. A Project is distinct from a
Conversation Folder: a folder is an organizational grouping for conversations,
while a Project is a workspace/context concept.

This step defines the domain record and public contracts only. It adds no
persistence, migrations, repositories, routes, UI, or Project file behavior.

## Domain fields

`ProjectRecord` contains a stable opaque `id`, a `name`, optional `description`
and `instructions`, reversible `is_archived` state, and `created_at` and
`updated_at` timestamps. The ID is AVA-owned and remains the stable identity
when the display name changes. Timestamps follow AVA's aware-UTC convention;
creation initializes both equally, and future metadata writes will advance
`updated_at`.

Project names must contain a non-whitespace character. Duplicate names are
allowed because identity comes from the Project ID. Contracts reject blank
names but preserve nonblank input; future write behavior is expected to trim
the value. Description is optional descriptive metadata and is not prompt
context. Instructions are optional Project data but are not injected into
execution in this phase. New Projects start unarchived; archive is intended to
be reversible and does not imply deletion.

## Future boundaries

Conversation linkage is deferred: this step adds no `Conversation.project_id`.
Project execution defaults and Project files are also deferred. Project files
will be distinct from Phase 7 knowledge/RAG behavior; this step adds no file,
embedding, index, vector-store, or retrieval state.

## Contracts and validation

Backend public contracts define `ProjectResponse`, `CreateProjectRequest`, and
`UpdateProjectRequest`; shared TypeScript contracts mirror those shapes. The
Python client has no organizational-resource request/response contract layer,
so it remains unchanged. There are no API routes or client methods yet.

## Validation

Focused backend and TypeScript contract tests cover the canonical fields,
defaults, nonblank-name validation, and absence of future relationship and
execution fields.
