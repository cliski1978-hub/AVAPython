# Phase 5 extension — Conversation Attachment Run Context, Step 2

Step 2 is implemented and verified against the actual NativeRuntime/provider
input and a live local model. Step 3 Inspector/UI polish has not started.

## Run path and extraction ownership

The existing `ContextConstructionService` receives an optional
`ConversationAttachmentContextPort`. Production composition supplies
`ConversationAttachmentContextService`, which enumerates only the active
Conversation's attachment inventory in repository insertion order and calls
Step 1's `AttachmentExtractionService.extract(conversation_id, attachment_id)`
once per attachment. It does not duplicate storage reads, ownership validation,
file-type classification, or decoding. An attachment deleted during preparation
becomes an explicit unavailable/extraction-failed item.

The resulting neutral `RunContext.attachments` contains extraction candidates
and explicit unsupported/failed outcomes before `RunService` forwards the
context through `AgentPort`. The shared native agent's existing selection path
resolves runtime/model, root/CORE/Project instructions, and the actual model's
context window. Existing conversation compaction runs before final windowing.
`ContextWindowManager.fit_with_attachments` then resolves whole-file inclusion
before the selected runtime receives its context. Neither NativeRuntime nor
OpenHands queries attachments or makes attachment-budget decisions.

There is no new API, schema migration, extraction cache, persistence table,
provider dependency, RAG, chunking, OCR, or Project File integration.

## Prompt representation and order

`AttachmentContextItem` contains attachment ID, filename, media type, status,
included flag, optional exact text, token estimate/accuracy, and safe diagnostic
code/message. No storage key or filesystem path crosses this boundary.
`extracted` is an internal candidate state. Published final outcomes are:

```text
included
unsupported
extraction_failed
excluded_context_limit
```

The final normalized request keeps the existing instruction precedence:

```text
AVA Root System
→ Resolved CORE prompts
→ Project Instructions, when applicable
→ Conversation Summary, when applicable
→ Recent Conversation History
→ Included Conversation Attachments
→ Current User Message
```

Each attachment is its own **user-role contextual message**, not a system
message. Its AVA-owned format labels the content as untrusted contextual data,
JSON-quotes filename/media-type metadata, and uses explicit BEGIN/END content
markers with attachment identity. Authored file text is preserved inside those
markers. Multiple files have separate boundaries. Native translates the same
neutral sequence into provider messages; OpenHands' existing transcript adapter
keeps attachment blocks in its user input, outside its AVA system-prompt suffix.

## Budget and inclusion policy

The existing selected-model resolution remains explicit run override → Project
default → application default → bootstrap. Its configured context-window value
is constrained by the provider's reported maximum, as before. No frontend model
selection becomes budget authority.

The existing estimator and output-reserve policy are reused. Each successful
attachment's token count includes its complete rendered contextual message and
framing, using the same selected-model identity and estimated accuracy as the
other messages. There is no attachment-specific tokenizer or separate budget.

The manager first applies existing whole-turn history windowing to the base
request. Required instructions/current input that cannot fit retain the existing
oversize failure; that condition is checked before a summarizer/provider call.
Attachments are optional and cannot turn that base failure into a file error.

After existing compaction and history fitting, attachments consume remaining
input budget in stable repository order. A complete file either fits or is
excluded; no substring, first-page, partial file, or silent truncation is sent.
An excluded large file does not stop a later smaller file from fitting. An
unknown model limit preserves existing unbounded compatibility behavior.

`attachment_context_tokens` counts included files only; excluded files retain
their attempted whole-file token cost in their individual metadata. The total
request estimate includes system/CORE/Project layers, summary/history, admitted
attachment messages, and current input, with output tokens reserved separately.
The existing context-preview endpoint uses this policy for unsent drafts too.

Compaction still selects complete old chat turns from `RunContext.messages`.
Attachments live in a separate field and are never sent to the summary-generation
request. Their contextual cost participates in pressure calculations; existing
summary-generation target/eligibility rules are preserved. If compaction cannot
reach its existing target, ordinary history fitting and explicit whole-file
exclusion still produce the final decision. No attachment summarization occurs.

Unsupported or failed extraction does not fail a safe run. It contributes no
attachment text/tokens and stays discoverable in run metadata. All-unsupported
and all-failed inventories are explicitly tested.

## Historical facts and API contracts

`RunInspectionSnapshot.attachments` records every file's final inclusion outcome,
identity, filename/media type, estimated token count, and diagnostics. Included
files preserve the exact extracted text used. The existing normalized request
also captures the delimited message actually dispatched. Context-window metadata
records the included token contribution and resolved model identity.

These facts use the existing run-owned JSON snapshot persistence (migration
0020); no live attachment read is needed to inspect a historical run. Deletion
affects later runs only. Tests remove the source file, reopen SQLite/local
storage, and verify that the original snapshot/text are unchanged. Project
movement changes applicable instructions while retaining Conversation attachment
identity and ownership. Project Files, including files with identical filenames,
remain outside this context path.

Shared TypeScript run-inspection/preview contracts mirror the additive metadata.
There is no new Inspector panel, file widget, or Step 3 interaction. The existing
composer notice was corrected because its previous statement that attachments
never enter runs became false.

