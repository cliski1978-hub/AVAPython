# AVA Phase 5.3 — Provider Connection Persistence

Phase 5.3 makes the Phase 5.2 `ProviderConnection` domain durable without
changing execution, settings APIs, or frontend state.

## Repository boundary

`ava.repositories.ProviderConnectionRepository` is the AVA-owned persistence
port. It accepts and returns only `ProviderConnection`; it has `create`,
`get`, `list`, and full-record `update` operations. The caller supplies the
stable `provider_connection_id`.

Both implementations have the same semantics: duplicate creation raises
`ValueError`, unknown reads/updates return `None`, and listing is stable
insertion order. Updating a record may change its display name, endpoint,
enabled state, and credential reference, but cannot change its `provider_id`.

## Implementations and composition

`ProviderConnectionStore` is the in-memory implementation. The SQLite adapter
is `RelationalProviderConnectionRepository`; both are exposed only by the
persistence composition bundles (`PersistenceRepositories` and
`ApplicationPersistence`). No service, `RunService`, `AgentPort`, execution
selection, HTTP route, or frontend module consumes the new repository.

## Schema and migration

Migration `v0004_provider_connections` creates `provider_connections` with a
surrogate insertion-order key and the exact durable fields:

`provider_connection_id`, `provider_id`, `display_name`, `endpoint`,
`enabled`, and `credential_reference`.

The connection identity is unique; endpoint and credential reference are
nullable; enabled is constrained to a SQLite boolean representation. The
migration is additive and leaves Phase 4 tables and rows unchanged.

`credential_reference` remains an opaque reference only. The schema contains
no credential value, token, password, API key, secret lookup, model, runtime,
or defaults field.

## Validation

Focused tests cover port abstraction, in-memory/relational parity, create/get/
list/update behavior, duplicate and missing behavior, nullable fields, enabled
state, deterministic ordering, provider-association stability, restart
durability, Phase 4-to-v4 migration, and persistence composition.

Validation run:

```text
pytest tests/test_provider_connection_repository.py tests/test_persistence_migrations.py
       tests/test_persistence_activation.py tests/test_persistence_database.py
       tests/test_repository_behavior_compatibility.py -q
36 passed

ruff check src tests
Success

mypy src
Success: no issues found in 148 source files
```

## Phase 5.4 implication

Provider connections are now available for future configuration services. They
are not yet used to construct providers or resolve execution; Phase 5.4 must
preserve the `RunService -> AgentPort` boundary when it introduces its next
bounded concern.
