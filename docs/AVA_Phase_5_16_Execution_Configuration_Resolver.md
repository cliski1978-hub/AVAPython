# AVA Phase 5.16 — Execution Configuration Resolver

## Execution audit (before completing the existing partial implementation)

`POST /runs` passes `RunRequest` to `RunService.start_run`, which persists the
run and calls only `AgentPort.start_run`. Production native execution uses
`NativeAgentAdapter`; the mock agent remains a separate development choice.

`ExecutionProfileService` publishes bootstrap presets containing `runtime_id`
and `model_provider_id`. The frontend expands a preset into
`RunExecutionOverride`; no profile id reaches the backend run path. The frontend
also seeds these selectors from discovery, so current UI submissions normally
contain explicit legacy choices. This phase does not change that UI contract.

`NativeAgentAdapter` calls `ExecutionSelector.resolve` once. In the bootstrap
path the selector chooses the runtime registry key from the override or
environment default. Automatic routing first chooses runtime/provider keys;
`ModelOrchestrator` then selects a model from the startup `ModelRegistry`.
Ordinary selection also uses that orchestrator, or `ModelBindingResolver` in
legacy compositions without one. `model_binding_from_profile` derives
`ConfiguredModelBinding`. `ModelProviderResolver` looks up the already-built
provider by `ModelProfile.provider_id`, and `RuntimeResolver` looks up the
runtime by registry key. These are not configured-instance ids.

Composition builds the bootstrap OpenAI-compatible provider under `local`,
using `Settings.local_model_base_url`, `model_name`, and `api_key=None`.
`RuntimeModelBinding.api_key` is the existing internal carrier into OpenHands;
native execution uses the same provider's HTTP authorization header. OpenHands
uses its existing placeholder for credential-free local providers.

After selection, the native agent applies compatibility/hosting validation,
resolves the approved workspace, acquires a model resource lease, calls
`AgentRuntimePort.execute` with the provider and binding, and releases the
lease. Native runtime invokes `ModelProviderPort.generate`; OpenHands consumes
the provider's internal runtime binding. `RunService` never performs any of
these resolutions.

The pre-existing partial 5.16 work already added repository resolution,
provider construction and composition wiring. It did not yet preserve model
orchestration on the persisted path, accepted arbitrary unknown resource ids
through a default descriptor, and had no 5.16 tests or completed documentation.
The implementation below completes that work without replacing the execution
architecture.

**Status:** Complete. Scope is Phase 5.16 only.

## Resolver boundary and result

`ExecutionConfigurationResolver` takes a `ConfigurationRepositories` bundle
containing the four existing repository ports, the existing `RuntimeResolver`,
`ModelOrchestrator`, a `ModelProviderFactory`, a `CredentialResolver`, and the
optional server-owned hosting requirement. Composition supplies these; callers
call `resolve_persisted()` without assembling ids.

- Absent defaults return `None`. `resolve_required()` offers an explicit error
  for callers requiring persisted configuration.
- Present defaults are re-read on every resolution. The referenced connection,
  model and configured runtime must exist and be enabled; the model must belong
  to the selected connection. Repository failures propagate as failures, never
  as absence.
- The result is `PersistedExecutionConfiguration`: the existing runtime port,
  provider port, `ModelProfile`, derived `ConfiguredModelBinding`, configured
  runtime id, runtime type, and connection id. Model id is read from the binding
  rather than independently stored again.
- `ExecutionSelector` depends on a repository-free resolver protocol. It adapts
  that result into its existing `ResolvedExecution`, whose internal `source`
  explicitly identifies `persisted` or `bootstrap`. Bootstrap selections have
  no configured connection/runtime ids.

These results are internal objects, not JSON/wire contracts. Both exclude
runtime/provider objects from `repr`, regardless of those objects' own repr
implementations. No public run/event contract gains fields.

## Authority and legacy compatibility

| Saved defaults | Request | Behavior |
| --- | --- | --- |
| Absent | Default or explicit legacy override | Original bootstrap selection |
| Valid | Absent or empty override | Persisted runtime/model/connection |
| Valid | Explicit legacy ids or `mode=auto` | Original explicit bootstrap selection, after validating saved defaults |
| Invalid or unusable | Any request | Fail; never substitute bootstrap |

`ExecutionProfile` remains a discovery preset. Its fields and endpoints are
unchanged. Explicit override semantics already exist, so this step retains them
instead of guessing that a registry key names a configured instance. Partial
legacy overrides still fill their other fields from bootstrap; no field-level
mixing of persisted and bootstrap identities is introduced.

A legacy override with saved defaults therefore performs persisted validation
(including adapter/credential resolution and model policy) followed by legacy
selection. This deliberately refuses to mask invalid saved configuration.
Neither validation nor provider construction performs network I/O. Default
persisted requests perform one model policy selection and one runtime lookup.

