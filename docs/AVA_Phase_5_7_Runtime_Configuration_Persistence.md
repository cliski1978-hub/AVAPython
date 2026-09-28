# AVA Phase 5.7 — Runtime Configuration Persistence

Phase 5.7 makes the Phase 5.6 `RuntimeConfiguration` domain durable using the
same repository, migration, and composition patterns established for provider
connections (5.3) and model configurations (5.5).

It persists configuration records only. Runtime *resolution* is unchanged:
`RuntimeRegistry`, `RuntimeResolver`, `ExecutionSelector`, `AgentPort`, and
`RunService` are untouched, and the persisted record is not wired into
execution.

## Repository port

`ava.repositories.RuntimeConfigurationRepository` is the AVA-owned persistence
port. It accepts and returns only `RuntimeConfiguration` and exposes exactly
four operations:

| Operation | Behavior |
| --- | --- |
| `create` | Create the record, or raise `ValueError` for a duplicate `runtime_configuration_id` |
| `get` | Return the snapshot for a `runtime_configuration_id`, or `None` when unknown |
| `list` | Return every record in stable insertion order |
| `update` | Replace mutable metadata for an existing record, or return `None` when unknown |

The port deliberately has no `delete`, no runtime-resolution method, and no
model/provider lookup method. Configuration records are created, replaced, and
read; nothing here resolves an `AgentRuntimePort`. A test asserts the public
surface is exactly `{create, get, list, update}` and that the port module
imports only `ABC`, `abstractmethod`, `Collection`, and `RuntimeConfiguration`.

## Implementations

`RuntimeConfigurationStore` (`ava.services.runtime_configuration_store`) is the
in-memory implementation. `RelationalRuntimeConfigurationRepository`
(`ava.infrastructure.persistence.repositories`) is the SQLite adapter. Both
raise the same `ValueError` on a duplicate id, return `None` for an unknown
read or update, and list in insertion order. A parametrized fixture runs the
same behavioral tests against both.

## Schema and migration

Migration `v0006_runtime_configurations` creates the minimum table:

```text
runtime_configurations(
    id,                          -- surrogate insertion-order key
    runtime_configuration_id,    -- TEXT NOT NULL UNIQUE
    runtime_type,                -- TEXT NOT NULL
    display_name,                -- TEXT NOT NULL
    enabled                      -- INTEGER NOT NULL CHECK (enabled IN (0, 1))
)
```

The migration is additive: it leaves every Phase 4 table and row, plus
`provider_connections` and `model_configurations`, unchanged. It creates no
execution-defaults, execution-profile, runtime/model-binding, runtime/provider-
binding, runtime-options-blob, or settings-history table. Verification fails
closed on a missing table, a mismatched column layout, an unexpected table, or
a missing unique index on `runtime_configuration_id`.

The relational adapter uses parameterized SQL, explicit row mapping, and
`ORDER BY id ASC` for deterministic ordering. Database errors go through the
existing `translate_database_error` convention, so a duplicate id surfaces as
`ValueError("Runtime configuration already exists: <id>")` — identical to the
in-memory message.

## Runtime-type persistence

`runtime_type` is an opaque AVA-owned adapter/framework identifier, so the
column is `TEXT NOT NULL` with no fixed vocabulary `CHECK`. AVA has no
canonical runtime-type enum: the existing `RuntimeRegistry` keys (`native`,
`openhands`) are lookup keys for already-constructed ports, not an enumeration
of supported types. Hard-coding them at the database layer would make the
schema decide which runtimes are installed, and would reject a legitimately
configured `langgraph` or `agentcore` instance before any code runs. The
domain record owns non-blank validation; the schema only enforces storage.

Round-trip is verified in both directions: tests create `native`, `openhands`,
`langgraph`, `agentcore`, and `future-adapter` records and read each type back
unchanged.

## Runtime-type immutability decision

**`runtime_type` is immutable after creation.** An `update` that changes it
raises `ValueError("Runtime configuration runtime_type cannot change")` in both
implementations, and the stored value is unchanged afterwards.

The Phase 5.6 domain is a frozen record with no reassignment operation, so
mutating the type was never a supported domain behavior. More substantively,
`runtime_type` is what a configured instance *is*: changing a record from
`native` to `openhands` would silently redefine it as a different runtime
instance while keeping the same identity, and any future reference to
`runtime_configuration_id` (a saved default, a run, a conversation preference)
would then resolve to a different kind of runtime. Identity stability is
therefore stronger than editability here. Deleting and recreating the record
is the explicit way to change type, and it gets a new identity.

`runtime_configuration_id` is the lookup key and is stable by construction.
`update` may change `display_name` and `enabled`; both round-trip through
SQLite, including re-enabling a previously disabled record.

## Persistence composition

The repository is exposed only through the persistence composition bundles:

- `PersistenceRepositories.runtime_configuration_repository` — the
  `RelationalRuntimeConfigurationRepository` over the shared `SqliteDatabase`
