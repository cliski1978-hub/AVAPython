# AVA Phase 5.35 — Configuration Failure Integration

## Purpose and boundary

Persisted execution resolution already rejected broken configured defaults without
falling back to bootstrap or environment selection. Before Phase 5.35, that
specific, actionable class of failure was collapsed into the generic durable
`agent_failed` result. This phase preserves the existing no-fallback policy and
makes only AVA-owned, safe configuration classifications available to the
assistant UI.

Phase 5.35 does not change execution selection, retry semantics, persistence
schema, or Settings implementation. It does not begin Phase 5.36 web
acceptance.

## Durable classification

`RunService` recognizes `ExecutionConfigurationError` and emits a durable
`run_failed` event whose payload has one of these normalized AVA-owned codes:

| Code | Meaning | Settings destination |
| --- | --- | --- |
| `configuration_missing` | Required execution defaults are absent. | Defaults |
| `configuration_invalid` | A configured reference is no longer valid. | None |
| `provider_connection_unavailable` | The configured provider connection cannot be used. | Providers |
| `model_unavailable` | The configured model cannot be used. | Models |
| `runtime_unavailable` | The configured runtime cannot be used. | Runtimes |
| `credential_unavailable` | Credentials for the configured provider cannot be resolved. | Providers |

The mapping uses no resolver, provider, or credential text as a classification.
The credential coverage proves that `SUPER_SECRET_SHOULD_NEVER_APPEAR` is not
persisted in the failure payload. Ordinary execution failures do not become
Settings problems: they retain the canonical generic `agent_failed` code.

The Phase 5.17 invariant remains unchanged:

```text
invalid persisted configuration != bootstrap/environment fallback
```

## Live and refreshed failure state

The existing durable run-event log is the sole source of configuration failure
classification. Live processing projects `run_failed.payload.error_code` into
`ConversationMessage.errorCode`. The assistant UI uses that code for safe
copy and determines a Settings target with `settingsSectionForFailure`; it never
parses error text or invents a code.

Closure testing found a refresh gap: the live event path preserved the code,
but a hydrated conversation only received message fields. The completed
projection is:

```text
failed assistant message + source_run_id
  + linked failed run + persisted run_failed.payload.error_code
  -> MessageResponse.error_code
  -> frontend conversation contract
  -> ConversationProvider
  -> ConversationMessage.errorCode
```

`ConversationService` therefore receives the already-existing
`RunEventRepository` through the established application composition path,
alongside its existing `RunRepository`. No repository abstraction was added.
It reads only the linked failed run's persisted `run_failed` event and projects
its string `error_code`; no missing historical value is synthesized. Failed
assistant messages without such a durable classification correctly return
`error_code: null`.

`MessageResponse.error_code` is an optional read projection. No database
migration is required because the durable source is the existing run-event log.

## UI ownership and navigation

`SettingsSectionId` is owned by `@ava/ui-core`. `agent-ui` determines a
remediation intent and exposes an `Open Settings` callback; it has no
dependency on settings-core implementation. Workspace owns navigation and
passes `initialSection` to `SettingsWorkspace`; settings-core owns the Settings
implementation.

The settings mapping is intentionally limited to the table above.
`configuration_invalid`, `agent_failed`, and every other unrecognized code
remain untargeted. The workspace replaces the mounted Settings view when the
target changes, so Models → return to conversation → Runtimes opens Runtimes
rather than retaining stale Models state.

Actionable failed assistant messages retain partial content and safe failure
copy, expose Open Settings, and retain Retry when the existing run policy makes
it eligible. There is no automatic retry, automatic Settings edit modal, or
loss of the original failed run.

## Final validation

Certified focused evidence:

```text
Resolver: 54 passed
No-fallback / secret suppression: 30 passed
Generic durable failure: 1 passed in 0.50s
RunService configuration normalization: 6 passed in 0.14s
ConversationService: 22 passed
FastAPI conversation routes: 22 passed
Agent UI: 193 passed
Workspace: 53 passed, 4 skipped

Backend Ruff: PASS
Backend mypy: PASS
Touched frontend package type checks: PASS
Web build: PASS
Desktop build: PASS
git diff --check: PASS
```

The known Vite chunk-size advisory is unchanged. Phase 5.34 remains the full
backend-suite baseline (`2,039 passed`, `2 skipped`, `4 warnings`); the next
full regression is reserved for Phase 5.40.
