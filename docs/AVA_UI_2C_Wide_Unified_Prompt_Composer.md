# UI-2C — Wide Unified Prompt Composer

**Status: production implementation complete.** The shared production `PromptComposer` now uses a wide unified surface in Web and Tauri Desktop. The four existing execution settings remain independent and are available from a compact contextual popover. UI-3 has not started.

## Previous and new layout

The previous composer showed Profile, Runtime, Model, and Workspace as a permanent selector grid below a narrow, separate text box. The new composer is one `rounded-3xl` card surface with an integrated transparent multiline input, a compact execution-summary control in the lower action row, and a circular Send/Stop action on the right. There is no attachment Plus action because the current composer has no supported attachment action to expose.

Production ownership remains in [`PromptComposer.tsx`](../frontend/packages/agent-ui/src/components/PromptComposer.tsx). The same `@ava/workspace` chat and composer are mounted by Web and Desktop. Prompt submit, Enter/Shift+Enter, controlled and local draft handling, disabled states, run state, and cancel callbacks are preserved.

## Width and geometry

`AppWorkspace` gives the bottom composer wrapper `w-full max-w-[90rem] mx-auto box-border` with horizontal padding of 12px below `sm`, 16px from `sm`, and 24px from `lg`. The 90rem cap includes padding and centers only on wider canvases. The composer itself fills that padded wrapper; it has no narrow form-card maximum width. The Tauri host adds no separate composer sizing rule.

Live Web measurements with the conversation sidebar open:

| Viewport | Chat canvas | Composer | Canvas side margins |
| ---: | ---: | ---: | ---: |
| 1024px | 751px | 703px | 24px each |
| 1440px | 1167px | 1119px | 24px each |
| 1920px | 1647px | 1392px | 128px each, from the centered 1440px capped wrapper |

At the default 590px in-app browser width, the sidebar remains distinct and the composer keeps narrow-screen breathing room. The composer shell and its textarea now both use border-box sizing; the textarea stays within the pill instead of extending past the shell.

## Controls and behavior

The lower-left execution summary uses the resolved model name, falling back to the existing Application default/custom summary. It truncates long text and exposes the complete summary as an accessible name and native title. Opening the shared `@ava/ui-core` non-modal Popover reveals a compact 2×2 set of Profile, Runtime, Model, and Workspace selectors using the existing native Select controls. Their current values, updates, defaults, and project inheritance remain unchanged. Escape and outside pointer close the popover; Escape restores focus to its trigger.

The composer uses semantic `card`, `card-foreground`, `foreground`, `muted-foreground`, `border`, and `ring` tokens. The textarea is borderless with a transparent background; focus highlights the whole rounded shell with a subtle semantic ring. Dark mode renders an integrated dark surface and readable light text. Light mode renders the semantic light surface and dark text. System mode follows the resolved operating-system appearance. The shared execution trigger stays black with white text in Dark mode. The Archived control stays black with white text in Dark mode whether selected or not; the selected state remains discernible through its outline.

Dark-mode contrast follow-ups requested during acceptance also keep both Active/Archived segments black with white labels in either selected state, use compact gray semantic pills for the Documents Rename/Save/Close actions, remove formatting-toolbar separators, replace Undo/Redo text with Lucide icons, and render formatting controls and model capability checkbox labels with the resolved light foreground. The underlying document and model actions remain unchanged.

Send uses the shared circular Lucide ArrowUp IconButton. While a run is starting, stopping, or active, the existing disabled/status and Stop behavior remains in place using the Lucide Square icon. Draft-preservation, execution selector, keyboard, submission, and stop behavior are covered by agent-ui and workspace tests. No backend, API, or migration behavior changed.

## Visual and native acceptance

Web Dark, Light, and System were inspected in the live Chat route. The System preference was restored after Light and Dark checks; it resolves to Dark in this environment. Narrow, standard, and wide desktop composer widths were measured in the browser. The compact settings trigger, Dark Archived control, empty/new-chat composer, and existing sidebar data were inspected. An attempt to open a database-backed conversation highlighted its row but did not change the Chat panel during this visual pass, so existing-transcript rendering is not claimed as a new visual acceptance result; selection and existing conversation loading remain covered by the existing workspace suite.

The Tauri release executable and Linux DEB/RPM bundles build from the same shared frontend. The computer-use surface reports no native application windows (`apps: []`), so the release window could not be opened or visually certified in this session. AppImage was excluded from the requested DEB/RPM bundle command; its runtime remains unavailable on hosts without `/dev/fuse`.

Screenshots were captured in the live browser tool for visual inspection, but that tool returns transient image output and does not provide a local file export API. Therefore no PNG files could be saved under `docs/ui2c-evidence/`; the captured screenshots are represented in the task's visual inspection, not as repository files. The browser's viewport override was reset and the original System appearance preference restored.

## Validation

`pnpm -r test` passed after the composer border-box correction: Contracts 42, API Client 112, UI Core 71, Agent UI 301, Settings Core 212, Document Core 70, Workspace 215, and Desktop 11 tests; 6 existing workspace integration tests remain skipped. A final targeted workspace suite was also run for the Dark Archived styling change. Recursive TypeScript/lint checks passed.

Web and Desktop Vite production builds passed at 1,003.71 kB JavaScript (305.58 kB gzip), with the existing warning for chunks over 500 kB. Compared with the UI-2A baseline of 998.33 kB (304.18 kB gzip), those shared bundles are up 5.38 kB (1.40 kB gzip); no bundle optimization was attempted. Tauri's packaging build emitted the same 1,003.71 kB JavaScript (305.58 kB gzip). The Tauri release build produced:

- Executable: `frontend/apps/desktop/src-tauri/target/release/ava-desktop`
- DEB: `frontend/apps/desktop/src-tauri/target/release/bundle/deb/AVA Desktop_0.1.0_amd64.deb`
- RPM: `frontend/apps/desktop/src-tauri/target/release/bundle/rpm/AVA Desktop-0.1.0-1.x86_64.rpm`
- AppImage: not built in the DEB/RPM command.

No backend, API, or migration files were changed. UI-2A and UI-2 documentation now point to this completed implementation; `CONTEXT.md` records its durable layout and execution-settings boundary.
