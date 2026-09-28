# AVA Phase 5.17 — Configuration Bootstrap / Migration Compatibility

## Audit before editing

`Settings` reads `AVA_AGENT_PROVIDER` (default `mock`), `AVA_AGENT_RUNTIME`
(`native`), `AVA_MODEL_PROVIDER` (`local`), `AVA_MODEL_NAME` (`local-model`),
`AVA_MODEL_ID` (otherwise `<provider>-<model name>`), `AVA_MODEL_HOSTING_MODE`
(`local`), and `AVA_LOCAL_MODEL_BASE_URL` (`http://localhost:11434/v1`). There
is no legacy credential setting. Memory persistence is the default; relational
persistence is selected independently.

Composition registers native/OpenHands runtime implementations. The bootstrap
provider registry constructs a local OpenAI-compatible instance only when the
selected provider is `local`. A separate configured-provider factory originally
constructed the same adapter for persisted connections. The startup model
registry holds one environment-derived profile; persisted profiles are per-run
snapshots, not registrations in that registry.

`ExecutionProfileService` publishes `local-default` and `openhands-local`,
containing runtime/provider registry ids. Runtime/provider discovery exposes
bootstrap default ids. `AppWorkspace` originally copied those ids and the
default profile id into selector state after discovery, then always sent those
values in `RunRequest.execution`. Merely opening the application therefore
acted as an explicit override. Web and Desktop both render this shared
workspace; their only shell setting is the backend API URL.

The 5.16 selector validates persisted defaults before choosing either a
persisted default execution or an explicit legacy override. Invalid saved
configuration never becomes bootstrap fallback. Repository writes own their
SQLite transactions; four independent calls need an enclosing atomic boundary
before automatic startup materialization can be safe.

## Scope

Only 5.17. No Settings redesign, new public execution contract, schema change,
or Phase 5.18 audit. Completion policy and validation are recorded below.

## Final compatibility policy

Automatic seeding is implemented for **native execution with relational
persistence**, after migrations and before the application serves requests.
Memory-mode and mock-agent development retain their previous compatibility
behavior and do not acquire synthetic Settings records.

| Startup state | Result |
| --- | --- |
| Empty durable configuration, structurally valid native bootstrap | Atomically seed all four records |
| Persisted defaults already exist, valid or invalid | Preserve everything; resolve and validate at execution time |
| Any configured provider/model/runtime exists, defaults absent | Skip seeding, preserve all records, retain bootstrap fallback |
| Empty configuration, unusable native bootstrap | Leave Settings unconfigured and log an instruction to configure execution defaults |
| Memory persistence or mock agent | Retain legacy development behavior |

“Empty” refers to the four execution-configuration stores, not conversation or
run tables. An upgraded Phase 4 database with conversation history but no
configuration is eligible. Existing records do not need to match bootstrap
identities to prevent seeding.

A missing defaults row alone never means the configuration is empty. No subset
is completed, inferred or merged. Matching and conflicting deterministic-id
collisions both produce `existing_records` and an operator diagnostic; neither
is overwritten. An operator completes the configuration through ordinary
Settings and chooses defaults explicitly.

## Stable identities and eligibility

| Record | Identity / source |
| --- | --- |
| Provider connection | `bootstrap-provider-<Settings.model_provider>`; currently `bootstrap-provider-local` |
| Provider adapter | Existing `local` OpenAI-compatible adapter identity |
| Model | Exact `Settings.resolved_model_id`: explicit `AVA_MODEL_ID`, otherwise `<provider>-<provider model name>` |
| Runtime configuration | `bootstrap-runtime-<Settings.agent_runtime>`, e.g. `bootstrap-runtime-native` |
| Runtime adapter | Existing runtime registry key from `Settings.agent_runtime` |
| Defaults | Existing singleton referencing the three records above |

Display labels are `Bootstrap <provider>`, the provider model name, and
`Bootstrap <runtime>`. Labels never generate identity. No UUID, source column,
ownership flag, timestamp or schema migration is added.

Before writing, the coordinator checks installed provider constructor support,
registered runtime type, and the existing provider adapter's structural endpoint
validation. Existing domain constructors validate model ids, their separation
from connection/provider-native identities, hosting mode and nonblank fields.
Defaults use their existing repository validation. All objects are constructed
before the first write. Validation is structural; startup performs no provider
health check, inference, model preload or secret resolution.

