# UI-2A — Shell Theme and Control Completion

**Status: implementation and Web acceptance complete; native visual acceptance remains unverified, so UI-2A is not certified complete. UI-3 has not started.** UI-2 established the shared shell structure. UI-2A closes the remaining shell theme gap: Chat's main canvas and composer now follow the active AVA appearance, shell-owned text uses semantic tokens, and legacy conversation controls use the shared control system where their existing behavior supports it.

## Why UI-2A was needed

The previous shell combined dark navigation with light-only Chat content and legacy controls. In Dark mode this left a bright canvas and composer beside dark chrome, and several labels and conversation titles still used fixed grey values. The certified palette was already correct; these surfaces needed to consume its semantic tokens.

Primary readable text uses `text-foreground`; supporting copy uses `text-muted-foreground`. The supplied `--foreground: 210 14% 93%` remains unchanged. No feature-specific theme constants, broad CSS reset, or `!important` overrides were added. A scoped audit of the migrated shell components found no remaining `text-black`, `text-gray-*`, `text-slate-*`, `bg-white`, hex, or fixed dark text color declarations. Remaining `hsl(var(--...))` values are semantic token reads for borders, status, error, and shadow treatments.

## Migrated surfaces

- The Chat workspace canvas, title header, empty state, message wrappers, composer surface, and app's no-selection state now use AVA background, foreground, card, border, destructive, and muted tokens. The empty state retains distinct empty/loading/error states.
- Shared sidebar chrome, Projects heading/expand/add affordances, conversation titles, Folder labels, Active/Archived selection, search, New Chat, and New Folder use semantic colors, Lucide icons, focus rings, and shared rounded Buttons/IconButtons/Input where appropriate. New Chat, folder operations, search, archive state, project actions, and dnd-kit ownership are unchanged.
- The Settings route frame, title, section tabs, and Appearance copy now follow semantic surfaces and text colors. Settings forms and their feature-owned record cards remain outside this phase.
- Suggestion prompts use shared outline-button styling while remaining inert as before. Message bubble layout and behavior are not redesigned; their legacy colors that affected readability now resolve from card/foreground/destructive tokens.
- The composer shell and textarea use semantic surfaces and foregrounds. Send uses the shared Lucide `ArrowUp` IconButton with the accessible name and tooltip “Send”; disabled and submit behavior are unchanged.
- Profile, Runtime, Model, and Workspace retain native `<select>` controls. Their labels, selected values, borders, backgrounds, focus rings, and disabled states now use semantic AVA styling with inherited color scheme. A trial replacement with Radix Select changed the selector interaction contract and broke workspace consumers/tests that use native option selection; it was removed to preserve execution resolution and native keyboard/value behavior. The dropdown values and callbacks are unchanged.
- The shared EmptyState and Modal primitives now use semantic foreground, surface, border, and focus tokens. The shell's existing Lucide controls inherit `currentColor`.

No legacy CSS rules needed an override. Tailwind Preflight remains disabled. Routes, provider lifetimes, loading/retry paths, streaming, execution defaults, search, archive, folder actions, and drag/drop behavior were not changed.

## Theme acceptance

Web was inspected at `/` in Light and Dark using the live preview, including the sidebar, New Chat/New Folder, search, Active/Archived, conversation and Project labels, empty state, composer, send control, and all four execution selectors. The Settings route frame/title/section tabs were also inspected in Dark. Light showed a clean light canvas and composer with dark primary text. Dark showed dark shell/canvas/composer surfaces; primary labels and title text were light, and selector values remained readable. The supplied dark foreground palette was not changed. The host System appearance resolved to Dark before testing. The appearance preference is restored to System (currently resolving to Dark) after the manual Light/Dark checks.

The Dark visual smoke inspected existing conversation and Project titles in the loaded sidebar and opened an existing conversation with its transcript; user and assistant message text remained readable. The Settings outer canvas, title, and section navigation also remained readable and dark, while its legacy provider record card remains feature-owned and outside this phase. Projects and Documents internals were not redesigned.

The native Tauri release build completed and its executable was started. This session exposes browser automation but no native window inventory or controls; the X11 window list is unavailable (`Cannot open display`). Therefore the release window could not be visually inspected in Light or Dark here. Native visual acceptance and native screenshots remain outstanding; the prior UI-2 captures are not represented as UI-2A evidence. No files are present under `docs/ui2a-evidence/` because this browser surface did not expose a local screenshot export.

## Validation

`pnpm -r test` passed across all 10 runnable workspace projects. Six live integration tests remain skipped by their existing configuration.

| Suite | Result |
| --- | --- |
| `@ava/ui-core` | 13 files, 67 tests passed |
| `@ava/desktop` | 1 file, 11 tests passed |
| `@ava/agent-ui` | 21 files, 299 tests passed |
| `@ava/workspace` | 15 passed, 2 skipped files; 211 passed, 6 skipped tests |
| `@ava/document-core` | 7 files, 70 tests passed |
| `@ava/settings-core` | 11 files, 211 tests passed |
| `@ava/api-client` | 14 files, 112 tests passed |
| `@ava/contracts` | 13 files, 42 tests passed |

`pnpm -r lint` passed, including TypeScript checks for Web and Desktop.

Production Web and Desktop Vite builds passed with the existing large-chunk warning. The final Tauri build produced:

- Release executable: `frontend/apps/desktop/src-tauri/target/release/ava-desktop`
- DEB: `frontend/apps/desktop/src-tauri/target/release/bundle/deb/AVA Desktop_0.1.0_amd64.deb`
- RPM: `frontend/apps/desktop/src-tauri/target/release/bundle/rpm/AVA Desktop-0.1.0-1.x86_64.rpm`
- AppImage: not requested in the DEB/RPM build; `/dev/fuse` remains unavailable for AppImage execution certification.

The minified Web/Desktop JavaScript bundle was 998.33 kB (304.18 kB gzip), up 1.54 kB / 0.36 kB gzip from UI-2's 996.79 kB / 303.82 kB. Chunk optimization remains out of scope.

Backend production changes, API changes, and migration changes: none. UI-3 conversation-row redesign and broader message redesign remain deferred. The unified composer and targeted Dark-mode surfaces were subsequently implemented in UI-2C; see [`docs/AVA_UI_2C_Wide_Unified_Prompt_Composer.md`](AVA_UI_2C_Wide_Unified_Prompt_Composer.md). **UI-3 has not started.**

## UI-2B follow-up

The Web application was available for the UI-2B follow-up. Its sidebar row actions were inspected in Light and Dark, and keyboard focus visibly reached a conversation Ellipsis control with its tooltip and focus ring. The native environment again exposed no native apps or window controls; therefore the new row-action appearance and the UI-2A shell theme have not been certified in an actual Tauri window. UI-2A remains open pending native Light/Dark inspection.

## UI-2C PromptComposer implementation

The previously deferred composer requirements are implemented in production by UI-2C. The shared composer fills the Chat canvas with responsive margins, uses a unified rounded surface, and exposes the four independent execution selectors through a compact contextual control. See [`docs/AVA_UI_2C_Wide_Unified_Prompt_Composer.md`](AVA_UI_2C_Wide_Unified_Prompt_Composer.md) for the width strategy, behavior, theme corrections, and validation record. This implementation does not start UI-3.
