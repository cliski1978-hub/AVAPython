# 42 — Web Acceptance

Date: 2026-10-12  
Environment: AVA Web at `http://127.0.0.1:5173/`, local browser session, backend connected

## Result

**#42 Web Acceptance — PASS.** The disposable conversation was permanently deleted and stayed deleted after refresh; Settings showed section-specific errors while the backend was down and recovered without restarting Vite. The remaining CORE Prompt card contrast defect is fixed with AVA semantic theme tokens and verified in Light, Dark, and System-dark modes. System-light resolution and theme-mode behavior are covered by the AppearanceProvider media-preference test.

## Browser checks

| Area | Result | Evidence |
|---|---|---|
| Create and rename conversation | Pass | Created and renamed `R42 Web Acceptance Test`; heading and sidebar reflected the new name. |
| Archive and restore conversation | Pass | Archived and restored the test conversation; both status messages appeared and it returned to Active. |
| Permanent deletion | Pass | Confirmed the irreversible delete for only `R42 Web Acceptance Test` through AVA's dialog. It disappeared from Project A and conversation search, and remained absent after refresh. It could not be reopened. |
| Send/receive and stop | Pass | `#42-OK.` round-trip succeeded. Stop control ended a long response and displayed `Response stopped` with `Retry response`. |
| Folders | Pass | Created `R42 Smoke Folder`, moved the test conversation into it, then moved it to Ungrouped; Folder became empty. |
| Projects and conversation assignment | Pass | Created `R42 Project A` and `R42 Project B`; moved/assigned conversations across Project A, Project B, Folder, and Ungrouped. |
| Project instructions | Pass | A Project A run included `R42-A-INSTRUCTIONS`; Inspector showed the Project Instructions section and marker. |
| Project execution defaults | Pass | Run Inspector recorded model `qwen25-coder-7b`, runtime `native`, provider connection `ollama-local`, and `project` as model/runtime source. |
| Project files | Pass | `r42-project-a.txt` remained in Project A after navigating away and back. Duplicate upload showed an explicit already-exists error and did not add another row. Project B showed no files. |
| Conversation attachments | Pass | `r42-chat-attachment.txt` stored, survived page refresh, duplicate upload showed an explicit error, and remove/re-upload succeeded. Inspector recorded extraction succeeded, inclusion `Yes`, and 89 estimated tokens. A run returned the fixture marker `attachment-context-test`. |
| CORE prompts | Pass | Inspector showed global `AVA PRIME DIRECTIVES` in both an ungrouped run and a Project run. Project runs also included Project Instructions. |
| Run Inspector | Pass | Prompts, Request, Response, Run, and Events views all displayed for historical runs, including normalized/runtime request and response, run resolution, attachment details, context window, and event sequence. |
| Context window / compaction | Pass | Draft estimate resolved to `429 estimated tokens / 31,744 available`, with one included attachment and 89 context tokens. Inspector displayed the run context window and `Not needed` compaction state. |
| Provider/model failure and retry | Pass | Selecting configured invalid model `bb1` produced `Model unavailable`, explanatory text, and Retry/Model Settings controls; the spinner cleared. Restoring Project default and retrying returned `R42-FAIL-PROBE`. |
| Settings outage and recovery | Pass | Stopped only AVA's uvicorn backend (PID 70405); Vite stayed up. Models, Runtimes, Providers, and CORE Prompts each exited loading with a user-facing error and a section-specific Retry control. Rapid switches kept the selected section authoritative and did not show another section's data. Restarted with `scripts/dev_backend.sh`; switching back to each section reloaded its normal data without restarting the frontend. CORE Prompts also recovered through its Retry control. |
| Navigation and refresh | Pass | Settings → Chat retained the selected conversation; page refresh briefly showed loading and restored `R42 Web Acceptance Test`, messages, and attachment. |
| Themes | Pass | CORE Prompt cards use `bg-card`, `text-card-foreground`, `border-border`, and `text-muted-foreground`. Live Light rendering measured white cards with dark text; Dark and System-dark rendered dark cards with light text and readable muted metadata. System mode followed the dark OS preference and matched Dark. System-light resolution is covered by the AppearanceProvider test with a light media preference; all modes retain the same semantic card classes. |
| Layout and console | Pass | Checked during the outage and after recovery at 935×1190: document width matched viewport width, with no horizontal overflow. No captured browser console errors and no stuck global loading state. Expected refused backend requests during the outage are not counted as regressions. |

## Final status matrix

| Area | Result |
|---|---|
| Conversation lifecycle | PASS |
| Permanent deletion | PASS |
| Folders / Projects | PASS |
| Execution defaults | PASS |
| Project instructions | PASS |
| Files / attachments | PASS |
| CORE prompts | PASS |
| Run Inspector | PASS |
| Context / compaction | PASS |
| Failure / retry | PASS |
| Backend outage recovery | PASS |
| Navigation / refresh | PASS |
| Light / Dark / System | PASS |
| Layout / console | PASS |

## Test fixtures

- Conversation: `R42 Web Acceptance Test` (`e1593b1f-b918-46a7-9bd1-d003f319862e`) — permanently deleted; absent after refresh.
- Folder: `R42 Smoke Folder`
- Projects: `R42 Project A` (`17214ce4-4d4e-4afe-aefd-580cfcdb5464`), `R42 Project B`
- Project file: `r42-project-a.txt`
- Conversation attachment: `r42-chat-attachment.txt` (`7a2039cd-1819-44d3-aff0-1ea0c0aab5fb` after retry upload)

Backend outage verification: backend stopped cleanly, port 8000 refused connections, and port 5173 continued returning HTTP 200. Backend restarted with the repository's normal development script; ports 8000 and 5173 both returned HTTP 200 afterward.

Deletion verification: the permanent delete confirmation was accepted for only the named disposable conversation. After refresh, `R42 Web Acceptance Test` was absent from Project A and conversation search and could not be reopened.

Settings outage verification: while port 8000 was unavailable, Models, Runtimes, Providers, and System Prompts each replaced loading with a visible error and retry control. Rapid switching left the current section selected and did not show stale data from another section. After backend restart, each section loaded its configured data again through section retry/re-entry without a frontend restart. No fatal console errors, horizontal overflow, or stuck global loading state were observed; expected outage request failures were excluded.

## Focused CORE Prompt contrast correction

The cards used the static light `defaultTheme.colors.surface` and `defaultTheme.colors.border` inline while inheriting foreground text from the active dark theme. Replaced only card surface, text, border, and metadata colors with AVA semantic classes in both prompt profile cards and scoped assignment cards. Layout and prompt controls are unchanged. Live browser checks in Dark/System-dark measured 14.93:1 card title/body contrast; secondary and destructive button labels measured 16.98:1 and 4.83:1 respectively. Muted metadata used the dark-theme `muted-foreground` token. Light mode remained white with dark text. No horizontal overflow or console errors were observed on the checked page.

Focused tests: `system-prompts.test.tsx` passed (19 tests), including assertions that both card types use semantic surface/foreground/border/metadata classes and no inline card background. `AppearanceProvider.test.tsx` passed (8 tests), including system-light and system-dark media preference behavior. `pnpm --filter @ava/settings-core lint` remains blocked by existing TypeScript errors in `src/models/ModelConfigurationEditor.tsx` (`context_window_tokens` is absent from `ModelConfigurationResponse` and `CreateModelConfigurationRequest`); these errors are outside the changed files.
