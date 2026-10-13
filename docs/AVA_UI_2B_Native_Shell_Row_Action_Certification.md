# UI-2B — Native Shell Certification and Transparent Row Actions

**Status: shared implementation and Web acceptance complete; native acceptance remains open. UI-2A is not certified complete. UI-3 has not started.**

## Row-action standard

Conversation ellipsis menus, Folder ellipsis menus, and the compact Project `+` now use the shared `@ava/ui-core` `IconButton` with `appearance="row-action"`. This reusable appearance explicitly removes resting fill, border, and shadow, uses `text-muted-foreground`, and applies semantic `muted` hover and `secondary` menu-open states. The shared Button's focus-visible ring remains in place. Compact controls keep a rounded 32×32 hit target, the shared Tooltip, and a required accessible name.

The canonical Lucide `Ellipsis` icon replaces `MoreHorizontal` for conversation and Folder menus. Lucide `Plus` remains the Project action icon. Its existing accessible name and tooltip continue to describe the action as “New Chat in {project}” / “New Chat in Project”. No new feature-specific button styling was added.

The action buttons remain keyboard reachable and expose `aria-haspopup="menu"` and accurate `aria-expanded` state for conversation and Folder menus. The ConversationList tests verify Ellipsis icon selection and open state; the shared IconButton tests verify transparent resting classes, compact geometry, accessible naming, focus styling, and Tooltip behavior. Existing menu callbacks and Project creation behavior remain covered by workspace tests.

## Behavior and drag/drop boundary

The conversation title button retains its existing `dnd-kit` attributes and listeners. Each contextual action remains a sibling control, outside that title button and its drag target. Clicking the conversation Ellipsis opens its current menu without selecting the row; Folder menu callbacks and Project Plus creation remain unchanged. The actual drag gesture was not exercised against the live backend, so dnd-kit runtime acceptance remains unverified here. Active/Archived, search, Folder membership, Project membership, and selection logic were not modified.

## Web acceptance

The live Web sidebar was inspected in Dark, Light, and System (System resolved to Dark). Conversation actions and the Project Plus rendered as Lucide glyphs without a persistent gray button box in both color modes. A selected conversation kept its semantic selected-row surface while its Ellipsis retained transparent resting chrome. Keyboard navigation reached the conversation Ellipsis and showed its visible focus ring and shared tooltip. Opening and closing the conversation menu worked without activating a menu item. Appearance was restored to System after the Light inspection.

The live page's CUA screenshot output was available for visual inspection but did not expose a file export path. No image files were saved under `docs/ui2b-evidence/`.

## Native acceptance and UI-2A closure

The native app inventory exposed zero native apps and no native-window controls in this session. As a result, this task could not inspect the actual Tauri shell in Light or Dark, open a native conversation menu, or interact with the native Project Plus action. The release executable was produced, but a built executable alone does not certify its rendered WebView or interaction.

The release executable, DEB, and RPM were built successfully with `pnpm --filter @ava/desktop tauri build --bundles deb,rpm` (exit 0). The default all-target `pnpm --filter @ava/desktop tauri build` also reached AppImage bundling but stopped producing output; it was interrupted after more than 45 seconds. `/dev/fuse` is absent and no AppImage was produced. The release binary was not launched because this session had no native window surface to verify it. Native release smoke and screenshot evidence remain outstanding. UI-2A and UI-2B remain open for native visual certification; UI-2 is not fully closed.

## Validation

- `pnpm -r test`: passed across the runnable workspace packages. `@ava/ui-core` 68 tests; `@ava/desktop` 11; `@ava/agent-ui` 299; `@ava/workspace` 211 passed and 6 skipped; `@ava/document-core` 70; `@ava/settings-core` 211; `@ava/api-client` 112; `@ava/contracts` 42. Six live integration tests remain skipped by their existing configuration.
- `pnpm -r lint`: passed, including the workspace TypeScript checks.
- `pnpm --filter @ava/web build`: passed; JavaScript bundle 998.64 kB (304.27 kB gzip) with the existing large-chunk warning.
- `pnpm --filter @ava/desktop build`: passed; same 998.64 kB (304.27 kB gzip) bundle and warning.
- `pnpm --filter @ava/desktop tauri build --bundles deb,rpm`: passed; release executable, DEB, and RPM generated.
- Default all-target `pnpm --filter @ava/desktop tauri build`: AppImage bundling did not finish; interrupted after more than 45 seconds. `/dev/fuse` is absent and AppImage was not produced.
- No backend, API, contract, or migration changes were made.
