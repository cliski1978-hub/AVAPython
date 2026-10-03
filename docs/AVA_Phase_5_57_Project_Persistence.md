# Phase 5.57 — Project Persistence

## Scope

This step makes the Phase 5.56 Project record durable through AVA's existing
memory and SQLite repository compositions. The relational schema is introduced
by migration 0012. No Project HTTP routes or frontend state are added.

Projects remain independent workspace/context boundaries, distinct from
organizational Conversation Folders. There is no conversation linkage,
Project files, execution defaults, prompt-instruction wiring, or
RAG/knowledge behavior in this phase.

## Schema

The `projects` table stores `id` as its primary key, required `name`, nullable
`description` and `instructions`, `is_archived` as a non-null SQLite integer
boolean with a default of `0`, and required `created_at` and `updated_at` ISO
timestamps. Timestamp serialization uses the shared aware-UTC helpers. Names
are not unique. The migration adds a standalone table and does not modify
conversation, folder, settings, or execution tables.

## Repository adapters

`ProjectRepository` defines only `create`, `get`, `list`, and `update`.
`ProjectStore` and `RelationalProjectRepository` persist the supplied canonical
record values without trimming names or generating IDs/timestamps. A duplicate
ID raises `ValueError`; an unknown ID returns `None` for `get` and `update`.

Both adapters list all Projects, including archived ones, ordered by
`is_archived` ascending, case-insensitive name ascending using Python
`casefold`, `created_at` ascending, and `id` ascending. Python-side sorting
keeps memory and SQLite behavior consistent for Unicode names.

The memory and relational repositories are available through the existing
application persistence composition. No service, API route, or UI is wired.

## Durability and compatibility

Migration 0012 creates `projects` through AVA's transactional migration
runner. A pre-0012 database upgrades in place and preserves its existing
conversation and folder data. Repeated startup/migration checks are idempotent.
Repository tests verify create/get/list/update parity, nullable and empty text,
archive persistence, direct SQLite row values, update durability, restart
durability, and SQLite integrity and foreign-key checks.
