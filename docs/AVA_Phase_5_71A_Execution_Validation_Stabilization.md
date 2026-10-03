# Phase 5.71A — Execution Validation and Stabilization

**Status: COMPLETE**

This record closes the validation blockers recorded by Phase 5.71. It adds no
execution feature or new Phase 5 capability.

## Attachment restart-recovery stall

The affected regression is
`tests/test_attachment_restart_recovery.py::test_api_end_to_end_restart_smoke_relational_metadata_local_content`.
Temporary checkpoints and a thread stack trace located the first block at
`TestClient.__enter__`, while Starlette's TestClient waited for its AnyIO
portal to start the application lifespan (`portal.start_task_soon(self.lifespan)`).
The lifespan itself had not begun. The portal's event-loop thread was idle in
`selectors.select`.

The test passed when run outside the restricted sandbox, as did the entire
canonical harness. A bare `TestClient(FastAPI())` reproduced the same stall in
the restricted sandbox. This isolates the cause to the sandbox's local thread/
event-loop wake-up behavior, rather than an AVA lifespan, SQLite lock, content
handle, hard-delete, or recovery defect. The same evidence makes the issue
unrelated to Phase 5.71 execution-context changes; historical provenance was
not independently established.

No production workaround, arbitrary timeout, weakened assertion, or
diagnostic logging was retained. No product-code mutation proof applies because
there was no product fix to mutate. The existing end-to-end restart test remains
the deterministic regression and passes in the canonical environment:

```text
1 passed in 0.80s
```

All focused attachment suites passed: **205 passed** across attachment
contracts, persistence, local content, repositories, API behavior, and restart
recovery. The complete backend run also passed the same restart test.

## Architecture boundary and hard-delete preservation

`ava/api/app.py` imported and selected
`RelationalConversationHardDeleteCoordinator` directly, bypassing the intended
API → composition → service port → persistence adapter boundary. The repair
adds `create_relational_conversation_hard_delete_coordinator` to persistence
composition and `create_conversation_hard_delete_coordinator` to application
infrastructure composition. The API factory now asks the composition seam for
the coordinator and no longer names or casts the concrete adapter.

The adapter still performs the same transactional deletion, including
conversation-owned attachment metadata/content and conversation-scoped CORE
assignments. Port-selection tests cover both in-memory and relational adapters;
existing rollback, shared-record, active-run, and owned-graph tests remain in
place. The architecture and hard-delete suites passed: **134 passed**. No guard
was suppressed.

## Canonical and live validation

The canonical backend script was launched on port 8001 with a disposable
database for live prompt runs; `/health` returned healthy and the database
initialized at **schema 16**. A second canonical start on port 8001 used the
existing development database. Its normal additive migration advanced that
database from schema 15 to **schema 16**, created
`core_prompt_assignments`, and passed `PRAGMA integrity_check`. Post-migration
counts were 10 conversations, 88 messages, 74 runs, 13,997 run events, 0
Projects, and 0 CORE prompt definitions. The migration did not delete or
rewrite these rows. The pre-existing process on port 8000 was left running;
the root `.env` was restored to port 8000 and `ava.sqlite3` after each check.

The canonical web script started AVA at port 5175 after finding 5173 and 5174
occupied, and the AVA page loaded. A later Vite watcher-limit (`ENOSPC`) error
ended that temporary web process. The disposable prompt-test database and the
temporary services started for this validation were cleaned up.

The configured Ollama service at `127.0.0.1:11434` was already running, and
`qwen2.5-coder:7b` was installed. The validation run selected:

```text
provider: local
connection: bootstrap-provider-local (Bootstrap local)
model: qwen2.5-coder:7b (local-qwen2.5-coder:7b)
runtime: native (bootstrap-runtime-native)
hosting: local
```

These settings were compared before and after the prompt tests and did not
change. The configured model reports `streaming: false` and `tool_calling:
false`; the validation did not enable capabilities or change runtime/model
selection.

The live root-only baseline completed and returned `BASELINE-571A`. With a
temporary Global CORE marker, `/core-prompts/resolve` included the marker and a
real run returned `CORE-571A`. A Project conversation with the specified
Project instruction and a Project-scope DISABLE excluded the CORE marker in
preview and returned `PROJECT-571A`. Adding a Conversation ENABLE restored the
marker in preview and execution. A Folder DISABLE excluded it; clearing Folder
membership restored Global resolution. A global conversation continued to
resolve the Global prompt independently of Project overrides.

The run stream endpoint delivered `message_content` and `run_completed` SSE
events. Since this model is configured without provider token streaming, this
proves AVA run-event streaming, not token-by-token local-model output. A live
retry of the same persisted user turn after disabling the marker returned no
CORE marker, demonstrating current-configuration resolution on retry. The live
mid-run assignment mutation was not attempted because the configured model
does not stream tokens; the deterministic
`test_mid_stream_assignment_change_affects_next_request_only` regression
covers that timing guarantee. Layer order (AVA root → CORE → Project
instructions → history → current message), context isolation, and capability
boundaries are covered by the focused execution tests. Prompt-layer text was
not exposed through a live diagnostic endpoint.

The deterministic marker and all Projects, Folders, Conversations, messages,
and runs were created only in the disposable validation database. That
database was deleted after the servers stopped. The pre-existing user
database was not modified. The temporary CORE prompt was created through the
API; the web UI was started and loaded, but the prompt was not created through
the UI.

## Automated checks

- Focused Phase 5.71 execution/resolver/assignment/persistence/streaming/
  provider-translation suites: **118 passed, 4 skipped**.
- Focused attachment suites: **205 passed**.
- Architecture and hard-delete suites: **134 passed**.
- Full backend suite: **2,435 passed, 6 skipped, 4 third-party deprecation
  warnings**.
- Backend Ruff: passed for `src` and `tests`.
- Backend mypy: passed for all 220 source files.
- Frontend workspace tests and TypeScript checks: passed through the canonical
  harness; Python client: **10 passed**, Ruff and mypy passed.
- Canonical `./scripts/test_all.sh`: **passed**. It ran without the previous
  artificial timeout. The harness does not produce production Web/Desktop
  builds; no frontend production file was changed in this stabilization step,
  so those extra builds were not required.
- `git diff --check`: passed after the final documentation changes.

The earlier test-only corrections update assertions and doubles to the current
Phase 5 schema/migrations and canonical conversation ordering. They do not
change execution behavior. The previous app-to-adapter hard-delete wiring is
now behind composition, so the formerly failing architecture guards pass.

## Phase status

```text
5.71 Execution Context Injection       COMPLETE
5.71A Validation/Stabilization         COMPLETE
Next Phase 5 extension step            NOT STARTED
```

Phase 5.71 is fully validated. No subsequent Phase 5 feature work was started.
