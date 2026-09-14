# AVA Sprint 2 — Core AI User Experience Log

Sprint title: **Sprint 2 — Core AI User Experience**

Goal: build the standard AVA AI application experience first. Reference plan:
`docs/AVA_Sprint_2_Plan.md`.

---

## Step Tracker

| Step | Scope | Status |
| --- | --- | --- |
| 1 | Core UI shell (header, collapsible sidebar, main workspace, composer region, status area, responsive) | Complete |
| 2 | Shared UI components (`@ava/ui-core`: Button, Textarea, Input, IconButton, StatusIndicator, LoadingIndicator, EmptyState, Panel, Sidebar, Header, AppShell, MainContent, Divider) | Complete |
| 3 | Conversation / message UI (`@ava/agent-ui`) | Complete |
| 4 | Prompt composer (multiline, Send, Stop, Enter/Shift+Enter) | Complete |
| 5 | Frontend conversation state (conversationReducer, useConversationStore) | Complete |
| 6 | Mock agent behind `AgentPort` | Complete |
| 7 | Run API (POST /runs, GET /runs/{id}, GET /runs/{id}/events, POST /runs/{id}/cancel) | Complete |
| 8 | Run / event lifecycle (backend run lifecycle; frontend event processor) | Complete |
| 9 | Agent UI integration (web + desktop render the shared conversation UI) | Complete |
| 10 | Cancel / retry / regenerate / copy / error UX | Complete |
| 11 | Web + Desktop integration validation | Complete |
| 12 | Shared Tiptap document workspace | Complete |
| 13 | AVA document model and state foundation | Complete |
| 14 | Basic in-memory document operations | Complete |
| 15 | Final validation and sprint sign-off | Complete |

Deferred: durable document persistence, document backend APIs, filesystem
operations, agent-driven document editing, approvals, and future runtimes.

---

## Step 15 — Final Validation

Step 14 rename regressions are covered: the title field accepts a temporarily
empty draft until commit, and selecting an existing document or creating a new
one cancels rename mode before active-document state changes. This prevents a
rename draft from leaking into another document.

Final automated validation passes: backend 108 tests; frontend 169 tests
(contracts 5, ui-core 20, api-client 17, document-core 11, agent-ui 112,
workspace 4); and Python client 1 test. Ruff, mypy, and every TypeScript
check pass. `./scripts/test_all.sh` is green. Web and Desktop Vite builds pass
with only Vite's informational chunk-size warning. Native Tauri compilation
and process launch pass; direct native GTK/WebKit interaction remains a manual
verification item because this host automation cannot attach to that window.

`SPRINT 2 — COMPLETE`

`SPRINT 2 — APPROVED FOR SIGN-OFF`

---

## Step 11 — Integration Validation Report

### Summary

| Area | Result |
| --- | --- |
| Backend unit/integration tests | 108 passed |
| Frontend unit tests | 154 passed (contracts 5, ui-core 20, api-client 17, agent-ui 112) |
| `scripts/test_all.sh` | Exit 0 (backend tests + ruff + mypy + frontend tests + tsc + clients) |
| Web runtime matrix (headless CDP) | 20/20 scenarios green (151 checks) |
| Desktop runtime matrix (headless CDP) | 18/18 scenarios green (137 checks) |
| JS console errors (all scenarios) | 0 |
| React key / style-shorthand warnings | 0 |
| Lint / typecheck / builds | Clean |

### Web scenarios validated (with seed greeting) on `:5173`

- empty — global empty state `No conversation selected.`; no message area.
- newchat — AVA identity + starter prompts when a new conversation is active and empty.
- success — user/pending/complete bubbles; exactly one `POST /runs` and one
  `GET /runs/{id}/events`; header stable during run; `AVA mock agent received: …` echo.
