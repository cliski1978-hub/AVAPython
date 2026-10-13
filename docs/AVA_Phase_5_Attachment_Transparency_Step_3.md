# Phase 5 extension — Conversation Attachment Transparency, Step 3

Step 3 exposes the existing extraction, inclusion, token, and historical-content
facts. Steps 1/2 backend extraction, ownership, prompt order, execution selection,
whole-file budgeting, compaction, and snapshot persistence are unchanged.

## Conversation UI and current draft

The compact attachment chips retain filename, stored size, and removal actions.
Their status comes from the existing backend context-preview result, matched by
attachment ID. Keyboard-focusable shared tooltips provide full explanations:

| Backend result | Prospective chip status | Explanation |
| --- | --- | --- |
| Included | Ready for context | Full extracted text fits the current preview; checked again at run start. |
| Unsupported | Stored · text unsupported | Text context is unsupported; the file remains stored and is not represented as corrupt. |
| Extraction failed | Stored · extraction failed | AVA could not extract text; raw error messages/storage details are not rendered. |
| Context limit | Stored · context limit | The complete file does not fit and is excluded without truncation. |
| Not checked | Stored · context not checked | Draft a message to obtain an authoritative readiness estimate. |

No browser decoding, extension/MIME classifier, tokenizer, or token estimator
was added. Before a meaningful draft exists, the UI reports that context has
not been checked rather than claiming a stored file is readable or included.
During preview it shows Checking. Non-included preview outcomes also have
small inline explanations below the chips; there is no per-file modal.

The misleading Inspector sentence that attachments never enter run prompts was
removed. A frontend TypeScript/TSX source search found no remaining equivalent
message. The composer retains the accurate conditional statement from Step 2:
supported text is included when it fits; run metadata records inclusion.

The Prompt Window Indicator now shows the backend's final estimated input,
input budget, included/not-included file count, and authoritative
`attachment_context_tokens` with count accuracy. It does not label the larger
preparation/compaction demand as the final input actually admitted to the model.
Inspector draft estimates are explicitly labeled **Current draft estimate**,
separate from a selected historical run's captured metadata.

Backend metadata does not provide every system/Project/history token subtotal,
so the UI does not invent that breakdown. Existing window, input, output reserve,
history omission, and summary fields remain visible where captured; attachment
contribution is the additional available subtotal.

## Preview ownership and refresh

`useContextWindowPreview` reuses the existing typed `/runs/context-preview`
client and 350 ms draft debounce. Its result is keyed to API client, draft,
Conversation, explicit execution selection, and a refresh key containing the
current file inventory, Project/Folder identity, Project default display state,
route, and scope-assignment dialog lifecycle.
Attachment upload/removal, model change, return from Settings/Projects, and app
focus invalidate the old result. Backend resolution remains authoritative for
application/Project inheritance. No default model is converted to a run override.

Changed inputs immediately hide the previous result, including previous context
exclusions. Cancellation guards discard older responses and errors. A model or
Conversation switch cannot retain a permanent exclusion from the old budget.
No synthetic empty-draft prompt is sent to obtain a speculative estimate.

## Run Inspector

Prompts and Run show **Conversation Attachments** using only the selected run's
`snapshot.attachments`. Each item exposes filename, logical attachment ID,
content type, extraction/inclusion outcome, Included Yes/No, token contribution
or whole-file tokens required, count accuracy, and a safe explanation. All four
outcomes are represented, including unsupported and extraction failures.

An explicit empty snapshot list means no attachment context was used. A missing
legacy field means attachment metadata was not captured; the Inspector does not
substitute the current Conversation inventory. Required-prompt failure is
distinguished from a file-size failure, and an uncounted file cost is not
presented as a fabricated zero-token requirement.

Included text is available under **View Context Sent**, collapsed by default.
Full text is mounted only after expansion inside the existing bounded,
scrollable monospace block. It is displayed as React text, never interpreted as
HTML, and the captured data is not truncated. Existing copy-button behavior is
reused for logical ID, exact extracted content, and the full attachment block
found in the captured normalized request. No live source download is required.

Prompts places Conversation Attachments separately between recent history and
the current user message. File messages are excluded from the history display
using captured identity-bearing attachment boundaries; durable message IDs keep
a quoted file block in ordinary history distinct. Optional captured summary
content remains separate. Request continues to show the recorded normalized and
runtime requests in their original order, without constructing another request.
Existing Conversation Compaction details remain distinct from attachment
processing and explain that files are not summarized by that service.

Run/Conversation identity guards immediately hide inspection data that does not
match the current selection. Cancelled request results are ignored; active-run
inspection polls do not overlap or restart solely because the run inventory
array was refreshed. An explicit historical selection remains historical even
when the composer has an unsent draft. Switching runs resets expanded file views.

## Files changed

