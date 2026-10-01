# AVA Phase 5.37 — Desktop Acceptance

## 1. Scope

Accept the Desktop application (`frontend/apps/desktop`) as a thin Tauri/React
shell over the shared frontend stack, and prove that every user-visible Desktop
behaviour is the shared behaviour rather than a Desktop reimplementation.

In scope:

- Desktop startup and composition.
- The Tauri shell boundary.
- Composition of the shared workspace, agent UI, settings core, and contracts.
- Delegation of conversation, run, Settings, and recovery behaviour.
- Desktop build, lint, and focused Desktop acceptance tests.

Out of scope:

- Any change to shared behaviour proven correct on Web.
- Backend or agent changes.
- Phase 5.38.

## 2. Acceptance stance

Desktop is accepted as a **shell**, not as a second frontend. The question this
phase answers is not "does Desktop work" but "does Desktop do anything of its
own". A Desktop acceptance failure means Desktop has grown authority the backend
already owns.

Accordingly the evidence below is deliberately asymmetric. Shared behaviour is
evidenced by the shared suites; Desktop adds only a small composition harness
that asserts delegation.

## 3. Architecture requirement

The required hierarchy is unchanged:

```
Desktop shell (frontend/apps/desktop)
  └── @ava/workspace        (AppWorkspace: the application)
        ├── @ava/agent-ui   (runs, transcript, composer, message actions)
        ├── settings-core   (Settings sections)
        ├── @ava/contracts  (wire types)
        └── @ava/api-client (transport)
              └── backend       (durable, authoritative state)
```

Desktop may own: the Tauri runtime, the window, the opener plugin, and the API
base URL.

Desktop may not own: conversation state, run state, retry/regenerate
implementation, event replay, execution-profile or provider resolution,
configuration authority, credential storage, or any local durable store.

## 4. Startup and composition

`frontend/apps/desktop/src/App.tsx` constructs a single `ApiClient` from
`VITE_API_BASE_URL` with a `http://localhost:8000` fallback, and renders
`<AppWorkspace client={client} />`. `src/main.tsx` mounts that `App` and nothing
else.

**Finding: pass.** The Desktop entry point contains no conversation logic, no
run logic, and no state. It is a dependency-injection seam and nothing more.

## 5. Tauri shell boundary

`src-tauri/src/lib.rs` runs a `tauri::Builder` and registers the opener plugin
only. `tauri.conf.json` sets the dev URL to `http://localhost:5174` and
`frontendDist` to `../dist`. `capabilities/default.json` grants `core:default`
and `opener:default`.

**Finding: pass.** The Tauri side opens external links and shows a window. It
carries no API bridge, no command surface for run lifecycle, and no filesystem
authority. There is no second path to run state that could diverge from the
backend.

## 6. Shared package reuse

Desktop's `App.tsx` is byte-identical to the Web entry point; the only
difference is the dev port (5174 vs 5173). Desktop depends on `@ava/api-client`
and `@ava/workspace` as workspace packages.

**Finding: pass.** The shell mounts the shared composition. Every conversation,
run, Settings, and document surface reachable from Desktop is the same component
tree Web uses.

## 7. Conversation list and creation

**Finding: pass (delegated).** Conversation list, selection, and creation come
from the shared `ConversationProvider` via `AppWorkspace`. The Desktop harness
asserts a conversation is listed and becomes the active selection after mount.

## 8. Prompt submission

**Finding: pass (delegated).** The shared `PromptComposer` is the only input
path. Submitting a prompt in the Desktop harness produces exactly one
`createMessage` call for the durable user message and exactly one `startRun`
call, with the prompt, `conversation_id`, and `source_user_message_id` taken
from the shared conversation. The request carries no `retry_of_run_id`, because
a first submission is not a retry.

Assembling a response from a run's ordered events is shared behaviour covered by
the workspace and agent-UI suites; the Desktop harness does not re-derive it.

## 9. Run start and stream observation

**Finding: pass (delegated).** Run start, backend status tracking, resumable SSE
observation, and event application all live in `@ava/agent-ui`'s conversation
run module, reached through `clientRunAgent` over the shared `ApiClient`.

**Finding: no Desktop-local transport.** Desktop adds no polling, no SSE client,
and no second observation path.

## 10. Backend-authoritative state

**Finding: pass.** Desktop renders what the shared clients return and holds no
authoritative copy. The acceptance harness seeds a completed durable turn and
asserts it survives a new submission: Desktop appended a turn rather than
replacing backend state.

## 11. Local persistence

**Finding: pass.** The Desktop source contains no `localStorage`,
`sessionStorage`, `indexedDB`, filesystem, Tauri store, or any other local
durable store. The harness asserts this over the shell source as well as at
runtime, so a future local cache would fail acceptance rather than ship
unnoticed.

## 12. Settings navigation

**Finding: pass (delegated).** Settings opens from the shared header tab and
exposes the shared sections. Conversation-specific chrome is hidden with
`display: none` rather than unmounted, so in-session state survives a view
switch. The harness asserts the hidden-ancestor state rather than DOM absence,
because asserting absence would assert the opposite of the intended behaviour.

## 13. Settings data loading