- `ApplicationPersistence.runtime_configuration_repository` — the
  `RuntimeConfigurationStore` in memory mode, the relational adapter in
  relational mode

`ApplicationPersistence` now carries eleven ports plus its optional `database`.
No service, `RunService`, `AgentPort`, execution selector, HTTP route,
`RuntimeRegistry`, `RuntimeResolver`, execution profile, or frontend module
consumes the new repository.

## Restart durability

Two relational tests close a file-backed database and re-open it through a
fresh repository bundle:

- creating two records (one disabled, one native, one openhands), disposing,
  and re-opening preserves configured-instance identity, runtime type, display
  name, and enabled state for each, and preserves insertion order
- an `update` that renames and disables a record survives reopen

The pre-existing `backend/tests/test_persistence_durability.py` restart proof
and `test_restart_recovery_integration.py` (seeded conversations, messages,
runs, events, documents, revisions, attachments across two restarts) continue
to pass; their schema-version expectations moved from `[1, 2, 3, 4, 5]` to
`[1, 2, 3, 4, 5, 6]`.

## Migration compatibility

A v0005 database upgrades by applying only version 6, and a Phase 4 database
reaches v0006 through the full pending chain. Both were verified to leave
existing data intact:

- provider connections and model configuration rows survive byte-for-byte
  (including `provider_id` and `provider_model_name`)
- conversations, messages, runs, run events, documents, document revisions, and
  attachments retain their row counts
- `runtime_configurations` starts empty; no rows are synthesized
- identity uniqueness and the `enabled IN (0, 1)` boolean constraint are
  enforced at the database level

## Architecture guards

Preserved, and covered by focused tests:

```text
RuntimeConfigurationRepository        remains an AVA persistence abstraction
RelationalRuntimeConfigurationRepository  remains infrastructure-only
RuntimeConfiguration                  remains independent of models/providers
RunService                            remains independent of runtime configuration
AgentPort                             remains the execution boundary
```

Two dependency guards needed a *narrow* new allowance, matching the pattern
Phase 5.3/5.5 already established for configuration-domain ports. The port
imports `ava.runtimes.configurations` (its domain record) and the adapter
imports the same record, so:

- `test_repository_ports_depend_only_on_contracts_and_each_other` allows
  `ava.runtimes` for `runtime_configuration_repository.py` only
- `test_persistence_layer_imports_only_repositories_and_contracts` allows
  `ava.runtimes` for `runtime_configuration_repository.py` only

No guard was broadened. `runtime_configurations` was added to the approved
created-table list, and the migration-version list now includes v0006. Two new
guards were added: adapters conform to their port, and no execution module
(`RuntimeRegistry`, `RuntimeResolver`, `ExecutionSelector`) references
runtime configuration.

## Execution profiles

The Phase 5.6 concern stands unchanged and is **not** addressed here.
`ExecutionProfile` still combines `runtime_id` with `model_provider_id` from
bootstrap discovery presets, while Phase 5 now has three independent
configuration records. Nothing in 5.7 altered that coupling, and no new
evidence was found that changes the plan. Reconciliation belongs to 5.8
(defaults) and 5.16 (execution configuration resolver), where a persisted
`runtime_configuration_id` finally has an authoritative record to resolve
against.

## Validation

```text
pytest tests/test_runtime_configuration_domain.py \
       tests/test_runtime_configuration_repository.py \
       tests/test_provider_connection_repository.py \
       tests/test_model_configuration_repository.py \
       tests/test_persistence_migrations.py \
       tests/test_persistence_activation.py \
       tests/test_persistence_database.py \
       tests/test_persistence_durability.py \
       tests/test_repository_behavior_compatibility.py \
       tests/test_restart_recovery_integration.py \
       tests/test_architecture.py -q
226 passed

ruff check src tests
Success

mypy src
Success: no issues found in 158 source files
```

Full backend suite: 1368 passed, 2 skipped, 11 failed. All 11 failures are
pre-existing on a clean tree and unrelated to runtime configuration — they
assert in-memory default composition while the repository-root `.env` selects
relational persistence for a full-suite run. No new failures were introduced.

## Phase 5.8 implication

Phase 5.7 adds only a fourth durable configuration record. Phase 5.8
(Application Execution Defaults) still needs the execution-defaults record and
its validation rules — that a default must reference an existing, *enabled*
record, and that an invalid default fails visibly rather than silently falling
back.

Two facts 5.7 establishes that 5.8 should rely on:

1. The three configuration records are independent. An execution default can
   reference a `runtime_configuration_id` that differs in identity from its
   `runtime_type`, so the defaults record must validate against configuration
   ids, never against `RuntimeRegistry` keys or `runtime_type` values.
2. `runtime_type` immutability means a default pointing at a
   `runtime_configuration_id` cannot be silently reinterpreted as a different
   kind of runtime later.