- consecutive — sequential runs in one conversation; no duplicate messages or leaked state.
- shortbubbles / longuser / longassistant — single bounded bubble; long content wraps without full-bleed.
- switching / isolation — A→B→C switching preserves per-conversation messages.
- midrunswitch — switching away and back during a slow run keeps states correct.
- starting — truthful "Starting…" + Stop disabled until `run_id` exists.
- failure — backend run failure renders failure bubble + Retry; no internals leak.
- retry — failed run retried via same `run_id` path; recovery message replaces failure state.
- regenerate — regenerates the assistant response in-place.
- unavailable — backend down shows a clean unavailable error; no page crash.
- recovery — backend restored while page stays open; Retry recovers without a reload.
- copy — assistant messages copy verbatim to clipboard.
- scroll — near-bottom follows new content; a scrolled-up reader is not yanked.
- viewports — 1440/1024/768/480/380 no horizontal overflow; sidebar collapses
  below 768; bubbles stay bounded.
- narrow / keyboard — mobile layout + Tab/Enter/Send/focus-visible indicators.
- consecutive + regenerate + copy validated on desktop with identical expectations.

Desktop (`:5174`) ran the same matrix against the same backend configs and
matched the web results (cross-platform parity confirmed).

### Runtime configurations used

- Default dev backend `:8000` for the standard matrix.
- `VERIFY_MODE=slow` (`run_delay=1.0`) on `:8011` for deterministic
  starting-state and mid-run-switch validation.
- `VERIFY_MODE=failure` on `:8010` for failure/retry paths.
- `VERIFY_MODE=failonce` on `:8013` for the failing-then-succeeding retry proof.
- `VERIFY_MODE=success` on `:8099` (started/stopped while the page stayed open)
  for backend-unavailable and recovery-without-reload validation.

### Defects found and fixed during Step 11

1. **React "mixing shorthand and non-shorthand" style warning** — `Button`,
   `Textarea`, `Input`, and `LoadingIndicator` combined the `border` shorthand
   with `borderColor`/`borderTopColor` longhands, which React flags as a dev
   warning. Fixed by using explicit `borderWidth` + `borderStyle` + `borderColor`
   longhands only. Regression tests added in `ui-core` asserting the longhands
   and forbidding the shorthand in the rendered style.
2. **Step 10 pill finalization** — user pills use `border-radius: 999px`;
   assistant bubbles use `border-radius: lg + 12` (20px). VM and tests updated
   to match; verified 11/11 on web and desktop.
3. **Test-harness robustness** (not product code) — pending-state polling must
   begin immediately after submit because the 1 ms mock completes faster than a
   casual poll interval.

### Architecture / compliance checks (grep + runtime)

- No `fetch`/`axios`/`XMLHttpRequest` outside `@ava/api-client`. ✔
- No runtime/model names (LangChain/LangGraph/Ollama/OpenAI/… ) in UI code. ✔
- No test ports (`:8010/:8011/:8013/:8099`) or verify modes in app defaults. ✔
- No demo data / sample conversations / hardcoded responses in app code. ✔
- No array mutation outside reducers; state updated immutably. ✔
- `streaming` capability truthfully `false`; event retrieval is snapshot-only. ✔
- Thin App shells: `web/src/App.tsx` and `desktop/src/App.tsx` are identical
  139-line wrappers with no data fetching or agent logic. ✔
- `ui-core` remains API/runtime-free; `agent-ui` provider-neutral. ✔
- Backend capabilities truthful: `health`, `runs`, `cancellation` true;
  `streaming`, `tool_calling`, `document_operations`, `local_model`, etc. false. ✔

### Known limitations (documented, in scope for Sprint 2)

- Conversation persistence not implemented (in-memory; refresh clears state).
- Streaming not implemented; runs are snapshot-only by design.
- Backend run startup is synchronous, so the normal UI rarely observes a
  cancellable `running` window before completion; Stop-enabled behavior is
  unit-tested and validated on the slow configuration.
- Real model/runtime not integrated (mock adapter only).
- Attachments and tool panels are not implemented. Document editing is local
  to the current session; document persistence and agent-driven document
  operations are not implemented.

### Files changed (Step 11)

- `frontend/packages/ui-core/src/components/{Button,Textarea,Input,LoadingIndicator}.tsx` — border longhands.
- `frontend/packages/ui-core/src/components/button.test.tsx`, `textarea.test.tsx` — style regression tests.
- `docs/Architecture.md` — Sprint 2 runtime flow + implemented-state notes.
- Validation harnesses: `/tmp/opencode/cdp11.mjs`, `shot11.mjs`,
  `step10_verify.py` (test infrastructure, not committed).