**Finding: pass (delegated).** Settings reads through the shared
settings-core sections and the shared API client, against the documented
contracts (`provider_connections`, `models`, `runtimes`, execution defaults).

**Finding: no Desktop-side resolution.** Provider, model, runtime, workspace,
and execution-default selection are resolved by the shared layer against backend
state. Desktop resolves nothing locally.

## 14. Credentials and secrets

**Finding: pass.** Desktop stores, prompts for, and transmits no credential.
Connection configuration is expressed as backend-side credential references.
The Tauri capability set includes no secret or filesystem access.

## 15. Retry and regenerate

**Finding: pass (delegated).** Recovery controls are the shared
`MessageActions` toolbar. A completed durable turn exposes **Regenerate
response** and not Retry; a failed durable turn exposes **Retry response** and
not Regenerate. Both are asserted against the shared accessible names.

Retry and regenerate branch from the durable `source_run_id` recorded by the
backend. Desktop neither infers lineage from position or text nor issues the
follow-up run itself.

## 16. Accessibility surface

**Finding: pass.** Every Desktop-reachable control is a shared control with a
real role and accessible name: workspace tabs (Chat, Documents, Settings), the
composer textbox, the send button, and the message-action toolbar buttons. No
Desktop-specific affordance, shortcut, or overlay exists to keep accessible.

## 17. Shared test evidence

Focused shared suites were run as the behavioural baseline for what Desktop
delegates to:

| Suite | Result |
| --- | --- |
| `@ava/workspace` | 53 passed, 4 skipped |
| `@ava/agent-ui` | 193 passed |
| `@ava/desktop` | 11 passed |

The existing `step411.architecture.test.ts` guard was read and confirmed to
already cover Web and Desktop shared-workspace composition, so it was not
duplicated.

## 18. Desktop acceptance harness

`frontend/apps/desktop/src/App.test.tsx` is a focused shell harness covering:

- the shared workspace mounts and the composer is reachable;
- Desktop adds no providers, stores, or lifecycle beyond the shared tree;
- backend state is authoritative and survives a new submission;
- the API base URL comes from the environment, with the documented fallback;
- prompt submission drives the shared run path with correct lineage;
- Settings navigation exposes the shared sections;
- Retry and Regenerate appear on the correct durable turn state;
- accessibility roles and names;
- the shell source contains no local persistence, transport, or run lifecycle.

`vitest.config.ts` and `src/test/setup.ts` provide the jsdom and cleanup
harness. The `test` script and its dev dependencies were added to
`frontend/apps/desktop/package.json`.

## 19. Harness corrections made during acceptance

Three incorrect harness assumptions were found and fixed. Each was a mistake in
the new Desktop test, not a Desktop defect:

1. Settings list mocks used invented response shapes (`connections`,
   `configurations`) instead of the documented contracts (`provider_connections`,
   `models`, `runtimes`).
2. Settings visibility was asserted as DOM absence, contradicting the shared
   `display: none` pane strategy that preserves in-session state.
3. Message-action controls were matched by guessed names rather than the shared
   accessible names `Retry response` and `Regenerate response`.

A fourth assumption — re-deriving run event assembly inside the Desktop harness
— was removed as out of scope, because that behaviour is shared and already
covered.

## 20. Validation commands and results

| Command | Result |
| --- | --- |
| `pnpm --filter @ava/desktop build` | exit 0; 199 modules transformed |
| `pnpm --filter @ava/desktop lint` | exit 0 |
| `pnpm --filter @ava/desktop test` | exit 0; 11 passed |
| `pnpm --filter @ava/workspace test` | exit 0; 53 passed, 4 skipped |
| `pnpm --filter @ava/agent-ui test` | exit 0; 193 passed |
| `git diff --check` | exit 0 |

Build output: `dist/assets/index-DuWeGZp6.css` 3.63 kB,
`dist/assets/index-CBixrr7W.js` 664.99 kB (gzip 205.06 kB), built in 1.28s. The
existing Vite chunk-size advisory is unchanged and accepted.

## 21. No backend changes

No backend, agent, or shared-package source was modified in this phase. The
lockfile changed only to add the Desktop test dev dependencies. No backend test
suite was run, because Desktop acceptance produced no evidence of a backend
defect.

## 22. No Web acceptance changes

No Web source was modified and no Web behaviour was re-litigated. Nothing
Desktop acceptance surfaced justified reopening Web acceptance.

## 23. Findings requiring action

None. Desktop acceptance produced no product defect, no shared defect, and no
architecture violation.

## 24. Files changed in this phase

- `frontend/apps/desktop/package.json` — added `test` script and test dev
  dependencies.
- `frontend/apps/desktop/vitest.config.ts` — new Desktop test harness.
- `frontend/apps/desktop/src/test/setup.ts` — new Testing Library cleanup.
- `frontend/apps/desktop/src/App.test.tsx` — new focused Desktop shell
  acceptance harness.
- `pnpm-lock.yaml` — test dependency resolution (+18/−3).
- `docs/AVA_Phase_5_37_Desktop_Acceptance.md` — this document.

## 25. Phase 5.37 closure

Phase 5.37 is fully closed. The Desktop application is accepted as a thin Tauri
shell that mounts the shared workspace and adds no second source of truth. No
follow-up work is required, and Phase 5.38 was not started.
