# AVA Phase 5.8 — Application Execution Defaults

Phase 5.8 introduces and persists AVA's first *application-level* execution
configuration: the configured records a default run should use. It references the
three independently persisted configuration domains from 5.3–5.7 and binds
nothing into execution.

The environment bootstrap path is untouched. Persisted defaults coexist with
`.env` bootstrap defaults and are **not** authoritative for execution yet; that
switch belongs to the later execution-resolution steps.

## 1. Where defaults exist today

Inspection found four pre-existing "default" mechanisms. None is persisted
application configuration, and Phase 5.8 keeps all four unchanged:

| Mechanism | Location | Identity it names | Persisted? |
| --- | --- | --- | --- |
| Environment/bootstrap defaults | `Settings.agent_provider`, `agent_runtime`, `model_provider`, `model_name`, `model_id`, `model_hosting_mode`, `local_model_base_url`; `Settings.resolved_model_id` | adapter ids + a derived model id | No — process environment |
| Execution-profile presets | `ExecutionProfileService` → `GET /execution-profiles` (`local-default`, `openhands-local`) | `runtime_id` (registry key) + `model_provider_id` (provider key) | No — hardcoded, read-only |
| Registry/selector defaults | `ExecutionSelector(default_runtime_id, default_model_provider_id)`, `ModelOrchestrator(default_model_id)`, `RuntimeDiscoveryResponse.default_runtime_id`, `ModelProviderDiscoveryItem.is_default` | adapter keys | No — in-process composition values |
| Frontend selection defaults | `AppWorkspace` seeds `runtimeId` from `default_runtime_id` and `profileId` from `default_profile_id` | discovery ids | No — client cache state |

`ApplicationExecutionDefaults` is a fifth concept: the only one that is durable
and the only one that names *configured* records.

## 2. Domain shape

`ava.configuration.execution_defaults.ApplicationExecutionDefaults` — a frozen
dataclass with exactly three fields:

```text
ApplicationExecutionDefaults(
    default_provider_connection_id,
    default_model_id,
    default_runtime_configuration_id,
)
```

No identity field, no version field, no timestamps. Justification: the record
is a singleton with no lifecycle of its own, so there is nothing for an
identity or a version to refer to. No other AVA record carries a version, and
inventing one would imply optimistic-locking or settings-history semantics that
no requirement asks for. Timestamps would imply audit requirements, which are
explicitly out of scope for Phase 5.8. The relational singleton is pinned by a
primary-key check instead.

The module lives in `ava.configuration` rather than `ava.models` or
`ava.runtimes` because it spans both and owns neither. It sits beside
`settings.py` but is deliberately *not* exported from that package's
`__init__`, so environment configuration and persisted configuration are not
conflated by import.

Fields are non-blank strings. The record contains no user id, conversation id,
workspace id, tool permission, fallback chain, or routing weight — this is
global application configuration for the current single-user/local stage.

## 3. Repository semantics

`ava.repositories.ExecutionDefaultsRepository` is deliberately **singular**:

```text
get() -> ApplicationExecutionDefaults | None
set(defaults) -> ApplicationExecutionDefaults
```

Not `create`/`list`/`update`/`delete`. A deployment has at most one defaults
record, so a collection shape would imply records that cannot exist. There is
no `delete`: "no defaults configured" is the absent state returned by `get`,
and clearing a default means setting a new one. A test asserts the public
surface is exactly `{get, set}`.

`get()` returns `None` until something is set — matching the fact that AVA has
no default before configuration. Absence is durable state, verified to survive
a close/reopen cycle.

## 4. Validation

`validate_execution_defaults` lives with the domain and takes already-resolved
snapshots (not repositories), keeping persistence concerns out of the domain
while guaranteeing in-memory and relational semantics cannot drift. `set`
raises `ValueError` unless all three rules hold:

1. **Existence** — each reference resolves to a stored record
   (`Unknown provider connection: …`, `Unknown model configuration: …`,
   `Unknown runtime configuration: …`)
2. **Enabled state** — each referenced record is enabled
   (`Provider connection is disabled: …`, `Model configuration is disabled: …`,
   `Runtime configuration is disabled: …`)
3. **Cross-domain compatibility** — `ModelConfiguration.provider_connection_id`
   equals the default provider connection, so "connection A + a model hosted by
   connection B" is rejected
   (`Model configuration … does not belong to provider connection …`)

There is no fallback of any kind. Nothing is silently enabled, nothing is
silently substituted, and a rejected `set` leaves the previous defaults
untouched (verified by test). Rules are evaluated existence → enabled →
compatibility, so the most fundamental problem is reported first.

