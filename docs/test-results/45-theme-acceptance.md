# 45 — Theme Acceptance

Date: 2026-10-12  
Environment: AVA Web at `http://127.0.0.1:5173/`, 1280×720 in-app browser; local backend restored with `scripts/dev_backend.sh` after it was found unavailable.

## Result

**#45 Theme Acceptance — PASS (Web); Desktop UNVERIFIED.** Light, Dark, and System-light were checked in the live Web app. System-dark behavior is covered by the AppearanceProvider test, which checks both dark and light media-preference transitions. One real Settings error-alert contrast defect was found and corrected with the existing destructive semantic tokens. The expanded Tauri E2E suite now defines Light/Dark/System semantic-surface assertions, but it did not run because no usable display or `xvfb-run` is available here.

## Theme and surface checks

| Surface | Result | Evidence |
|---|---|---|
| Appearance selector | PASS | Settings exposes System, Light, and Dark. Each mode updated the root theme. The selected mode stayed in effect while moving between Chat, Projects, and Settings. |
| Light | PASS | Live Settings, CORE Prompts, project files, project detail, and chat-related surfaces were readable. CORE Prompt cards rendered white with dark foreground and visible borders. |
| Dark | PASS | Live Dark rendering showed readable conversation messages and errors, sidebar hierarchy, composer and attachment chip, Inspector panels, and CORE Prompt cards. Prompt cards used `bg-card text-card-foreground border-border` and rendered with a dark surface and light text. |
| System-light | PASS | With AVA set to System, the browser reported a light preference; the root dark class was absent and CORE Prompt cards matched Light. System mode persisted across navigation and refresh. |
| System-dark | PASS with environment limitation | The in-app browser continued reporting `prefers-color-scheme: light` even after the host preference was set to dark, so a live System-dark transition could not be driven here. The AppearanceProvider test simulates dark and then light changes while System remains selected and verifies the root dark class follows both directions. Live Dark rendering uses the same semantic theme classes. |
| CORE Prompt regression | PASS | Profile and assignment cards remained readable in Light and Dark. Live Dark computed card colors were `rgb(22, 26, 29)` / `rgb(235, 237, 240)`; Light/System-light were white / `rgb(36, 41, 46)`. Titles, descriptions, metadata, assignment controls, and edit/disable/delete actions were legible. |
| Conversation and composer | PASS | A conversation with long messages, an error, and an attachment was inspected in Dark. Message roles were distinct, long text wrapped, the attachment chip and context-status text were readable, and the composer/send/attachment controls were visible. Historical Inspector data showed the attachment as included in run context. |
| Sidebar | PASS | Selected and archived controls, folders, project rows, and action affordances were inspected in Dark. Keyboard resizing moved the sidebar through narrow (240 px) and wide (368 px) layouts, then restored the initial 272 px width. The page had no horizontal overflow. |
| Projects and files | PASS | Project overview and file table were inspected in Light, including file metadata and download/delete controls. Dark Project A, instructions, settings, and file surfaces were also inspected earlier in this acceptance session; text and controls remained readable. |
| Conversation attachments | PASS | The conversation attachment chip and historical run-context status were readable in Dark; Inspector reported one included attachment and successful text extraction. Unsupported-file and excluded-context warning variants were not separately triggered in this pass. |
| Run Inspector | PASS | A historical run with prompts, request/response data, events, attachment context, and compaction details was available. The Dark screenshot showed readable tabs, JSON/content panels, metadata, and copy controls. |
| Context indicator | PASS for inspected states | The composer exposed its draft-estimate hint, and the historical Inspector displayed estimated context usage and `Not needed` compaction status. A high-usage or active-compaction state was not forced during this theme pass. |
| Settings | PASS | Appearance and CORE Prompts were checked in Light, Dark, and System-light. The browser also recovered from a temporary backend outage using the CORE Prompts retry control. Other settings sections were not separately theme-stressed in this pass. |
| Dialogs, menus, and focus | PASS for inspected states | The CORE Prompt creation dialog and edit dialog were inspected in Light, and select controls and assignment menus were visible in both Light and Dark. Keyboard interaction on the sidebar resize separator worked and returned to its original width. A dedicated focus-ring sweep across every control was not performed. |
| Errors and warnings | PASS after correction | Dark conversation errors remained readable. The backend-unavailable CORE Prompts state showed a clear retry action in System-light and recovered after backend restart. Settings modal validation errors now use the semantic destructive surface/foreground pair. |
| Layout and console | PASS | At a 1280 px viewport, document width equaled viewport width (no horizontal overflow). No console errors were captured after backend recovery. Expected failed requests while the backend was unavailable were treated as outage behavior. |
| Refresh and persistence | PASS | System mode remained selected after a full Web refresh and across Chat, Projects, and Settings navigation. The host OS preference was restored to its original dark value after checking; the browser still reports light for `matchMedia`. |
| Desktop | UNVERIFIED | No native Tauri window was available through the current computer-use session, so no Desktop visual result is claimed. |

## Contrast finding and correction

The shared Settings modal used fixed `#dc2626` text on `#fef2f2` for validation and submit errors. That pair measured **4.41:1** for 13 px text, below the 4.5:1 WCAG AA threshold, and kept a light alert panel in Dark mode. The alert now uses AVA's `bg-destructive text-destructive-foreground` tokens. The existing destructive color with its white foreground provides approximately **4.8:1** contrast and follows the active theme token system. No layout or dialog behavior changed.

The targeted audit also found fixed black/white colors on the selected Active/Archived conversation-view controls. They stayed legible in the checked Dark sidebar and Light surfaces, so they were left unchanged. CORE Prompt cards remain semantic-token based.

Files changed for this acceptance:

- `frontend/packages/settings-core/src/modal/SettingsModal.tsx` — use destructive semantic surface and foreground for the alert.
- `frontend/packages/settings-core/src/modal/settings-modal.test.tsx` — assert the alert uses semantic colors and has no inline color override.
- `frontend/packages/ui-core/src/appearance/AppearanceProvider.test.tsx` — verify System mode follows dark and light preference changes.
- `docs/test-results/45-theme-acceptance.md` — this report.

## Automated tests

Focused tests passed:

| Package | Tests |
|---|---:|
| `@ava/ui-core` — appearance/theme/status/icon | 19 |
| `@ava/workspace` — attachment Inspector/sidebar/projects | 54 |
| `@ava/settings-core` — Settings modal/prompts/workspace/inventory | 59 |
| `@ava/agent-ui` — composer | 17 |
| `@ava/desktop` — shell composition | 11 |
| **Total** | **160 passed** |

The Desktop test result verifies shell composition only, not native visual appearance. No unrelated application changes were made.

## Final status

**#45 Theme Acceptance — PASS (Web); Desktop remains UNVERIFIED.** The desktop theme assertions exist in the native E2E suite but need a GUI execution. System-dark was validated through the simulated media-preference test because the in-app browser did not expose the host's dark preference.
