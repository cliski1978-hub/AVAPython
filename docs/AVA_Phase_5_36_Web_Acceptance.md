# AVA Phase 5.36 — Web Acceptance

## Scope and harness

The Web application (`@ava/web`) is a production shell that composes one
`ApiClient` with `AppWorkspace`. The highest practical repository-supported
acceptance harness is the jsdom `@ava/workspace` integration suite, which
exercises the same workspace, agent UI, API-client boundaries, run observer,
and Settings navigation used by the Web shell. The opt-in real HTTP suite,
`live-workspace-run.integration.test.tsx`, is available when
`AVA_LIVE_BACKEND_URL` is supplied; it was not configured for this validation.

No Phase 5.35 architecture was redesigned. No Web-specific persistence or
lifecycle behavior was introduced.

## Startup and shell

`@ava/web` lint and production build pass. The shell mounts `AppWorkspace`,
which renders the main Chat workspace and exposes Chat, Documents, and Settings
navigation. The existing Vite chunk-size advisory remains unchanged and is not
a regression.

## Conversation and run acceptance

The workspace harness covers durable conversation selection and isolation,
including reselecting without duplicate messages and remounting from persisted
history. Prompt submission exercises the shared conversation/run flow: a user
message and run are created, an assistant placeholder is tied to the accepted
run identity, and run events update that same assistant message.

Streaming-capable fixtures exercise progressive assistant updates with sequence
handling. Shared run tests cover partial-content updates, terminal completion,
durable completed-message persistence, refresh recovery for active runs, and
terminal refresh without a second observer or duplicate assistant message.

The integration suite also covers regenerate reconciliation by run/message
identity, preserving immutable earlier history and showing only the appropriate
transcript response. Rejected regeneration produces no ghost assistant bubble.
Retry and cancellation remain the shared run-controller behaviors: retry starts
a new attempt/run identity; cancellation records backend intent and waits for
the authoritative terminal state rather than claiming cancellation locally.

## Failure and remediation acceptance

Generic failures use the safe shared presentation and remain untargeted:
`agent_failed` does not expose Open Settings. Partial content and Retry remain
available according to the existing run policy.

The workspace acceptance fixture hydrates a failed assistant message with
`model_unavailable` from the conversation API and verifies that Open Settings
is accessible and selects Models. This is a refresh-safe path: the code comes
from `MessageResponse.error_code`, projected from the durable failed run event,
not transient browser state. Phase 5.35 focused mapping coverage additionally
establishes Defaults for `configuration_missing`, Providers for provider and
credential failures, and Runtimes for runtime failures.

Workspace navigation owns the destination and remounts `SettingsWorkspace` for
each target. The shared settings-navigation suite covers all four Settings
sections and preserves usable conversation state after returning to Chat.

## Switching, replay, and persistence

Conversation-selection integration covers A/B switching, stale late list
responses, remount refresh, and in-flight assistant state when reselecting a
conversation. Shared run tests cover run epoch, identity, event-id, and
sequence protections, along with replay/resume and snapshot reconciliation, so
late or duplicate events cannot append duplicate assistant content.

The Web, workspace, and agent-ui sources contain no `localStorage`,
`sessionStorage`, or `IndexedDB` references. Browser memory is an interaction
projection only; conversation/run recovery reads durable backend state.

`execution_interrupted` remains a generic safe failure presentation: partial
content is retained, Settings is not offered, and Retry follows existing
eligibility. Full backend restart/durability testing remains Phase 5.38 scope.

## Accessibility smoke result

The accepted flows use named controls: Send, Retry, Regenerate response, Open
Settings, top-level workspace tabs, and named Settings section tabs. The
configuration-remediation test invokes Open Settings by accessible name and
asserts the target section is selected.

## Defects and production changes

No Web-specific or shared production defect was exposed by the acceptance
harness. This phase adds this acceptance record only.

## Focused evidence

```text
@ava/workspace: 53 passed, 4 skipped
  - 4 skipped are opt-in live-backend workspace tests; no live URL was configured
@ava/web lint: PASS
@ava/web build: PASS
git diff --check: PASS
```

The pre-existing Phase 5.35 evidence remains applicable to the shared failure
and Settings behavior: Agent UI 193 passed; backend and shared frontend checks
passed; Web and Desktop builds passed.

## Known limitation and Phase 5.37 handoff

This validation did not use a live backend/provider because the opt-in backend
URL was unavailable. It validates the production Web composition through the
repository's supported integration harness. Phase 5.37 should perform the same
surface acceptance for the Desktop shell, using its application composition and
the existing shared integration coverage; it must not alter Web or backend
semantics unless Desktop acceptance exposes a concrete defect.