### Screenshots

Captured (headless Chrome, deviceScaleFactor 2) to `/tmp/opencode/shots11/`:
`web_wide_success.png` (1440), `web_narrow_success.png` (380),
`web_failure.png` (1280), `desktop_success.png` (1280),
`desktop_narrow_success.png` (420). All captured with 0 console errors.

---

## Step 12 — Tiptap Integration Report

### Shared editor and workspace

`@ava/document-core` contains the sole Tiptap integration in
`src/editor/DocumentWorkspace.tsx`. It configures StarterKit, owns all editor
commands and toolbar state, and provides the local document surface. The
shared `@ava/workspace` package owns Chat/Documents workspace selection and
is consumed unchanged by both Web and Desktop shells.

Opening Documents mounts the editor. After that, both workspace panes remain
mounted, so returning to Chat preserves conversation state and returning to
Documents preserves the unsaved editor session. There is no persistence,
document identity, document backend API, or AVA document-domain model.

### Editor and toolbar

The editor supports paragraphs, headings, bold, italic, bullet lists,
ordered lists, undo, and redo. The toolbar uses AVA `Button` and `Divider`
primitives. Formatting controls expose names and `aria-pressed` state; the
editor itself is labelled `Document content`. Tiptap restores editor focus
when toolbar commands run, and native Tiptap keyboard shortcuts remain
available.

### Isolation and dependencies

Tiptap-specific APIs and types are confined to `@ava/document-core`; neither
the application shells, contracts, backend, nor run events import them.

Added dependencies, all pinned at `3.31.3`:

- `@tiptap/core`
- `@tiptap/react`
- `@tiptap/starter-kit`

### Tests and validation

`document-core` has 9 behavioral tests covering editor rendering, initial
content, edits, formatting, lists, undo/redo, and accessible active state.
`@ava/workspace` has 4 tests covering default chat state, workspace switching,
conversation preservation, and editor-session preservation. The existing
frontend suite reports 167 tests across contracts, UI core, API client,
agent UI, document core, and workspace.

Production Web and Desktop builds pass. The editor test suite runs without
React, Tiptap, or ProseMirror warnings.

### Verification remediation

The complete backend validation suite passed: `pytest` reported 108 passed,
Ruff was clean, and mypy reported no issues. `./scripts/test_all.sh` also
completed successfully: 108 backend tests; 167 frontend tests (contracts 5,
UI core 20, API client 17, agent UI 112, document core 9, workspace 4); all
frontend TypeScript checks; and Python client compilation.

The normal backend at `:8000` returned `GET /health` with HTTP 200. The Web
application at `:5173` was exercised at 1440, 1024, 768, 480, and 380 px.
At every width the editor and toolbar were visible and `scrollWidth` matched
the viewport width. Typing, paragraphs, headings, bold, italic, bullet and
ordered lists, toolbar undo/redo, and Ctrl+B/Ctrl+I/Ctrl+Z/Ctrl+Shift+Z all
worked. Toolbar active states were exposed through labelled pressed controls;
the editor retained usable focus after commands.

The runtime Chat → Documents → Chat scenario preserved the submitted mock
response, and returning to Documents preserved unsaved editor content. The
Web browser console had zero warnings and errors. No document API requests
were introduced; code inspection confirms no document endpoints, persistence,
or Tiptap imports outside `@ava/document-core`.

The Desktop frontend target at `:5174` passed the same shared-editor,
Chat/Documents preservation, console, and five-width responsive checks.
Native Tauri itself could not be launched because the system has no `cargo`
executable; this is the only remaining verification blocker.

### Status

`STEP 12 NOT COMPLETE`

All implementation, backend, Web runtime, Desktop frontend-target, static,
and build verification is complete. Native Tauri webview verification remains
blocked until Rust/Cargo is available on the host.

---

## Step 13 — Document-Core Foundation Report