**Current UI limitation:** Web/Desktop normally submit their discovered legacy
runtime/provider values explicitly, including when those controls were seeded
by a bootstrap profile. Those submissions remain explicit bootstrap choices.
Default API requests already execute persisted settings. Phase 5.17 must settle
how legacy clients express “use application defaults”; this phase does not infer
intent by comparing ids, change selectors, or remove environment bootstrap.

`AVA_AGENT_PROVIDER=mock` continues to select the mock agent. Persisted settings
configure the native execution machinery, not the choice of the outer AgentPort.

## Runtime, model and provider mapping

```text
RunService -> AgentPort / NativeAgentAdapter -> ExecutionSelector
                                                 |
                                      ExecutionConfigurationResolver
                                        /           |            \
                             configured runtime   model        connection
                                      |             |              |
                                runtime_type     ModelProfile   provider_id
                                      |             |              |
                               RuntimeResolver   ModelOrchestrator factory
                                      |             |              |
                               AgentRuntimePort  standard binding ModelProviderPort
                                        \           |            /
                                      existing ResolvedExecution
                                                 |
                                  compatibility + workspace policy
                                                 |
                                      model lease -> runtime.execute
```

`runtime_configuration_id` selects the persisted instance.
`RuntimeConfiguration.runtime_type` is then passed to `RuntimeResolver`; the
configured id is never treated as a runtime registry key. A missing adapter has
its own typed error, distinct from a missing configuration record.

The configured model supplies stable id, provider-native model name, display
name, hosting mode, capabilities and enabled state to `ModelProfile`.
`ProviderConnection.provider_id` supplies the profile's provider adapter id.
The existing `model_binding_from_profile` produces the binding.

The existing orchestrator now accepts an optional per-call `ModelRegistry`
snapshot. Persisted default resolution supplies the selected profile and asks
for its exact id, preserving the same hosting/eligibility/qualification policy
without mutating the shared bootstrap catalog. Exact selection is intentional:
rejecting this configured default must not choose a different model. No model
id is hard-coded, the legacy multi-model/automatic selection path is retained,
and future override/catalog integration can use the same snapshot seam. This
phase does not make every persisted model discoverable or introduce routing
among persisted models.

`ModelProviderFactory` is an AVA-owned construction port because the existing
provider registry holds already-configured instances, not constructors. A new
instance is required for each selected connection/credential. The concrete
`ConfiguredModelProviderFactory` remains in infrastructure and serves registered
OpenAI-compatible adapter instances. Production currently registers `local`.
An unrelated registered provider port is not reinterpreted as OpenAI-compatible;
it needs its own construction support.

The configured endpoint passes unchanged through the resolver/factory. `None`
uses the existing local deployment endpoint from `Settings`. The existing
OpenAI-compatible adapter still performs its own whitespace handling and URL
validation; no new URL rule is imposed on `ProviderConnection`. An opaque
endpoint can resolve yet be rejected by the adapter when execution needs a URL.

## Credentials and lifecycle

Credentials resolve once per execution resolution, never at application startup
or Settings save. A connection with no reference does not call the credential
resolver. A reference uses the existing `CredentialResolver`/`SecretValue` seam;
only the infrastructure factory calls `reveal()`, once, into the existing
provider constructor. OpenHands continues to receive credentials through the
existing internal `RuntimeModelBinding.api_key`, which now excludes that field
from repr. No second credential carrier was added.

Credential and construction failures have safe typed wrapper errors with
suppressed exception chaining. The resolver does not log endpoints or resolved
secrets. The native agent releases its per-run provider reference on completion
and retains only the terminal status needed to preserve cancellation behavior.
The provider factory shares one owned HTTP pool across per-run adapters and
closes it at application shutdown; an injected pool remains caller-owned.

Integration tests inspect actual HTTP authorization headers, rotate the
reference value between runs, inspect SQLite dumps and public run/events, and
assert secrets do not appear in captured logs. Tests also use an intentionally
unsafe provider repr and exception messages to verify the result/error boundary.

## Orchestration and resource leases

`RunService` and `AgentPort` are unchanged. Neither receives configuration
repositories, a provider factory, nor a credential resolver. Compatibility and
workspace checks remain after selection; configuration selection grants no new
tool/workspace authority.

`NativeAgentAdapter` still acquires/releases `ModelResourceManager` leases
around runtime execution. It supplies the selected profile alongside its id so
new persisted models can enter the existing manager under an explicit
composition-owned resource policy. A bare unknown id still fails closed.
Production uses the same provider-managed residency policy as bootstrap, with
unknown capacity estimates and no startup load.

