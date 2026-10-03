# Phase 5.72 — Project Execution Defaults

**Status: COMPLETE.** This step adds Project-scoped runtime and model preferences to the domain, persistence, API, and typed TypeScript client. They remain inert: no execution precedence, selector input, settings UI, or Project UI was added.

## Existing selection architecture audited

| Concept | Existing identity | Existing location / role |
| --- | --- | --- |
| Runtime selection | Runtime registry key (`native`, `openhands`) | `RunExecutionOverride.runtime_id` / `RunExecutionSelection.runtime_id`; resolved by `RuntimeResolver` against `RuntimeRegistry` |
| Configured runtime | `runtime_configuration_id` and `runtime_type` | `runtime_configurations`; distinct from a runtime registry key |
| Model selection | Stable AVA `model_id` | Run selection and configured model records; configured through `ModelConfigurationRepository` |
| Provider | Provider adapter `provider_id` | Provider registry; identifies implementation, not a configured deployment |
| Provider connection | `provider_connection_id` | Durable provider connection; owns endpoint and credential reference |
| Global defaults | Configured provider connection, model, and runtime configuration IDs | `application_execution_defaults`; used by the existing execution configuration resolver |
| Explicit run selection | Optional per-run runtime/model/provider override axes | `RunExecutionOverride`; applied by the existing selector over application execution configuration |

The runtime key and configured runtime ID are intentionally different. Project preferences use the runtime registry key because that is the runtime identity consumed by run selection. The model preference uses AVA's stable `model_id`; provider identity, provider connection identity, and provider-native model names remain derivable from the configured model and are not copied into Project state.

The current selector starts from persisted application execution configuration and applies any explicitly supplied per-run axes over it; axes omitted by the run request retain the persisted values. If no persisted application selection exists, it uses the existing bootstrap fallback. Phase 5.72 does not insert Project preferences into this path. The intended future precedence remains unimplemented.

## Domain and persistence

`ProjectRecord.execution_defaults` contains a frozen `ProjectExecutionDefaults` value with independently nullable `runtime_key` and `model_id`. Existing constructors and Project creation continue to get null/null defaults. A Project references these configured resources; it does not own them. No compatibility pairing between runtime and model is enforced.

Migration **0017**, `backend/src/ava/infrastructure/persistence/migrations/versions/v0017_project_execution_defaults.py`, adds nullable `projects.default_runtime_key` and `projects.default_model_id` columns. Existing records receive null values without row rewrites. The model column references `model_configurations(model_id) ON DELETE SET NULL`, so configured model removal cannot leave a dangling Project preference. There is no configured-model delete API/repository port today; the database relationship provides cleanup if deletion is introduced through the existing repository lifecycle. Runtime registry keys have no database FK because the registry is in-memory. The current registry has no unregister path, so stale runtime keys are retained and GET reports `runtime_available: false` until the preference is replaced or cleared.

Memory storage persists the whole Project snapshot. SQLite serialization and CRUD persist both columns. Empty PATCH is a no-op. Omitted fields preserve their current values; explicit null clears only that axis. Archived Projects can read and update defaults. Project deletion removes the inline columns with the Project row, while existing conversation unassignment and CORE assignment cleanup remain unchanged.

## API and client

- `GET /projects/{project_id}/execution-defaults`
- `PATCH /projects/{project_id}/execution-defaults`

The response contains `project_id`, `runtime_key`, `model_id`, and a nullable `runtime_available` status. Runtime references are checked against `RuntimeResolver`; model references are checked against configured models and disabled models are rejected using the existing model validation errors. A missing Project uses `project_not_found`. Runtime and model validation are independent.

The TypeScript contracts add `ProjectExecutionDefaults` and `UpdateProjectExecutionDefaultsRequest`. The API client adds `getProjectExecutionDefaults` and `updateProjectExecutionDefaults`, both using the shared `ApiClient`. The Python client has no Project configuration surface to extend, so it was left unchanged.

## Boundaries

Project runtime and model preferences do not alter run selection, provider selection, prompt resolution, Project instruction injection, permissions, conversation membership, or folder membership. They do not add controls to Project settings, application settings, or the chat composer. Global Execution Defaults, Project Execution Defaults, and Explicit Run Selection remain distinct concepts; Project runtime and Project model preferences remain independently nullable.

## Validation record

Validation:

- Schema-16 populated upgrade: Project, conversation, folder, message, run, run event, CORE prompt, and assignment rows survived; migrated defaults were null/null. Repeated migration was a no-op. SQLite integrity was `ok` and the FK check returned no rows.
- Memory and SQLite tests covered null defaults, setting both references, independently updating/clearing each reference, omitted-field preservation, archived Projects, invalid runtime/model rejection without mutation, independent runtime/model validation, Project deletion, restart durability, direct SQL values, and model-reference cleanup via `ON DELETE SET NULL`.
- API tests covered GET/PATCH, empty-PATCH no-op, omitted versus explicit null, missing Project, invalid runtime/model, archived Project behavior, and unchanged global defaults/conversation membership.
- A run-selection regression set Project defaults to `openhands`/`ava/large`; the following run still selected `native`/`ava/small`/`shared` from the existing selector configuration.
- Mutation proof: changing the runtime update condition so omitted `runtime_key` was treated as null made the targeted memory and SQLite cases fail (**2 failures**). The mutation was reverted and the cases passed.
- Focused Phase 5.72 backend run: **53 passed** before the final no-execution-effect assertion; final focused Project/API/selector run: **7 passed**.
- Canonical `./scripts/test_all.sh`: backend **2,440 passed, 6 skipped**; backend Ruff and mypy passed; frontend workspace tests and TypeScript lint passed; Python client **10 passed**, Ruff and mypy passed. The one additional selector regression added after the canonical run passed independently.
- Focused frontend package tests: contracts **38 passed**, API client **110 passed**. Both package TypeScript checks passed; the canonical workspace lint also passed.
- Final `git diff --check` passed.

**Phase 5.72 complete. Project execution defaults remain inert. The next Project execution-default resolution/UI step has not started.**
