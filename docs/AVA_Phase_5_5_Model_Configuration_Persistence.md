# AVA Phase 5.5 — Model Configuration Persistence

`ModelConfigurationRepository` now provides `create`, `get`, stable-order
`list`, and full-record `update` operations for Phase 5.4's exact domain
record. Memory and SQLite adapters match: duplicate model ids raise
`ValueError`, missing reads/updates return `None`, and the
`provider_connection_id` association is immutable after creation.

Migration `v0005_model_configurations` creates the minimal table:

```text
id, model_id, provider_connection_id, provider_model_name, display_name,
hosting_mode, capabilities, enabled
```

`model_id` is unique and insertion order is by surrogate `id`. Hosting mode is
stored as canonical `ModelHostingMode.value`. Capabilities are stored as
deterministic, sorted AVA-owned JSON from `ModelCapabilities.model_dump()` and
validated back through `ModelCapabilities.model_validate()`.

AVA's prior schema deliberately has no declarative foreign keys, so this step
preserves that convention. Both adapters explicitly verify that the referenced
provider connection exists before creation; unknown connections are rejected.
No endpoint, credential, context window, qualification, runtime, or execution
field is added.

The repository is exposed through memory, relational, and application
persistence composition only. `RunService`, `AgentPort`, execution selection,
and public/API/frontend contracts remain unchanged.

Tests cover parity, integrity rejection, hosting/capability round trips,
enabled persistence, ordering, immutable association, restart durability, and
v0004-to-v0005 migration while preserving provider connections. Phase 5.6 can
add only its runtime-configuration concern; it should not alter this model
record or wire it into execution.
