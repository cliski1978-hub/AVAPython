# Phase 5.2 — Provider Connection Domain

`ProviderConnection` is an AVA-owned, backend-only domain type in
`ava.models.provider_connections`.

```text
Provider
  = adapter/type/capability implementation (ModelProviderPort)

ProviderConnection
  = one configured deployment handled by that provider
```

For example, one OpenAI-compatible provider adapter may later handle separate
configured connections for a local endpoint, a company gateway, and another
approved deployment. Those are separate `provider_connection_id` values; they
do not change the adapter's `provider_id`.

The Phase 5.2 record contains an opaque endpoint and an opaque credential
reference, never credential material. It contains no model or runtime identity
and is not yet persisted, composed into execution, exposed by an API, or used
by frontend state. Those deliberate omissions preserve bootstrap behavior for
later bounded Phase 5 steps.
