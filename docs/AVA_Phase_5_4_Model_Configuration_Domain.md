# AVA Phase 5.4 — Model Configuration Domain

Phase 5.4 introduces the backend-only `ModelConfiguration` domain record. It
is configuration data only: no repository, database table, migration, API,
frontend contract, execution selection, or runtime coupling was added.

## Domain shape and identity

```text
ModelConfiguration(
    model_id,
    provider_connection_id,
    provider_model_name,
    display_name,
    hosting_mode,
    capabilities,
    enabled,
)
```

`model_id` remains the stable AVA-owned identity. It is distinct from the
opaque provider deployment id (`provider_connection_id`) and provider-facing
target (`provider_model_name`). A provider connection can therefore later
own multiple model configurations. Endpoint and credential-reference fields
remain exclusively on `ProviderConnection`.

`hosting_mode` reuses the canonical `ModelHostingMode`; capabilities reuse the
immutable AVA `ModelCapabilities` vocabulary. `enabled` defaults to true and
is configuration availability, not an authorization grant.

## Context and qualification decision

No context-window field was added. The current `context_limit` belongs to
provider-reported `ModelInfo` discovery metadata; neither `ModelProfile` nor
the registry owns it. Persisting it now would create a second authority before
its update/validation lifecycle is defined.

No qualification fields were added. `ModelQualification` remains separately
curated measured evidence keyed by stable `model_id`, rather than model
configuration capability or permission data.

## Relationship to execution types

`ModelProfile` remains the current execution-time immutable catalog record,
with `provider_id`. `ConfiguredModelBinding` remains a derived execution view
of a profile. Later configuration composition must resolve a persisted
`ModelConfiguration.provider_connection_id` to a provider connection and its
provider adapter, then derive `ModelProfile`, then `ConfiguredModelBinding`.
Phase 5.4 deliberately does none of those transformations.

No TypeScript/shared contract changed because no public API exposes this
domain yet. `RunService` and the `AgentPort` execution boundary remain unaware
of `ModelConfiguration`.

## Validation

Focused tests cover construction, identity separation, connection association,
provider model name, display name, canonical hosting/capability types, enabled
default, invalid values, and the `RunService` dependency guard. Ruff, mypy,
and `git diff --check` are run before completion.

## Phase 5.5 implication

Phase 5.5 should persist this exact record through the established AVA
repository/migration pattern. It must not change the record into a provider
SDK binding or make `ModelProfile` a database entity.