## 5. Relational schema and migration

Migration `v0007_application_execution_defaults` creates:

```text
application_execution_defaults(
    id                               INTEGER PRIMARY KEY CHECK (id = 1),
    default_provider_connection_id   TEXT NOT NULL,
    default_model_id                 TEXT NOT NULL,
    default_runtime_configuration_id TEXT NOT NULL
)
```

`id` is constrained to 1, so the database itself permits at most one defaults
row; a second insert raises `sqlite3.IntegrityError` (tested). No
`AUTOINCREMENT` key is used because a single record has no insertion order to
preserve. Verification fails closed on a missing table, mismatched columns, an
unexpected table, or a missing `CHECK (id = 1)` constraint — the last is
detected by inspecting the stored DDL, since an `INTEGER PRIMARY KEY` rowid
alias creates no index for a unique-index check to find.

The table stores **only** the three configured identities. `provider_id`,
`provider_model_name`, `runtime_type`, `display_name`, and `enabled` are
asserted absent from the DDL: those stay owned by their source records, so the
defaults row can never disagree with them.

Following AVA's existing no-declarative-FK convention, the migration declares
no foreign keys. Cross-record existence and compatibility are validated
explicitly in the repository, exactly as Phase 5.5 did for
`ModelConfiguration.provider_connection_id`.

`set` performs an `UPDATE` of the singleton row, inserting only when no row
exists — both inside one transaction, so validation and write are atomic. A
rejected `set` leaves no partial state.

## 6. Persistence composition

- `PersistenceRepositories.execution_defaults_repository` —
  `RelationalExecutionDefaultsRepository` over the shared `SqliteDatabase`,
  constructed with the bundle's own provider-connection, model-configuration,
  and runtime-configuration repositories so it validates against the same
  instances that own the data
- `ApplicationPersistence.execution_defaults_repository` —
  `ExecutionDefaultsStore` in memory mode, the relational adapter in relational
  mode, both receiving the same three stores the configuration repositories use

`ApplicationPersistence` now carries twelve ports plus its optional `database`.
No service, `RunService`, `AgentPort`, `ExecutionSelector`, `RuntimeRegistry`,
`RuntimeResolver`, HTTP route, or frontend module consumes the new repository.

## 7. Durability and migration compatibility

- Defaults written through the relational bundle survive close/reopen with all
  three references intact; a *replaced* set also survives reopen; and a bundle
  where defaults were never set reads back `None` after reopen.
- A v0006 database upgrades by applying only version 7. Verified to preserve
  provider connections (including `provider_id`, `endpoint`, and
  `credential_reference`), model configurations (including
  `provider_connection_id` and `provider_model_name`), and runtime
  configurations (including `runtime_type` and `display_name`), with
  `application_execution_defaults` starting empty and no rows synthesized.
- A Phase 4 database reaches v0007 with conversation, message, run, run-event,
  and document rows unchanged.

## 8. ExecutionProfile is unchanged

`ExecutionProfile` remains exactly as it was: `id`, `name`, `description`,
`runtime_id`, `model_provider_id`, plus `ExecutionProfileDiscoveryResponse`'s
`contract_version` and `default_profile_id`. Tests assert its field list
verbatim, assert `ApplicationExecutionDefaults` does not inherit from it, and
assert no persisted-default field leaked into it or its discovery response.

The two concepts stay distinct:

```text
ExecutionProfile                 = bootstrap/discovery preset naming adapter keys
ApplicationExecutionDefaults     = persisted references to configured AVA records
```

`ExecutionProfile.runtime_id` is a `RuntimeRegistry` lookup key
(`native`/`openhands`); `default_runtime_configuration_id` names a configured
instance that is not required to equal its own `runtime_type` and is not a
registry key. They are not interchangeable, and nothing in 5.8 attempted to
reconcile them. `GET /execution-profiles` is unchanged.

## 9. Bootstrap behavior

Nothing about bootstrap changed. `Settings`, `create_configured_model_profiles`,
`create_model_orchestrator`, `create_runtime_registry`, and the
`ExecutionSelector` defaults all still derive from the environment exactly as
before, and `get_settings()` still returns the same bootstrap values. Persisted
defaults are data only: no execution path reads them. Making them authoritative
— and deciding the precedence between a persisted default and an environment
value — belongs to Phase 5.17.

## 10. Architecture guards

New focused guards assert the defaults record declares no `provider_id`,
`provider_model_name`, `runtime_type`, or `runtime_id`; owns no user, workspace,
conversation, routing, or fallback state; and that neither `RunService` nor
`ExecutionSelector` mentions `ApplicationExecutionDefaults` or
`ExecutionDefaultsRepository`. Both are checked by AST field/parameter
inspection rather than substring matching, so prose describing what the record
deliberately omits does not read as a declared field.

