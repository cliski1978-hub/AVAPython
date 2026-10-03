# Phase 5.43 — Conversation Organization Metadata Persistence

Conversation organization metadata is durable in SQLite. Migration 0010 adds
`is_pinned` and `is_archived` as `INTEGER NOT NULL DEFAULT 0`, constrained to
`0`/`1` using the existing boolean convention, and nullable `folder_id TEXT`
without a foreign key. Existing and newly created rows default to
`false` / `false` / `null`.

The existing migration registry and transactional runner apply the additive
migration during normal database bootstrap. A version-9 database upgrades
without reset, preserving conversation identifiers, titles, and timestamps.
Repeated startup verifies the schema without reapplying the migration.

Relational get/list/rename projections and the shared row mapper restore all
three values. Legacy row projections missing the fields retain canonical
defaults. Creation relies on the schema defaults, verified against the stored
row. The memory store needs no changes: it retains complete records and uses
`dataclasses.replace` for rename. SQLite rename updates only title/timestamp.

Tests seed metadata directly in storage because organization write APIs do not
exist yet. Explicit values survive disposal and reopening, reach API single
and list responses unchanged, survive the normal HTTP rename path, and remain
intact after a subsequent reopen. Both repositories retain insertion order and
include archived conversations.

Production changes are limited to migration 0010, its registry registration,
the relational conversation projection, and the serialization row mapper.
Inspection confirms organization fields only participate in conversation
storage and read responses; run creation, context construction, runtime/model
selection, and streaming remain unchanged. No pin/archive/folder write path,
folder entity/table, filtering, sorting, delete, Projects, or UI work is added.

Validation: 154 focused backend tests pass, including the 10 Phase 5.42 metadata
tests and 9 new persistence cases. Existing migration/database expectations now
include version 10. Ruff, mypy on touched backend files, and `git diff --check`
pass. Tests cover repositories, conversation service/API, conversation/message
activation, migration/bootstrap, and persistence durability. The full canonical
suite was not run: the migration is local and shared runner mechanics are
unchanged. HTTP tests ran outside the sandbox after TestClient's AnyIO thread
startup stalled inside it.

Phase 5.43 complete. Phase 5.44 not started.
