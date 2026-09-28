# AVA Phase 5.10 — Settings API

Phase 5.10 exposes AVA's four persisted configuration domains over HTTP so the
Settings UI (Phase 5.11) has a stable contract to build against. It adds a
route module, a service, wire contracts, and thin typed client wrappers. It
changes no execution behavior, no persisted schema, and no discovery route.

## 1. Route structure

```text
GET    /settings/providers
POST   /settings/providers
GET    /settings/providers/{provider_connection_id}
PUT    /settings/providers/{provider_connection_id}

GET    /settings/models
POST   /settings/models
GET    /settings/models/{model_id}
PUT    /settings/models/{model_id}

GET    /settings/runtimes
POST   /settings/runtimes
PUT    /settings/runtimes/{runtime_configuration_id}
GET    /settings/runtimes/{runtime_configuration_id}

GET    /settings/defaults
PUT    /settings/defaults
```

One router, `ava/api/routes/settings.py`, tagged `settings`, following the
project's existing one-module-per-area convention (`documents.py`,
`attachments.py`, `runtimes.py`). `PUT` is used rather than `PATCH` because
each update is a full replacement of the mutable fields: a `PUT` body carries
every mutable field with none optional, so clearing a nullable field means an
explicit `null` rather than an omitted key, and there is no partial-update
semantics to reason about. There is no `DELETE` for any resource — the
repositories do not support deletion, and inventing a soft-delete or
"disable-on-delete" rule would add lifecycle semantics no requirement states.
Disabling is an explicit `enabled` update.

### The boundary that matters

```text
/settings/*         persisted configuration — what an operator has configured
/model-providers    discovery — what providers are available and healthy
/models             discovery — what models are registered
/runtimes           discovery — which runtime implementations are registered
/capabilities       discovery — application capability names
/execution-profiles discovery — bootstrap presets naming adapter keys
```

These are never merged. Discovery still answers from the live registries;
`/settings/*` only ever reaches the configuration repositories through
`SettingsService`. A test asserts both directions: configured records never
appear in discovery output, and configuring a runtime whose adapter is not
installed does not make it appear in `/runtimes`. An architecture test asserts
no non-Settings route module serves the `/settings` prefix and that the Settings
router declares none of the discovery paths.

## 2. Contracts

`ava/contracts/settings.py` — plain Pydantic models, no `ava.models`,
`ava.infrastructure`, repository, runtime, or vendor type. Response contracts
carry `contract_version`, matching the rest of the API.

Response field sets are exactly the domain field sets, with no additions:

| Resource | Fields |
| --- | --- |
| `ProviderConnectionResponse` | `provider_connection_id`, `provider_id`, `display_name`, `endpoint`, `enabled`, `credential_reference` |
| `ModelConfigurationResponse` | `model_id`, `provider_connection_id`, `provider_model_name`, `display_name`, `hosting_mode`, `capabilities`, `enabled` |
| `RuntimeConfigurationResponse` | `runtime_configuration_id`, `runtime_type`, `display_name`, `enabled` |
| `ApplicationExecutionDefaultsResponse` | `default_provider_connection_id`, `default_model_id`, `default_runtime_configuration_id` |