- `frontend/packages/agent-ui/src/lib/attachmentContextPresentation.ts` — safe shared outcome labels/count summary.
- `frontend/packages/agent-ui/src/index.ts` — public presentation helpers and existing attachment metadata type.
- `frontend/packages/agent-ui/src/components/PromptComposer.tsx` — compact authoritative statuses/tooltips and explanations.
- `frontend/packages/agent-ui/src/components/prompt-composer.test.tsx` — prospective status and safe-message tests.
- `frontend/packages/workspace/src/useContextWindowPreview.ts` — current-input-scoped preview/refresh hook.
- `frontend/packages/workspace/src/AppWorkspace.tsx` — preview dependencies and token/count wiring.
- `frontend/packages/workspace/src/RunInspector.tsx` — historical attachment section/content/copy, layer separation, and selection/poll guards.
- `frontend/packages/workspace/src/attachment-inspector.test.tsx` — snapshot, status, history, theme, token, and race regressions.
- `frontend/packages/workspace/src/context-attachment-preview.test.tsx` — prospective invalidation and stale-response regression.
- `frontend/packages/workspace/src/RunInspector.test.tsx` — accurate Conversation IDs, supplied preview props, and exact multiline assertions in existing fixtures.
- This record.

No backend production file, extraction policy, runtime adapter, API endpoint,
budget calculation, schema, package dependency, or Project File behavior was
changed. The checkout already contains unrelated changes; its full Git diff is
not this step's diff.

## Validation

| Check | Result |
| --- | --- |
| Inspector/preview focused tests | 15 passed: 10 new Inspector cases, 1 new preview case, 4 updated existing Inspector cases. |
| Composer focused tests | 17 passed, including 2 new status/safety cases. |
| Agent UI full suite | 316 passed. |
| Workspace full suite | 252 passed, 2 existing failures, 6 opt-in live tests skipped. |
| Desktop shell tests | 11 passed. |
| Agent UI TypeScript | Passed. |
| Workspace TypeScript | Existing Settings model-contract errors plus the existing AppWorkspace test callback typing error. No new feature-source error reported. |
| Web/Desktop production builds | Blocked before Vite by the existing Settings `context_window_tokens` contract mismatch. No green production build is claimed. |
| `git diff --check` | Passed. |

The two remaining workspace failures are the existing Inspector-width resize
assertion and cross-ApiClient connectivity test. They were present before this
step. Existing Inspector tests now use valid API-shaped IDs and supplied budget
props; exact multiline contents are checked in their actual text containers.
No unrelated failure was suppressed. Backend full/static checks were not
repeated for a frontend-only step; earlier Steps 1/2 record their existing
backend architecture/type failures.

The new tests cover included/unsupported/failed/context-excluded states; safe
diagnostics; exact content mounted on expansion; captured Request ordering;
files added/deleted between historical runs; stale Conversation/run responses;
an explicit historical selection with a current draft; authoritative aggregate
tokens independent of per-file fixtures; required-input failure with unavailable
file counts; slow active-run polling; Light/Dark/System appearance; and preview
refresh after file/model/Conversation/focus changes.

## Live Web/Desktop frontend checks

A disposable native backend on port 8001 used the existing local Ollama
`qwen2.5-coder:7b`, SQLite metadata, local attachment bytes, and a 2,048-token
configured model window. Web ran on 5175; the Desktop package's Vite frontend
ran on 5176 against the same backend. No user database/settings were changed.

Web uploaded `attachment-test.md` containing **AVA-ATTACHMENT-RUN-8426**. The
draft chip showed Ready for context, and both composer and Inspector preview
showed its **80 estimated tokens**. The real model returned the phrase. The
Inspector showed Included, Succeeded extraction, logical ID, MIME type, and
80 tokens; expansion displayed the captured marker, and the copy action
returned the exact captured text. Request showed the file block in both the
normalized and Native runtime request before the current user message.

A later run used the same file while recording an image as Unsupported, an
invalid UTF-8 text file as Extraction failed, and a 20,000-byte Markdown file as
Excluded · context limit with **5,072 estimated tokens required**. All outcomes
were visible together. After source deletion, the next run omitted that file.
Selecting the earlier run still displayed its exact captured file and 80-token
contribution. The later unsupported/oversized/failed files were absent from the
first run, even while present in the current Conversation.

Light, Dark, and System were exercised through the shared appearance control
and captured visually. The original System selection was restored. The Desktop
frontend opened the same historical run and displayed the retained file metadata
after deletion. This is Desktop frontend/shared-shell validation; a native Tauri
window was not independently exercised during this step.

Evidence remains at `/tmp/ava-step3-light.png`, `/tmp/ava-step3-dark.png`,
`/tmp/ava-step3-system.png`, `/tmp/ava-step3-historical.png`, and
`/tmp/ava-step3-desktop.png`. Validation browser tabs, servers, and disposable
data were cleaned up after the smoke test.

## Limits

Stored attachments are not declared context-ready before a draft preview. Each
preview and run resolves current backend state independently; an estimate is
not a promise of later inclusion. Historical status/content remains immutable
and source-independent. No RAG, embeddings, indexing, OCR, chunk retrieval,
Project File automatic context, or attachment summarization was added.
