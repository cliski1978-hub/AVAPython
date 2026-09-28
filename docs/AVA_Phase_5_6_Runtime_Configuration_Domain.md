# AVA Phase 5.6 — Runtime Configuration Domain

Phase 5.6 adds the backend-only `RuntimeConfiguration` record:

```text
RuntimeConfiguration(
    runtime_configuration_id,
    runtime_type,
    display_name,
    enabled=True,
)
```

`runtime_configuration_id` is the stable AVA identity for one configured
runtime instance. `runtime_type` is separately the adapter/framework kind.
AVA's existing `RuntimeRegistry` key (`runtime_id`) is an opaque lookup key for
an already-constructed `AgentRuntimePort` and may differ from adapter metadata;
the current `native` and `openhands` keys are runtime types, not persisted
configured-instance records.

Display name is future Settings/selector metadata and does not determine
identity. Enabled defaults to true and is availability configuration, not user
authorization.

No runtime-specific configuration bag was added. Native currently needs none;
OpenHands constructor inputs are composition-owned security/policy objects,
not reusable runtime-instance settings. The record contains no model, provider,
provider connection, workspace, tool authority, credential, or SDK type.

Later composition may resolve a runtime configuration's type to a constructed
registry adapter, after persistence exists. This step does not alter the
registry, `RuntimeResolver`, `AgentPort`, or `RunService` boundary.

Current execution profiles are bootstrap discovery presets combining a
`runtime_id` and `model_provider_id`; they remain untouched and are not a
runtime-configuration representation. Phase 5.8/5.16 should reconcile that
bootstrap coupling with independently persisted settings.

No TypeScript contracts changed because there is no public settings API. Phase
5.7 should persist this exact record through the existing repository/migration
pattern, without adding model/provider fields.