Dynamic profiles with supplied local estimates participate in existing capacity
accounting. Existing descriptors retain their adapter/estimates. A profile
cannot change underneath an active lease; an idle changed profile resets its
cached resource state. No loading or lease acquisition occurs in the resolver.

## Errors and guards

All resolution errors derive from `ExecutionConfigurationError`, retaining
`ValueError` compatibility while carrying a stable `reason`:

- `ExecutionDefaultsNotConfiguredError`
- `ConfiguredReferenceMissingError` / `ConfiguredReferenceDisabledError`, with
  the configured domain identified
- `ModelProviderMismatchError`
- `RuntimeAdapterNotRegisteredError` / `ProviderAdapterNotRegisteredError`
- `CredentialResolutionFailedError`
- `ConfiguredModelIneligibleError`
- `ProviderConstructionFailedError`

The existing native-agent failure normalization and durable failed-run/event
path remain unchanged. Detailed typed reasons stay internal; this phase does
not redesign public error UX.

Architecture guards assert repository fan-out stays in the resolver, selection
uses the neutral port, Settings has no execution-resolution dependency,
configuration records remain SDK-free, result repr hides ports, and public
run/event contracts have no secret fields. The concrete-provider import guard
allows exactly one additional infrastructure file (`model_provider_factory.py`),
not an entire layer.

## Files changed for 5.16

This work completed an existing partial implementation in a workspace already
containing uncommitted 5.3–5.15 changes. Relative to the start-of-task snapshot,
the changed files are:

```text
backend/src/ava/execution/configuration_resolver.py
backend/src/ava/execution/persisted_execution.py
backend/src/ava/execution/selector.py
backend/src/ava/execution/model_orchestrator.py
backend/src/ava/execution/model_resources.py
backend/src/ava/models/provider_factory.py
backend/src/ava/models/bindings.py
backend/src/ava/infrastructure/model_provider_factory.py
backend/src/ava/infrastructure/composition.py
backend/src/ava/api/app.py
backend/src/ava/agents/adapters/native/native_agent.py
backend/tests/test_execution_configuration_resolver.py
backend/tests/test_persisted_execution_integration.py
backend/tests/test_architecture.py
docs/AVA_Phase_5_16_Execution_Configuration_Resolver.md
```

No Settings API/UI, frontend, persistence schema, RunService, AgentPort,
ExecutionProfile, or main Phase 5 plan file was changed by this task.

## Validation results

- Resolver tests: **54 passed**, exercising memory and SQLite repositories.
- HTTP/execution integration tests: **12 passed**, covering real adapter request
  mapping with mock HTTP transport, orchestration, runtime registry lookup,
  lease release, invalid-config rejection, bootstrap execution, restart
  durability, HTTP pool ownership, and dynamic capacity accounting.
- Combined resolver, architecture, credentials, orchestration, and resource
  checks: **224 passed** (includes the 54 resolver tests).
- Full backend: **1634 passed, 2 skipped**; four existing OpenHands SDK
  deprecation warnings.
- Ruff: passed over `backend/src` and `backend/tests`.
- mypy: passed over all 172 backend source files.
- `git diff --check`: clean.
- File hashes against the task-start snapshot confirm frontend unchanged.

The backend suite used `AVA_PERSISTENCE=memory AVA_ATTACHMENT_STORAGE=memory`
to avoid the documented repository `.env` contamination. Individual relational
tests explicitly select isolated SQLite files. Starlette TestClient hung at
thread startup inside the execution sandbox; integration and full-suite runs
passed outside that sandbox. No live model server or network endpoint was
needed for the new integration tests.

The first full run caught a terminal-cancellation regression while removing
completed provider references. Retaining terminal status without retaining the
provider fixed it; the final full-suite result above includes the correction.

## Phase 5.17 handoff — not implemented

1. Resolve the client/default distinction described above: current UI preset
   selections arrive as explicit legacy overrides. Do not silently reinterpret
   registry keys as configured-instance ids.
2. Bootstrap discovery/registries remain separate from persisted inventory.
   Decide seeding/migration and catalog visibility deliberately; do not migrate
   on resolver reads. Provider construction currently supports the registered
   OpenAI-compatible implementations, while other protocols need factories.
3. Persisted defaults are authoritative for default native runs now. Retain the
   absent/valid/invalid distinction during any bootstrap cleanup; invalid saved
   settings must never trigger fallback. Keep the explicit source diagnostic.
4. Configured records are synchronous read-time snapshots, not a cross-port
   transaction. Multi-process atomic configuration revisions would need an
   explicit repository-level design; this phase adds no revision/history model.
5. Keep provider-managed leasing until a real lifecycle adapter supplies resource
   estimates. Do not derive hosting mode or resource policy from endpoint text.

**Phase 5.16 complete. Phase 5.17 has not been started.**