## Files changed by this step

- `backend/src/ava/contracts/attachment_context.py` — neutral attachment item/status, formatting, and load port.
- `backend/src/ava/contracts/conversations.py` — context field and final/preview message placement.
- `backend/src/ava/contracts/run_inspection.py` — run-owned file facts and token contribution.
- `backend/src/ava/services/conversation_attachment_context_service.py` — Step 1 extraction coordination.
- `backend/src/ava/services/context_construction_service.py` — port consumption before AgentPort.
- `backend/src/ava/execution/context_window.py` — complete-file admission using the existing estimator/budget.
- `backend/src/ava/agents/adapters/native/native_agent.py` — final admission, preview parity, required-input guard, snapshots.
- `backend/src/ava/api/app.py` — application-service composition.
- `backend/tests/test_attachment_run_context.py` — new runtime/ownership/accounting/history regressions.
- `backend/tests/test_architecture.py` — permit only the additional neutral attachment contract in the pure window policy.
- `frontend/packages/contracts/src/runs.ts` — additive inspection/preview metadata types.
- `frontend/packages/agent-ui/src/components/PromptComposer.tsx` and its existing test — truthful notice text.
- This record.

The Step 1 extractor, RunService, and compaction implementation were not changed
by this step. The checkout already contains unrelated changes in several of
those files; its full Git diff is not this step's diff.

## Automated validation

| Check | Result |
| --- | --- |
| New attachment run-context tests | 28 passed across memory/SQLite metadata and local stored bytes. |
| Extraction, run-context, windowing, construction, compaction, inspection, NativeRuntime, persisted execution resolution, Project defaults | 261 passed. |
| Architecture suite | 123 passed, 4 existing failures: native adapter imports existing compaction service; persistence inventory lacks its context-summary expectation; existing runtime/service dependency guard; existing RunService list-query assertion. These same failures were verified before Step 2. |
| Backend Ruff, `src tests` | Passed. |
| Focused strict mypy | Passed for 6 extraction/context/contract/window production modules. |
| Full backend mypy | 13 existing errors in Settings, OpenHands request typing, compaction/summary repositories, deletion coordinator, and Conversation routes. The touched native snapshot construction now uses the accounting model directly. |
| Shared contracts | 42 tests passed; TypeScript check passed. |
| Agent UI | 314 tests passed; TypeScript check passed. |
| `git diff --check` | Passed. |

The new tests prove actual NativeRuntime → provider input contains
`AVA-ATTACHMENT-CONTEXT-7319`; preserve Markdown, JSON, CSV, UTF-8 text and
file boundaries; extract once per run; account for included tokens; exclude
complete oversized files; continue past oversized/unusable files; isolate
Conversation and Project File ownership; preserve deleted-file history after
reopen; use the actually selected model window; deliver already-budgeted items
to a runtime seam; keep attachment text out of summary generation; preserve
instruction order; and include files in unsent preview accounting.

Full canonical certification is not claimed. Step 1 already reproduced 25
unrelated full-backend failures and a full-run stall, plus workspace/frontend
contract failures; Step 2 uses focused validation and independently checks the
current architecture and backend types. No unrelated failure was suppressed or
fixed as part of attachment integration.

## Live browser/model validation

Disposable SQLite/local content on port 8001 and Web on port 5175 used Native
execution with the existing local Ollama `qwen2.5-coder:7b`. Only disposable
configuration/data were created. The configured model context window was 2,048
tokens: 1,536 input tokens and 512 reserved output tokens.

The browser created a Conversation, uploaded `attachment-test.md`, and asked
for its validation phrase. The real model returned **AVA-ATTACHMENT-RUN-8426**.
The run's stored file outcome was `included`, with 93 estimated attachment
tokens inside a 143-token normalized request. Browser refresh restored the
attachment from storage; the second question returned the same phrase and the
existing draft indicator showed increased context usage.

The backend was also restarted over the same disposable database/content root.
An unsupported image and 20,000-byte text file were uploaded. The next real run
still returned the phrase; metadata recorded `unsupported` and
`excluded_context_limit` respectively. The oversized file's full contextual
cost was 5,072 estimated tokens, and none of its text was truncated into the
normalized request.

Deleting `attachment-test.md` through the existing Conversation API removed it
from the next real run's file inventory. That run completed. Reading the prior
run's inspection afterward returned an identical snapshot with the captured
text and inclusion metadata intact.

Live evidence is saved at `/tmp/ava-step2-live-model.png`,
`/tmp/ava-step2-live-inspection.json`, and `/tmp/ava-step2-live-followup.json`.
Validation servers and disposable data were cleaned up after the smoke test.

## Remaining limits

Step 1's UTF-8 text/file-size support remains unchanged. Inclusion is whole-file
and deterministic; there is no semantic prioritization or retrieval. Historical
inspection retains included source text as a run fact, not as an extraction
cache. Preview requests may independently extract current attachments, but each
run extracts each attachment once. Existing summary policy and approximate token
estimates remain authoritative. Step 3 can present the shipped outcome/token
metadata without reconstructing historical file use from live attachments.
