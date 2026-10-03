# Phase 5.66 — CORE System Prompt Domain

**Status:** Complete. This phase defines the reusable AVA-owned CORE prompt
definition and its shared contracts. Definitions are inert: no storage,
assignment, resolver, API, UI, or execution behavior was added.

## Canonical domain concept

`CorePromptRecord` is the canonical immutable snapshot for a reusable CORE
System Prompt. Its opaque AVA-owned `id` is its stable identity; display names
are human-readable and need not be unique. The record contains:

| Field | Meaning |
| --- | --- |
| `id` | Stable opaque AVA identity, supplied by a future creation boundary |
| `name` | Nonblank human-readable label |
| `description` | Optional nullable metadata; never execution content |
| `prompt_text` | Exact reusable instruction text; multiline, Markdown, Unicode, and whitespace are preserved |
| `category` | `CorePromptCategory`, for future UI organization |
| `is_enabled` | Whether the definition is available to future assignment/resolution; new records are expected to default to `true` |
| `created_at`, `updated_at` | Aware UTC timestamps carried by the record; future write boundaries own their values |

The category values use lowercase serialization: `core`, `engineering`,
`research`, `safety`, `style`, `tool_use`, `architecture`, `organization`, and
`general`. A category describes the topic of a reusable definition. It is not
a scope: `CorePromptCategory` ≠ `CorePromptScope`.

Write contracts reject blank names and whitespace-only `prompt_text` while
preserving the submitted values. Description may be omitted or null. On
updates, Pydantic's `model_fields_set` retains omitted-versus-null semantics:
omission preserves description and explicit null clears it. `prompt_text` is
required and non-null. No token, provider, model, runtime, or formatting limits
are imposed.

## Contract boundary

Backend contracts are `CreateCorePromptRequest`, `UpdateCorePromptRequest`,
and `CorePromptResponse`. The shared TypeScript package exports matching
`CorePrompt`, `CorePromptCategory`, `CreateCorePromptRequest`, and
`UpdateCorePromptRequest` types. The backend enum and frontend union are
covered against the same nine-value vocabulary.

The repository has no Python API client that mirrors these resource contracts;
its HTTP clients are runtime/provider integrations. No client architecture was
introduced for this domain phase.

## Future architecture boundary

The concept boundaries are intentionally separate:

```text
CorePromptRecord
    reusable definition

CorePromptAssignment
    future: where it applies

EffectivePromptResolver
    future: which prompts are active

ExecutionContextAssembly
    future: how resolved prompt layers become model input
```

Prompt Definition ≠ Prompt Assignment. Prompt Assignment ≠ Prompt Resolution.
Prompt Resolution ≠ Execution Injection. Category is not scope. Future scopes
may include Global, Application, Project, Folder, Conversation, Runtime,
Capability, or Model Compatibility; none exist in this phase. Project
instructions remain independent Project-specific customization.

The documented future hierarchy is:

```text
AVA Root System
    ↓
Resolved CORE Prompt Profiles
    ↓
Scoped Custom Instructions
    ↓
Conversation History
    ↓
User Message
```

This is architecture documentation only. `CorePromptRecord` has no priority,
scope IDs, inheritance controls, provider/runtime binding, message role,
assignment state, or execution behavior. The existing AVA root prompt,
Project instructions, context construction, and runtime adapters are unchanged.

## Naming audit

The repository contains Project `instructions` metadata/UI and generic runtime
system-message/context-window handling, but no existing AVA-owned reusable
prompt-profile abstraction. `CorePromptRecord` was selected consistently with
the feature name “CORE System Prompt,” avoiding collision with the runtime's
provider-facing message structures.

## Scope and validation

Added the domain record and category enum, Pydantic request/response contracts,
matching shared TypeScript definitions, focused backend/frontend contract
tests, and this documentation. No migration, table, repository port, service,
route, client API, assignment model, UI, or execution integration was added.

Validation evidence:

- Backend CORE prompt plus Project and shared contract coverage: 61 passed.
  One stale Project-domain assertion was excluded because it expects
  `ConversationRecord` not to have `project_id`, although the current codebase
  already implements that Phase 5.61 relationship. Running the complete two
  domain files directly confirmed the other 14 tests pass and that one fails
  for this unrelated expectation.
- Shared TypeScript contract package: 35 tests passed; `tsc --noEmit` passed.
- Ruff and focused mypy checks passed; `git diff --check` passed.
- Mutation proof: temporarily disabling blank `prompt_text` validation caused
  exactly 1 of 6 CORE prompt tests to fail. The validator was restored and all
  6 tests passed again.

No full canonical suite was run.