An invalid blank bootstrap model now produces an empty bootstrap catalog with
an explicitly opt-in unconfigured binding resolver, so Settings remains
reachable. Other binding-resolver callers retain their previous strict
construction behavior. Invalid values rejected by `Settings` itself (such as an
unrecognized hosting-mode environment value) retain the existing strict startup
validation; 5.17 does not reinterpret malformed operational settings.

## Idempotency, edits and environment changes

Once the defaults row exists, startup performs no seed writes. Every seeded
record is an ordinary editable Settings record. Changes to display names,
endpoint, enabled state, credential reference, provider-native model name,
hosting mode, runtime label or defaults survive restart unchanged.

Changing `.env` after seeding updates the separate legacy bootstrap catalog,
not the persisted records. Requests without overrides still use persisted
settings. Explicit legacy selections may intentionally use the changed
bootstrap catalog. A missing or disabled saved reference remains an execution
error; startup never repairs it by reseeding or choosing an environment value.

Seeded connections persist the actual bootstrap endpoint. A separately edited
connection whose endpoint is explicitly cleared to `None` retains 5.16's
existing adapter-default endpoint behavior; 5.17 does not invent a replacement
endpoint policy.

## Atomicity and failure behavior

Composition passes the coordinator only the configuration repository bundle,
Settings, runtime registry, and an optional transaction context factory. The
coordinator never imports concrete persistence adapters or SQLite. Memory mode
has no durable transaction capability and is intentionally not seeded.

For SQLite, the existence checks and four writes run inside `BEGIN IMMEDIATE`.
`SqliteDatabase.transaction()` now supports nested repository operations through
uniquely named savepoints. Repository success releases its savepoint, not the
outer transaction. If any write fails, the outer transaction rolls back all
four records and startup raises `ConfigurationBootstrapError`; it does not
continue after a partial failure. A restart can retry the empty store safely.

Tests inject failure at each of the four writes, reopen the database, and prove
that nothing survived and the next startup can seed. Additional tests prove an
outer rollback reverses successful repository writes, and a caught inner
failure rolls back only its savepoint. The emptiness check is inside the write
transaction, so independently starting SQLite connections cannot both observe
empty configuration and commit duplicate seeds.

## Provider, runtime and model compatibility

`construct_compatible_provider` is the one infrastructure construction function
used by both bootstrap and persisted provider paths. Credentials are revealed
only there. The per-execution factory retains its shared HTTP-pool lifecycle;
bootstrap instances retain their original provider-owned pool lifecycle.

Built-in constructor support (`local`) is now independent of the environment's
selected default provider. A saved local connection still executes when the
legacy default changes to an unsupported provider. Compatible registry aliases
can be supported; unrelated registered protocols are not silently constructed
as OpenAI-compatible providers.

Runtime registration is unchanged: native/OpenHands remain executable adapter
instances. Seeding stores only configured-instance metadata and runtime type.

The bootstrap `ModelRegistry` and persisted per-run profile snapshots remain
separate. Persisted records are not appended to the bootstrap registry, so
there is no duplicate registration or last-write shadowing. The same stable id
may be present in the two explicitly selected sources; default requests use
the persisted snapshot and intentional legacy overrides use the bootstrap
catalog. Existing orchestration and resource leases remain unchanged.

## Credentials

Legacy Settings has no credential environment field. Consequently bootstrap
connections have `credential_reference=None`, even if unrelated key variables
exist in the process. No key variable name is invented and no environment secret
is copied into persistence. Operators can subsequently set an `env:NAME`
reference using ordinary Settings. Existing per-execution resolution, redaction
and secret-boundary tests continue to apply.

## Explicit overrides and frontend behavior

`ExecutionProfile` remains an explicit legacy/bootstrap preset, with its
existing `local-default` and `openhands-local` identities and unchanged schema.
It is not the durable defaults record.

The shared composer starts at **Application default**. Discovery only populates
available choices; it no longer writes runtime, provider or profile selections
into user state. Therefore normal submissions omit `RunRequest.execution`,
allowing the backend to use saved defaults (or absence-only bootstrap fallback).

Selecting a runtime, model/provider, profile or Auto is an explicit override.
The existing request contract and backend interpretation are preserved. Partial
legacy overrides still resolve their unspecified fields from bootstrap; they
are not combined with configured-instance ids. Choosing Application default
clears runtime/provider overrides without changing workspace selection. Late
discovery cannot reset user intent because it does not write selection state.