Two dependency guards needed a *narrow* allowance matching the pattern 5.3–5.7
already established: the port and its adapter import
`ava.configuration.execution_defaults`, so
`test_repository_ports_depend_only_on_contracts_and_each_other` and
`test_persistence_layer_imports_only_repositories_and_contracts` allow
`ava.configuration` for `execution_defaults_repository.py` only. No guard was
broadened. `application_execution_defaults` was added to the approved
created-table list, the migration-version list now includes v0007, and a new
guard asserts both defaults adapters implement the singular port.

## 11. Tests

`backend/tests/test_execution_defaults.py` — 47 tests over a
memory/relational parametrized fixture, so every behavioral rule is proven
identical in both implementations:

- domain construction, field order, blank rejection
- singular port shape; `get()` is `None` before `set`
- set/get round trip, replacement, single-record persistence under repeated
  sets, failed `set` leaving prior state intact
- each of the three missing-reference rejections
- each of the three disabled-record rejections
- the model/provider-connection mismatch rejection, and a valid compatible
  trio on connection B
- no silent fallback: a rejected `set` stores nothing
- restart durability, replacement durability, durable absence
- v0006→v0007 upgrade preserving provider/model/runtime configuration, and a
  Phase 4→v0007 upgrade
- minimal column list, second-row rejection at the database level, and absence
  of duplicated adapter/type metadata in the DDL
- architecture boundaries: declared-field identity rule, no user/workspace/
  routing state, `RunService`/`ExecutionSelector` independence, `ExecutionProfile`
  unchanged, no persisted default in execution discovery

## 12. Validation

```text
pytest tests/test_execution_defaults.py tests/test_provider_connection_repository.py \
       tests/test_model_configuration_repository.py \
       tests/test_runtime_configuration_repository.py \
       tests/test_persistence_migrations.py tests/test_persistence_activation.py \
       tests/test_persistence_database.py tests/test_persistence_durability.py \
       tests/test_repository_behavior_compatibility.py \
       tests/test_restart_recovery_integration.py tests/test_architecture.py -q
267 passed

ruff check src tests
Success

mypy src
Success: no issues found in 163 source files

git diff --check
Clean
```

Full backend suite: **1427 passed, 2 skipped, 0 failed** (clean-tree baseline
with the same environment: 1318 passed, 0 failed).

The suite's known `.env` sensitivity is unchanged. With the repository-root
`.env` left as-is, a full-suite run shows 17 failures instead of the previous
11; those tests assert in-memory default composition while that `.env` selects
relational persistence, which pollutes the cached `Settings` singleton for the
rest of the process. Adding tests shifts which tests land after the polluting
test, which is why the count moved. Neutralizing it
(`AVA_PERSISTENCE=memory AVA_ATTACHMENT_STORAGE=memory`) yields zero failures
both before and after this change, and `test_attachments.py` and
`test_conversation_message_activation.py` pass in isolation. No regression.

## 13. Implications for Phase 5.9 and 5.16

**Phase 5.9 (credential references).** Nothing changes, and 5.8 adds no secret
surface. `ApplicationExecutionDefaults` stores no credential, and the defaults
table's DDL is asserted free of credential material. A credential reference
stays on `ProviderConnection.credential_reference`, which the defaults row
reaches only indirectly through its `default_provider_connection_id`. One thing
worth noting for 5.9: because the defaults row joins three domains by id, it
must never be a place to denormalize or cache a resolved endpoint or
credential — that would create a second authority that credential rotation
could silently desynchronize.

**Phase 5.16 (execution configuration resolver).** Two facts 5.8 fixes that
5.16 depends on:

1. A resolver can now treat `ApplicationExecutionDefaults` as the authoritative
   *fallback* layer while per-run overrides win. Because `set` rejects
   disabled or missing records, a resolver that reads a stored default does not
   need to re-validate enablement at resolution time — though it still must
   handle the case where a record was disabled *after* the default was set.
2. The resolver must join by configured identity, never by adapter key. When it
   resolves a default, it gets a `runtime_configuration_id` (not a
   `RuntimeRegistry` key) and must resolve the registry adapter through
   `RuntimeConfiguration.runtime_type` — the same join 5.6 and 5.7 established
   as the relationship between configured instance and adapter.

The precedence question Phase 5.8 deliberately leaves open — persisted default
versus environment/bootstrap value, and what happens when both exist — is
Phase 5.17's to settle, not 5.16's.
