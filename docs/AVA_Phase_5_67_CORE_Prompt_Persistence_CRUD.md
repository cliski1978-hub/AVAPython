# Phase 5.67 — CORE Prompt Persistence, CRUD, and Enable/Disable

**Status:** Complete. Phase 5.67 makes the Phase 5.66 reusable `CorePromptRecord`
durable and manageable. Prompt definitions remain inert: this phase adds no
assignment, scope, inheritance, resolution, or execution behavior.

## Durable schema

Migration **0015**, `v0015_core_prompts.py`, creates `core_prompts` with
`id TEXT PRIMARY KEY`, non-null `name`, `prompt_text`, `category`,
`is_enabled`, `created_at`, and `updated_at`, and nullable `description`.
`is_enabled` is an integer constrained to 0 or 1 and defaults to 1. No names
are unique. The schema contains no scope, assignment, provider/runtime, or
priority columns.

The migration is additive and transactional under AVA's migration runner. A
populated version-14 database upgrades to version 15 without changing its
Project or Conversation rows. Repeated startup at version 15 applies no
migrations. Migration version assertions directly affected by this canonical
version advance were updated from 14 to 15. The unrelated existing
`test_project_has_no_future_relationship_or_execution_fields` assertion still
expects `ConversationRecord` to lack `project_id`, despite the implemented
Phase 5.61 relationship; it remains unchanged and is excluded from focused
Phase 5.67 regression validation.

## Repository, service, and ordering

`CorePromptRepository` defines `create`, `get`, `list`, `update`,
`set_enabled`, and `delete`. `CorePromptStore` is the memory adapter;
`RelationalCorePromptRepository` is the SQLite adapter registered through the
standard application persistence composition. The row mapper deserializes
category through `CorePromptCategory(value)`, so unknown stored values fail
instead of being remapped.

Both adapters return definitions in this exact order:

```text
category.value ASC
name.casefold() ASC
created_at ASC
id ASC
```

Enabled state does not affect list order. Updates can only write name,
description, prompt text, category, and `updated_at`; identity, creation time,
and enabled state are preserved. Enable/disable has its own repository and
service operation.

`CorePromptService` exposes `create_core_prompt`, `get_core_prompt`,
`list_core_prompts`, `update_core_prompt`, `set_enabled`, and
`delete_core_prompt`. It generates UUID4 IDs, trims names at the write
boundary, rejects blank names and whitespace-only prompt text, and uses
aware UTC timestamps. A created record begins enabled with equal creation and
update times. Description values (`None`, empty, multiline, and Unicode) are
preserved. Prompt text is stored exactly as received after blank-only
validation, including leading/trailing whitespace, line breaks, indentation,
Markdown, and Unicode. Omitted update descriptions preserve their value;
explicit null clears it; an empty string remains an empty string.

An actual enable-state change advances `updated_at`. Repeating the current
state succeeds without changing `updated_at`. Delete is permanent; repeating
it reports `core_prompt_not_found`. The same stable `core_prompt_not_found`
error is used by get, update, and enable/disable.

`is_enabled` is persisted lifecycle/configuration state only. With no resolver
in this phase, enabled or disabled prompts have **no execution effect**.

## Public API and typed client

Routes:

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/core-prompts` | `201` and canonical `CorePromptResponse` |
| `GET` | `/core-prompts` | All definitions in repository order |
| `GET` | `/core-prompts/{core_prompt_id}` | Definition or `404 core_prompt_not_found` |
| `PATCH` | `/core-prompts/{core_prompt_id}` | Updated definition |
| `PATCH` | `/core-prompts/{core_prompt_id}/enabled` | Updated enabled state |
| `DELETE` | `/core-prompts/{core_prompt_id}` | `204`, or `404 core_prompt_not_found` |

The shared Phase 5.66 contracts are reused, with a narrow enabled-state
request and list response added. The TypeScript API client provides
`listCorePrompts`, `getCorePrompt`, `createCorePrompt`, `updateCorePrompt`,
`setCorePromptEnabled`, and `deleteCorePrompt`. Its tests cover methods, URLs,
JSON bodies, omitted/null descriptions, multiline Unicode text, 204 handling,
and `ApiError` propagation.

## Validation evidence

- Focused backend CORE prompt domain, repository, service, API, and migration
  tests: **48 passed**.
- Memory and SQLite adapters run the same CRUD, ordering, update, enable,
  delete, and not-found cases. File-backed tests reopen the database after
  create/update/disable and after delete, then compare every record field.
- Direct SQL checks verify the exact stored text and description, category
  serialization, integer disabled state, and timestamps. `PRAGMA integrity_check`
  returned `ok`; `PRAGMA foreign_key_check` returned no rows.
- The migration test advances a populated version-14 database and confirms
  prior Project and Conversation data remains present; a second migration call
  is a no-op.
- API routes were exercised through HTTPX `ASGITransport` with memory and
  relational persistence; no TestClient lifespan stall occurred.
- Phase 5.66 domain/contract tests, shared contract tests, and API-client tests
  pass; Ruff, mypy, TypeScript checks, and `git diff --check` pass.
- Mutation proof: changing SQLite row mapping to always report enabled caused
  the SQLite disable test to fail. The mutation was reverted and focused tests
  passed again.

No prompt selector UI, assignment model/table, scope relationship, inheritance
operation, Project/Folder/Conversation linkage, resolver, or execution
injection was added. `Project.instructions` and runtime execution behavior are
unchanged.