Deliberately absent from model configuration: provider `endpoint` (it belongs
to the connection — duplicating it would create a second authority),
`context_limit` (provider-reported *discovery* metadata, not configuration;
Phase 5.4 excluded it for this reason), qualifications (measured evidence, not
configuration), and runtime binding (execution's concern). Absent from runtime
configuration: `model_id`, `provider_id`, `provider_connection_id`, registry
objects, `AgentRuntimePort`, workspace config, tool permissions, and
credentials. A test posts each of those as a runtime field and asserts `422`
and that nothing was created.

Every **request** contract sets `extra="forbid"`. This is a correctness
requirement, not a style choice: silently dropping an unknown field is how a
caller would come to believe a secret field, a runtime adapter key, or an
execution field had been stored.

## 3. Identity and update semantics

Identity is server-owned and always travels in the path. No request body
contains a path identity field.

Each domain additionally has one field that is *immutable after creation*, and
the update contract carries it as an **optional echo** rather than an editable
value:

| Resource | Immutable field | Omitted | Resent with current value | Different value |
| --- | --- | --- | --- | --- |
| Provider connection | `provider_id` | preserved | `200` | `409` |
| Model configuration | `provider_connection_id` | preserved | `200` | `409` |
| Runtime configuration | `runtime_type` | preserved | `200` | `409` |

This was a real design choice. Omitting the field entirely would make the
reassignment impossible, but a client that *does* send it would then have it
silently dropped — which is its own ambiguity, and exactly the "silently
re-pointed" outcome the phase prohibits. Echo semantics give three legible
outcomes instead of two, and a client that round-trips a full record is not
punished for doing so. `_require_unchanged` in the service states the rule once
for all three domains.

## 4. Credential-reference handling

`credential_reference` is validated for **syntax only**, using Phase 5.9's
`CredentialReference.parse`, and persisted in canonical form.

```text
POST /settings/providers {"credential_reference": "env:OPENAI_API_KEY"}  → 201
POST /settings/providers {"credential_reference": "OPENAI_API_KEY"}      → 422
POST /settings/providers {"credential_reference": "env:"}                → 422
```

`None` remains valid — a local unauthenticated provider has no reference, and
`endpoint` and `credential_reference` are both independently nullable.

**A save never resolves the secret.** This is the load-bearing decision of the
phase: whether the named secret currently resolves is a property of a transient
secret backend, not of the configuration. A test creates a connection
referencing a variable that definitively does not exist and asserts `201` and
readability. If saving depended on resolution, every backend outage would
either block configuration or silently discard it.

Consequently there is **no credential-resolution test endpoint** in 5.10. The
phase made it optional pending justification, and the justification did not
hold up: a `POST /settings/providers/{id}/test-credential` returning
`{"success": true}` would report only "a string exists in an environment
variable", which is not what an operator asking "does my key work?" means. The
honest version of that question needs a live authenticated request against the
provider — a model call, provider SDK behavior, and latency — which is a
connection-testing feature, not a settings endpoint. If a Settings UI needs a
signal, the cheap honest one is a boolean derived from catching
`CredentialNotFoundError`/`BlankCredentialError` and discarding the message;
that belongs with the UI work in 5.11, not here.

## 5. Error mapping

All errors use the existing `ErrorResponse` envelope with AVA's `ErrorCategory`
values, matching `/documents` and `/attachments`:

| Condition | Status | `error_code` | Category |
| --- | --- | --- | --- |
| Unknown record on GET/PUT | `404` | `*_not_found` | `NOT_FOUND` |
| Duplicate identity on POST | `409` | `*_already_exists` | `VALIDATION` |
| Immutable field change | `409` | `*_field_immutable` | `VALIDATION` |
| Domain validation, unknown reference, malformed credential reference, defaults incompatibility | `422` | `invalid_*` | `VALIDATION` |
| Request contract violation | `422` | FastAPI `detail` | — |

The service raises four typed errors (`DuplicateSettingsRecordError`,
`UnknownSettingsRecordError`, `ImmutableSettingsFieldError`,
`InvalidSettingsError`) rather than letting the route classify raw
`ValueError`s by message text. Where the HTTP status depends on *why* a write
failed — duplicate versus immutable versus invalid — the service resolves the
cause with an explicit lookup before the write, and the repository stays the
authority for the write itself. A race between the two surfaces as the
repository's own `ValueError`, translated to `422`.

### A credential-echo path found and closed

FastAPI's default `422` body echoes the rejected value as `detail[].input`. On
the Settings surface that is a real leak path: a user who mistakenly pastes a
secret into a rejected field has it reflected verbatim in the response.

`handle_settings_validation_error` in `ava/api/app.py` strips the echoed `input`
for `/settings` paths only, keeping field locations and messages, and delegates
to FastAPI's default handler for every other path. Verified both ways: a
`POST /documents` with a mistyped field still returns the standard body
including `input`, and the Settings response contains no trace of the value.
No existing endpoint's contract moved.

## 6. Disabled records

List endpoints return the **full inventory**, including disabled records, and
`enabled` is a writable field. Settings management is inventory work; filtering
disabled rows would make a user unable to see — let alone re-enable —
something they had configured.

Execution selection rules for disabled records are a separate concern and remain
unimplemented, exactly as in 5.8: `ApplicationExecutionDefaults` refuses to
*reference* a disabled record, but nothing yet refuses to *execute* a disabled
one. Tests assert disabled records appear in every list and that a disabled
record is rejected as a default.

## 7. Defaults endpoint

`GET /settings/defaults` returns `ApplicationExecutionDefaultsState`:

```json
{"configured": false, "defaults": null, "contract_version": "v1"}
```

"Not configured yet" is reported as `200` with an explicit flag rather than
`404`. An unconfigured application is normal state, not a missing resource, and
`404` would force every client to treat a routine first-run condition as an
error. There is no list form and no way to create a second defaults record.

`PUT /settings/defaults` replaces the single record and enforces every Phase 5.8
rule — all three references exist, all three are enabled, and
`ModelConfiguration.provider_connection_id` equals
`default_provider_connection_id`. Those checks are the repository's, so
in-memory and relational semantics cannot drift. Adapter keys
(`provider_id`, `provider_model_name`, `runtime_type`) are not accepted fields;
posting one is a `422`. A rejected write leaves the previous defaults intact.

## 8. Discovery compatibility and execution confirmation

Existing routes were not modified. `/runtimes`, `/models`, `/model-providers`,
`/capabilities`, and `/execution-profiles` keep their implementations, their
response shapes, and their meanings; tests assert each still responds as before
after settings records exist.

Execution is untouched. `RunService`, `AgentPort`, `ExecutionSelector`,
`ModelOrchestrator`, `RuntimeResolver`, provider execution, model binding
selection, and the run request contracts were not modified. `ExecutionProfile`
is unchanged — a test asserts the preset set and `default_profile_id` are
identical after writing persisted defaults, since persisted defaults are not yet
authoritative for execution. `app.py` composes `SettingsService` alongside
`RunService`; nothing passes settings into the run path.

## 9. Service design

One `SettingsService` covers all four domains, unlike the one-service-per-domain
shape of `DocumentService`. The deciding factor is that the domains validate
against each other: a model must name an existing connection, and defaults must
name three existing enabled records that agree. Keeping those rules in one place
is the reason for the choice; the service is otherwise a thin translator from
domain records to wire contracts.

The service deliberately does **not** resolve credentials. An architecture test
asserts `settings_service.py` never references `CredentialResolver`,
`SecretValue`, `resolve_connection_credential`, or `reveal(` while still
referencing `CredentialReference` for syntax validation — a service on a request
path that returns HTTP contracts must never hold secret material.

## 10. Tests

`backend/tests/test_settings_api.py` — 72 tests, in the order the phase requires:

- **Providers** — empty list, create/get/update, duplicate `409`, unknown `404`,
  enabled/disabled list inclusion and toggling, nullable endpoint and credential
  reference, explicit `null` clearing, three valid reference forms, five
  malformed forms, immutable `provider_id` conflict, current-value echo
  accepted, a save that references a nonexistent secret, and blank-field `422`.
- **Models** — empty list, create/get/update, duplicate, unknown, unknown
  provider connection, immutable association, three hosting modes round-tripping,
  full and default capabilities round-tripping, capability replacement, disabled
  listing, and identity-collision rejection.
- **Runtimes** — empty list, create/get/update, duplicate, unknown, runtime type
  immutability (the `native` → `openhands` case), an uninstalled adapter type
  being accepted, disabled listing, and four smuggled execution fields each
  rejected with nothing created.
- **Defaults** — unconfigured state, set/get, replacement, three missing-record
  rejections, three disabled-record rejections, model/connection mismatch, a
  rejected write preserving the previous value, adapter keys rejected, and
  missing fields rejected.
- **Credential safety** — no secret in any response with a *resolvable*
  reference configured, no secret-bearing field on any contract, contract
  exposes `credential_reference` only, the generated OpenAPI schema contains no
  secret property, and a posted `api_key` is rejected without echo.
- **Compatibility** — discovery keeps its own meaning, configuring does not
  invent availability, `/capabilities` unchanged, and persisted defaults do not
  change execution profiles.

`backend/tests/test_architecture.py` — six narrow additions: Settings routes
import only contracts and services; neither routes nor service import a runtime
or provider implementation; no Settings contract carries a secret field
(checked by AST, so docstrings naming what is absent do not trip it); the
defaults contract has no adapter-identity field; the service never resolves
credentials; and the Settings prefix does not overlap discovery.

One pre-existing 5.9 test was tightened: its substring scan of
`ava/contracts/` for `SecretValue` now became an AST check, because a contract
docstring that says "no field may hold a `SecretValue`" is prose about an
omission, not code referencing the thing omitted.

### Test isolation

The Settings tests build their app with
`create_app(settings=Settings(persistence_provider="memory"))` rather than
inheriting ambient configuration. This is deliberate and it matters: the first
version of these tests inherited the repository-root `.env`, and under
`AVA_PERSISTENCE=relational` all 44 state-dependent tests failed because one
on-disk database was shared across the whole process and configured records
leaked between tests. With the override, the Settings tests pass under every
persistence mode, including the ambient `.env` that still breaks 11–17 unrelated
baseline tests.

## 11. API client

`@ava/contracts` gained `settings.ts` (TypeScript interfaces mirroring the wire
contracts) and `@ava/api-client` gained `settings.ts` (thin `fetch` wrappers)
plus `settings.test.ts` (7 tests). Both are exported from their `index.ts`.

These were added because this project does treat API-client parity as part of
endpoint delivery: `@ava/api-client` has exactly one module per backend route
module, and the contracts package mirrors them one-for-one. The wrappers are
transport only — no components, no state, no caching, no UI. The Python client
at `clients/python` was **not** extended: it covers five of roughly thirty
endpoints (health, capabilities, model-providers, models, workspaces) and has
never mirrored the full surface, so it is not a parity surface and adding
Settings methods there would be inconsistent rather than complete.

Both packages pass `tsc --noEmit` and the full `vitest` suite (73 tests).

## 12. Validation

```text
pytest tests/test_settings_api.py                    72 passed
pytest tests/test_architecture.py                    94 passed
pytest tests/test_credentials.py                      56 passed
pytest <18 files: settings, architecture, credentials,
        documents, conversations, attachments, runs,
        model/runtime discovery, capabilities, settings,
        runtime registry/resolver, execution defaults>  460 passed

ruff check src tests          All checks passed!
mypy src                      Success: no issues found in 168 source files
git diff --check              Clean
tsc --noEmit (contracts)      clean
tsc --noEmit (api-client)     clean
vitest run (api-client)       10 files, 73 tests passed
```

Full backend suite:

| Environment | Result |
| --- | --- |
| `.env` neutralized (`AVA_PERSISTENCE=memory AVA_ATTACHMENT_STORAGE=memory`) | **1563 passed, 2 skipped, 0 failed** |
| Ordinary repository `.env` | 17 failed, 1546 passed — **0 in any Settings or architecture test** |

The 17 are the documented baseline contamination: tests that assert in-memory
default composition while the repository-root `.env` selects relational
persistence, polluting the cached `Settings` singleton for the rest of the
process. The count oscillates between 11 and 17 across runs purely from test
ordering. The neutralized run — the project's true result — is clean at 1563,
up from 1485 after Phase 5.9.

## 13. Implications for 5.11–5.15 and 5.16

**5.11–5.15 (Settings UI).** The UI can be built against these contracts with no
backend change. Three things to know:

- The defaults screen should branch on `configured`, not on a 404.
- Every list includes disabled records, so the UI owns the filter/enable
  affordance rather than the API filtering for it.
- Never put a secret in a request field. The backend will reject it, and it
  will not be echoed — but the right client behavior is to send only
  `credential_reference`. A "test credential" affordance, if wanted, is the
  boolean described in §4 and is a UI-side concern.
- The `provider_id` / `provider_connection_id` / `runtime_type` echo fields
  should be sent back verbatim when the UI round-trips a record. Omitting them
  also works, but sending them makes the conflict explicit if a record was
  retyped elsewhere.

**5.16 (execution configuration resolver).** Nothing in this phase moved the
execution needle, and that is the correct outcome. Three facts 5.16 can rely on:

1. Persisted records are readable and complete, so a resolver can join
   `ApplicationExecutionDefaults` → connection → model → runtime by configured
   identity without touching the API layer.
2. Settings state is not authoritative for execution, so 5.16 can introduce
   that wiring without changing any Settings contract. If 5.16 finds it needs a
   new configuration field, that is a new phase, not a Settings API change.
3. The Settings API never resolves credentials, so the resolver's credential
   boundary is unaffected by anything here.