Web and Desktop continue to consume the same shared workspace and controls;
neither shell nor the Settings feature was changed. The UI reads no execution
environment variables. No Settings screen, run contract or profile schema was
redesigned.

The 5.16 rule remains: existing saved defaults are validated even before an
explicit legacy override. Invalid saved configuration fails rather than being
hidden by an unrelated execution selection.

## First-run diagnostics

A valid native relational installation gets editable Settings records and a
saved defaults row before its first request. A memory/mock development install
retains its existing behavior. An unusable native bootstrap produces no guessed
record; startup logs an instruction to configure Providers, Models, Runtimes
and Defaults, and Settings remains accessible where Settings parsing succeeds.
Run failure continues through the existing sanitized failed-run/event contract;
this phase does not add a new run-error UI or expose infrastructure diagnostics.

## Files changed in Phase 5.17

```text
backend/src/ava/infrastructure/configuration_bootstrap.py                 new coordinator
backend/src/ava/infrastructure/composition.py                             startup wiring / shared construction
backend/src/ava/infrastructure/model_provider_factory.py                  shared constructor / installed support
backend/src/ava/infrastructure/persistence/database.py                    nested savepoints
backend/src/ava/api/app.py                                                 startup call / unconfigured catalog support
backend/src/ava/models/bindings.py                                         opt-in empty bootstrap catalog
backend/tests/test_configuration_bootstrap.py                             new bootstrap / request / transaction tests
backend/tests/test_architecture.py                                        two additional guards
frontend/packages/agent-ui/src/components/ExecutionControls.tsx          Application default option
frontend/packages/workspace/src/AppWorkspace.tsx                         explicit selection state
frontend/packages/workspace/src/execution-default-request.test.tsx       real client request-body tests
docs/AVA_Phase_5_17_Configuration_Bootstrap_Migration_Compatibility.md      this report
```

Earlier uncommitted Phase 5 work remains in the workspace. No Settings domain,
Settings API/UI, public execution contract, runtime registry, RunService,
AgentPort, migration version, or main Phase 5 plan was changed in this step.

## Tests and validation

The new backend file has 25 parametrized cases covering deterministic seeding,
idempotence, derived identity, partial/collision policy, rollback at every write,
invalid bootstrap values, mock/memory compatibility, user edits, environment
changes, API edits and restart, default/explicit request authority, invalid saved
references, Settings reachability, and nested transaction behavior.

Six frontend tests use the real `AppWorkspace`, state providers, and
`@ava/api-client`, replacing only fetch. They inspect the actual serialized
`POST /runs` body for untouched defaults, runtime/model/profile/Auto overrides,
and switching back to Application default. Backend HTTP tests then prove
omitted overrides execute persisted settings while explicit requests retain
legacy selection. No external model server is needed.

Final validation:

| Check | Result |
| --- | --- |
| Bootstrap / resolver / persisted HTTP integration / SQLite / architecture | **208 passed** |
| Full backend | **1661 passed, 2 skipped**, four existing OpenHands SDK deprecation warnings |
| New frontend serialized-request tests | **6 passed** |
| All frontend packages | **633 passed, 4 skipped** (opt-in live-backend tests) |
| TypeScript (`pnpm lint`) | All 10 packages/apps passed |
| Web production build | Passed |
| Desktop production build | Passed |
| Ruff, backend source and tests | Passed |
| mypy | Passed, 173 source files |
| `git diff --check` | Clean |

Web and Desktop emitted identical `index-Duw0SgmH.js` and
`index-DuWeGZp6.css` assets. The existing Vite large-chunk warning remains.
Backend runs used `AVA_PERSISTENCE=memory AVA_ATTACHMENT_STORAGE=memory`
to neutralize the documented ambient `.env` sensitivity; relational tests
explicitly used isolated temporary databases. HTTP integration runs used the
approved outside-sandbox environment because Starlette TestClient cannot start
its local thread reliably in this execution sandbox.

## Phase 5.18 handoff — not started

Normal Web/Desktop submissions now exercise persisted execution defaults.
Conversation/run architecture work should preserve the distinction between
omitted overrides and intentional legacy selections; do not seed configuration
from a run or infer configured-instance ids from registry keys.

Configuration seeding is a startup infrastructure concern. It requires no
conversation migration, schema change or future conversation audit. Partial
configuration remains an operator decision. Discovery still describes the
legacy executable catalogs; exposing a persisted model picker would be a
separate product decision, not a prerequisite for using saved defaults.


**Phase 5.17 complete. Phase 5.18 has not been started.**