`@ava/document-core` now owns AVA's serializable document model and in-memory
state. A document has an AVA-generated ID, title, HTML `DocumentContent`, ISO
timestamps, and AVA-owned dirty state. The provider initializes a document
collection with one active `Untitled Document`; no document persistence, API,
or document-operation UI was added.

Tiptap remains an implementation detail. `EditorAdapter` is the small
AVA-facing editor capability surface, while `TiptapEditorAdapter` performs the
HTML conversion at the integration boundary. The workspace initializes Tiptap
from active AVA state and routes editor updates back to the provider, marking
the document dirty without feeding those updates back into the editor.

The document-core package checks pass: 5 tests across model serializability,
immutable reducer updates, adapter conversion, and workspace rendering; its
TypeScript check also passes. Workspace TypeScript validation passes.

### Native Tauri remediation

Native Tauri startup initially failed because `tauri::generate_context!()`
requires `src-tauri/icons/icon.png`, and the repository contained no icon
asset. There was no existing AVA artwork, so a simple temporary development
icon was added at `frontend/apps/desktop/src-tauri/dev-icon.svg` and used to
generate the standard Tauri icon set under `src-tauri/icons/`, including the
required 512px `icon.png`, platform ICO/ICNS files, and platform-size assets.

With Cargo 1.98.1 and rustc 1.98.1 from `/home/bizon/.cargo/bin`, native
Tauri compilation now completes and starts `target/debug/ava-desktop` against
the normal Desktop Vite frontend. The available automated UI surface could
not attach to the native GTK/WebKit window, so browser-style native editor,
resize, shortcut, and console inspection remain unobservable in this host.
The Web runtime and automated remount coverage continue to verify the shared
editor and AVA-owned document state behavior.

`./scripts/test_all.sh` passes after the packaging fix: 108 backend tests and
164 frontend tests, plus Ruff, mypy, TypeScript, and Python client checks.
`./scripts/build_all.sh` passes for both Web and Desktop Vite builds. The
only build diagnostic is Vite's existing chunk-size warning.

### Status

`STEP 13 NOT COMPLETE`

Native binary compilation and process launch pass, but native-window visual
interaction, resize, keyboard, and console verification cannot be observed
through the available host automation surface.

---

## Step 14 — Basic Document Operations

The shared `DocumentProvider` now owns create, select, rename, save, and
close operations for the in-memory document collection. New documents receive
stable AVA IDs, serializable empty HTML content, a collision-avoiding untitled
title, clean state, and active selection. Rename marks the document dirty
without changing its identity or content. Save accepts the current in-memory
state as clean; it does not persist past refresh or restart. Closing a dirty
document asks for explicit confirmation before discarding it.

`DocumentWorkspace` now includes a responsive document list, active-document
state, New, Rename, Save, and Close controls. Tiptap receives only the active
AVA document's content and changes only that document. The Web runtime
verified creation, dirty transition, save-to-clean transition, and switching
between independently held document contents.

Document-core now has 9 tests covering document-model behavior, operation
isolation, rename/save semantics, active-document reassignment, the empty
collection state, adapter conversion, and workspace/remount behavior. Web and
Desktop Vite builds pass.

### Step 14 validation remediation

`scripts/test_all.sh` previously used the backend Python interpreter for the
Python client and only compiled client source. The client owns a separate
virtual environment and declares its development tools through
`clients/python/pyproject.toml`. The harness now runs client pytest, Ruff, and
mypy through `clients/python/.venv/bin/python`. The stale client environment
was Python 3.11 despite the package requiring Python 3.12+, so it was
recreated with Python 3.12 and the declared `.[dev]` extras. Ruff and mypy are
now declared development dependencies, and the client includes a contract
model test.

Final automated validation passes: backend 108 tests, frontend 167 tests
(contracts 5, ui-core 20, api-client 17, document-core 9, agent-ui 112,
workspace 4), and Python client 1 test. Ruff and mypy pass for both Python
projects. `pnpm -r --if-present lint` is the canonical current TypeScript
validation command and runs `tsc --noEmit` across the frontend workspace.
Web and Desktop Vite builds pass with only Vite's informational chunk-size
warning.
