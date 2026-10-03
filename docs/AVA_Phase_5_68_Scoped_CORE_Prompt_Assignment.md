# Phase 5.68 — Scoped CORE Prompt Assignment

**Status:** Complete. This phase persists explicit scoped enable/disable controls for reusable CORE prompt definitions. Assignments remain inert: there is no effective-prompt resolution or execution injection.

## Scope identity audit

| Scope | Identity classification | Assignment support | Validation |
| --- | --- | --- | --- |
| `global` | Canonical singleton; no target identity | Supported | `scope_id` must be null |
| `application` | No stable assignment identifier exposed by current application contracts | Deferred | Rejected as `core_prompt_scope_unsupported` |
| `project` | Durable ID | Supported | Existing Project ID required |
| `folder` | Durable ID | Supported | Existing Conversation Folder ID required |
| `conversation` | Durable ID | Supported | Existing Conversation ID required |
| `runtime` | Canonical `RuntimeRegistry` key | Supported | Must match a runtime ID registered at application startup |
| `capability` | Canonical `CapabilityName` enum value | Supported | Must match an AVA capability name |
| `model_compatibility` | Model profiles exist, but no stable compatibility identity exists | Deferred | Rejected as `core_prompt_scope_unsupported` |

Application and Model Compatibility remain reserved and serialized exactly as listed. Writes do not accept caller-invented identifiers for those scopes.

## Record and state semantics

`CorePromptRecord` remains a reusable definition; category remains independent of scope. `CorePromptAssignmentRecord` contains an opaque UUID4 `id`, `core_prompt_id`, `scope_type`, nullable `scope_id`, `mode` (`enable` or `disable`), and creation/update timestamps. It contains no prompt text or Project instructions.

The persisted states are `enable` and `disable`. The control API also accepts `inherit`, which deletes an explicit row. No row means INHERIT; there are no redundant inherit rows. Setting the same state succeeds without changing identity or timestamps. Changing enable/disable preserves ID and `created_at`, and advances `updated_at` monotonically. Disabled prompt definitions may retain assignments.

Migration **0016**, `v0016_core_prompt_assignments.py`, adds `core_prompt_assignments` after schema version 15. The prompt foreign key cascades on definition deletion. Checks constrain enum values and global-vs-target IDs. Partial unique indexes guarantee one global row per prompt despite SQLite NULL uniqueness rules and one row per prompt/type/target for non-global scopes. Lists use `scope_type`, `scope_id`, `created_at`, then `id` ordering.

## Repositories, service, and deletion

`CorePromptAssignmentRepository` has memory and SQLite adapters for explicit lookup, lists by prompt/scope, upsert, individual deletion, and cleanup. The service validates prompt and supported target existence, stable error codes, global null identity, and nonblank target IDs. It has no inheritance traversal or effective-state calculation.

Prompt deletion cascades assignment rows in the same SQLite transaction. Project and Folder repositories delete their scoped rows while clearing conversation membership and deleting the target in the same transaction. Conversation hard delete clears only conversation-scope assignments inside its aggregate transaction. Memory adapters perform matching cleanup. Project and Conversation archive preserve assignments; disabling a prompt definition also preserves assignments. Rollback tests inject failures into Project deletion and prompt deletion and verify both target/definition and assignment state remain.

## API and typed client

- `GET /core-prompts/{core_prompt_id}/assignments` lists explicit rows for a definition.
- `PUT /core-prompts/{core_prompt_id}/assignments` sets `enable`, `disable`, or removes the row with `inherit`.
- `GET /core-prompt-assignments?scope_type=…&scope_id=…` lists explicit rows for a supported scope.

Responses report `state`, and return null `assignment_id`/timestamps for INHERIT. Shared TypeScript contracts and the typed API client expose all three operations. No Python client change was needed because it does not mirror CORE prompt resources.

## Boundaries

No selector UI, effective-prompt resolver, parent-scope precedence, default prompt seeding, or execution injection was added. `RunService`, agent ports/adapters, provider prompt assembly, and `Project.instructions` are unchanged. Folder/Conversation custom instructions remain out of scope.

## Validation

Focused tests cover memory/SQLite state parity, idempotency, update identity/timestamps, global SQL uniqueness, target validation, unsupported scopes, migration and restart persistence, cascade and target cleanup, rollback, and archive preservation. `PRAGMA integrity_check` returns `ok` and `PRAGMA foreign_key_check` returns no rows. Frontend contract/API-client tests and TypeScript checks cover the exact scope/state vocabularies and URLs.
