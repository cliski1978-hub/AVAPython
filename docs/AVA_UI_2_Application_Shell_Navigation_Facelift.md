# UI-2 — Application Shell and Navigation Facelift

**Status: UI-2 structure complete; full UI-2 closure remains open pending native visual certification of UI-2A and UI-2B.** UI-2 established the shared `ava-default` shell and top-level navigation. UI-2A completed semantic theme adoption on the shell-owned Chat surfaces and controls; UI-2B establishes transparent contextual row actions. Their Web acceptance passed, while actual Tauri Light/Dark inspection remains outstanding. See [`docs/AVA_UI_2A_Shell_Theme_Control_Completion.md`](AVA_UI_2A_Shell_Theme_Control_Completion.md) and [`docs/AVA_UI_2B_Native_Shell_Row_Action_Certification.md`](AVA_UI_2B_Native_Shell_Row_Action_Certification.md). Projects, Documents, and Settings feature internals and domain behavior remain outside this presentation migration.

## Scope and architecture discovered

Both `frontend/apps/web/src/App.tsx` and `frontend/apps/desktop/src/App.tsx` are thin host compositions that create an `ApiClient` and render the same `@ava/workspace` `AppWorkspace`. The shared workspace owns the route selection and composes stable `ConversationProvider`, `DocumentProvider`, and `AgentRunProvider` instances above its workspace content. Its feature panes stay mounted across top-level navigation and are hidden when inactive, preserving in-session state and run ownership.

`@ava/ui-core` owns the generic `AppShell`, `Header`, `Sidebar`, and the new `PrimaryNav`. `@ava/workspace` retains the compatibility-facing `WorkspaceTabs` export as a thin adapter over `PrimaryNav`; route changes remain owned by `AppWorkspace`. Conversation list content, folders, archive/search state, and drag/drop remain in `@ava/agent-ui`; Projects, Documents, and Settings retain their existing feature packages. The shell does not inspect provider, runtime, execution-default, or conversation domain state.

The active template remains `ava-default`; no template or theme identity was added. Existing Template/Theme/Theme Mode separation remains under `AppearanceProvider`. Both Web and Tauri use the same shared shell and primary navigation. Native titlebar/window chrome remains system-owned.

## Shell and navigation changes

The former custom top-level tab buttons are now semantic links in one labeled `<nav>`. The stable mapping is:

| Destination | Lucide icon | URL |
| --- | --- | --- |
| Chat | `MessageSquare` | `/` |
| Projects | `FolderKanban` | `/projects` |
| Documents | `FileText` | `/documents` |
| Settings | `Settings` | `/settings` |

Each link retains a visible text label, uses `aria-current="page"` for the active destination, and has a semantic hover treatment and `focus-visible` ring. Native anchor activation and modified-click behavior are preserved. `PrimaryNav` is intentionally distinct from `IconButton`: these are navigation links with labels and route semantics.

The persistent header is compact and uses the AVA name and top-level destinations rather than adding a second sidebar navigation. The app root uses a full-height flex layout with an open main canvas and semantic background/foreground tokens. The conversation sidebar uses a semantic card surface and border; collapse is a shared `IconButton` with Lucide `PanelLeftClose`/`PanelLeftOpen`, a shared Tooltip, and an accessible action name. On mobile widths, the existing responsive hook collapses the sidebar; UI-2 does not add another nav mode.

The `ava-default` structural stylesheet defines `--ava-sidebar-width: 17rem`, `--ava-sidebar-collapsed-width: 3.5rem`, `--ava-header-height: 3.5rem`, `--ava-shell-content-padding: 1.25rem`, and `--ava-shell-section-gap: 1.25rem`. Geometry is kept separate from theme colors. Existing layouts continue to own feature-specific inner spacing; the shell avoids wrapping every route in another card.

The prominent New Chat action now uses the shared rounded `Button` and Lucide Plus icon. Conversation search uses the shared semantic `Input`, Lucide Search icon, and a shared tooltip-backed clear `IconButton`. Search behavior is unchanged. These are toolbar/chrome migrations; conversation rows, folder rows, archive rows, dnd-kit targets, context menus, and conversation actions were not redesigned.

`/documents` and `/settings` now initialize and update through the existing workspace route state, alongside `/` and `/projects`. Project workspace URLs remain `/projects/:projectId`. The internal Settings section navigation and Appearance control remain in Settings. The development-only `/dev/ui` preview remains available in Vite hosts. No router package or backend route was introduced.

## Preserved boundaries

- No backend, API contract, SQLite schema, migration, or persistence code changed.
- No conversation, run/event, folder, Project, Document, Settings, CORE prompt, Project Files, or execution-selection behavior was moved into `ui-core`.
- Provider wrappers remain stable above route content; the navigation state update does not key or reconstruct them.
- Conversation list selection, Active/Archived views, search semantics, folder operations, and dnd-kit behavior remain feature-owned.
- Projects workspace sections, Documents editor, Settings sections, and Appearance state remain feature-owned and were not visually redesigned.
- No large dependency or UI-2-specific package dependency was added.

## Verification

All 10 runnable workspace test projects passed. Six existing live integration cases remain skipped by their test configuration.

| Suite | Result |
| --- | --- |
| `@ava/ui-core` | 13 files, 66 tests passed |
| `@ava/desktop` | 1 file, 11 tests passed |
| `@ava/agent-ui` | 21 files, 294 tests passed |
| `@ava/workspace` | 15 files, 211 passed, 6 skipped |
| `@ava/document-core` | 7 files, 70 tests passed |
| `@ava/settings-core` | 11 files, 210 tests passed |
| `@ava/api-client` | 14 files, 112 tests passed |
| `@ava/contracts` | 13 files, 42 tests passed |

`pnpm -r lint` passed. `pnpm --filter @ava/web build` and `pnpm --filter @ava/desktop build` passed. Both production builds emit the known 500 kB chunk warning: the shared minified JavaScript bundle is 996.79 kB (303.82 kB gzip), about 2.24 kB above the UI-1C recorded 994.55 kB. Bundle optimization was outside UI-2.

The live Web app was checked in Light, Dark, and System modes. System resolved to the host Dark appearance after the selector was restored. Keyboard Enter activation reached Chat, Projects, Documents, and Settings. Direct loads followed by hard reloads rendered Chat, Projects, Documents, Settings, and an existing `/projects/:projectId` workspace. The Project workspace retained its existing sections. Existing Documents and Settings content remained available. Responsive shell behavior was checked at a narrow viewport; the sidebar collapsed and the labeled primary navigation remained usable.

The release Tauri window launched successfully and displayed the shared shell and Chat workspace. Under System appearance, temporarily changing GNOME from `prefer-dark` to `prefer-light` changed the native shell surfaces to Light; restoring `prefer-dark` returned the native shell to Dark. The original GNOME preferences (`prefer-dark`, `Yaru-blue-dark`) were restored. This UI automation surface exposed browser controls but no native-window controls, so native navigation destinations were not individually clicked in the release window; the same `AppWorkspace` and `PrimaryNav` are used by both hosts, and route/keyboard interaction was verified in Web and shared workspace tests.

The native release executable was built at `frontend/apps/desktop/src-tauri/target/release/ava-desktop`. Tauri produced:

- `frontend/apps/desktop/src-tauri/target/release/bundle/deb/AVA Desktop_0.1.0_amd64.deb`
- `frontend/apps/desktop/src-tauri/target/release/bundle/rpm/AVA Desktop-0.1.0-1.x86_64.rpm`

AppImage was not built in the requested DEB/RPM bundle pass. `/dev/fuse` is absent in this environment, so AppImage execution cannot be certified here. The native Light/Dark shell captures are in [`docs/ui2-evidence/`](ui2-evidence/).

`git diff --check` passed. No backend, migrations, or API files appear in the change set. `CONTEXT.md` now records only the durable shell/design-system boundary.

## Files and components

UI-2 adds `frontend/packages/ui-core/src/components/PrimaryNav.tsx`, `frontend/packages/ui-core/src/components/primary-nav.test.tsx`, `frontend/packages/ui-core/src/icons.ts`, and `frontend/packages/ui-core/src/templates/ava-default.css`. `PrimaryNav` is exported through the ui-core component and package entry points.

The shared `AppShell`, `Header`, and `Sidebar` in `ui-core` now use the template geometry and semantic utility classes. `WorkspaceTabs` delegates to `PrimaryNav`; `AppWorkspace` retains route ownership and directs all four top-level destinations. `ConversationList` adopts shared controls for New Chat and search chrome. Web/Desktop app entry points preserve the development preview route, and the Desktop test harness resets location between tests now that route navigation updates browser history.

Pre-existing UI-1 files and dependency configuration remain part of the working tree. They were preserved and were not reverted as part of UI-2.

## Next phase

The next logical scope is **UI-3 — Conversation Sidebar + Chat Header Facelift**, focusing on conversation and Folder rows, archive/search presentation, contextual actions, and icon consistency. UI-2C has since implemented the wide unified shared PromptComposer and corrected the requested Dark-mode surfaces in Settings, Projects, and Documents. See [`docs/AVA_UI_2C_Wide_Unified_Prompt_Composer.md`](AVA_UI_2C_Wide_Unified_Prompt_Composer.md). **UI-3 has not started.**
