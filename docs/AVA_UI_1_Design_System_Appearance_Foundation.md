# UI-1 — AVA Design System and Appearance Foundation

UI-1 establishes shared presentation infrastructure. It does not redesign Chat,
Projects, Documents, Settings, or the application shell. The implementation is
owned by `frontend/packages/ui-core`; Web, Desktop, and shared feature packages
consume that package rather than maintaining duplicate design systems.

## Frontend findings

The repository uses React 18.3, TypeScript 5.6, Vite 6, and pnpm workspaces.
Web and Tauri Desktop are Vite applications that compose the shared
`@ava/workspace` package. Before UI-1, there was no Tailwind or PostCSS setup,
no `@/` alias, and no shared utility-CSS framework. Most AVA screens use
legacy inline styles and the existing `defaultTheme` token object. This phase
adds Tailwind 4 utilities without importing Preflight, leaves those screens and
their styles intact, and keeps new controls in `ui-core/src/components/ui`.
The older inline-style components remain exported from the existing barrel;
new primitives are namespaced under `shadcn` to avoid public-name collisions.

## Ownership and appearance model

`@ava/ui-core` owns shadcn-derived primitives, the `cn()` utility, semantic AVA
theme CSS, theme and template registries, appearance preference types,
persistence, selectors, and `AppearanceProvider`. Both application entry
points import the same `@ava/ui-core/styles.css` and mount the same provider.

Appearance is deliberately three independent values:

```text
Template ≠ Theme ≠ Theme Mode
Template ≠ Application Behavior
Theme ≠ Application Behavior
```

`TemplateId` comes from `src/templates/registry.ts` and initially contains
`ava-default`. `ThemeName` comes from `src/themes/registry.ts` and initially
contains `ava`. `ThemeMode` is `system | light | dark`; `ResolvedThemeMode` is
`light | dark`. The default preferences are `ava-default`, `ava`, and
`system`. Appearance can change presentation only. Feature/domain components
must not branch API, persistence, or execution behavior on template or theme.

The provider API is exported from the `@ava/ui-core` root and
`@ava/ui-core/appearance`:

```tsx
<AppearanceProvider>
  <App />
</AppearanceProvider>
```

`useAppearance()` returns all three preference axes, the resolved mode, and
setters for each axis. `ThemeRegistry` and `TemplateRegistry` are small
registration points; a template is a presentation definition, not a second
application tree. Future templates should arrange shared application pieces
without copying their business logic.

## Persistence and DOM markers

The appearance persistence boundary is `src/appearance/persistence.ts`. It
owns these local-storage keys:

```text
ava.appearance.template
ava.appearance.theme
ava.appearance.mode
```

Each field is validated against its registry/type on read. A missing or invalid
field independently falls back to `ava-default`, `ava`, or `system`; blocked
storage does not prevent startup. The stored mode remains `system` even when
the OS currently resolves to dark. The provider watches
`prefers-color-scheme` changes while system mode is selected.

The provider writes separate root markers:

```html
<html data-template="ava-default" data-theme="ava" class="dark">
```

`data-template` identifies the template, `data-theme` identifies the named
theme, and the `dark` class represents the resolved mode. No combined theme
and mode identifier is used.

## Theme CSS and utility setup

`src/styles/appearance.css` is the authoritative shared AVA palette. It
contains the exact UI-1 light and dark HSL values, semantic shadcn variables,
Tailwind 4 `@theme` mappings, and the dark variant. It imports only Tailwind's
theme and utility layers: Preflight is deliberately omitted so global resets do
not restyle existing screens. `@source` scans both shared frontend packages
and application sources so Web and Desktop generate the same classes.

Theme-builder CSS can be adapted by mapping its values to the shared semantic
variables in a named theme stylesheet and registering that theme. React
components consume tokens such as `bg-background`, `text-foreground`,
`border-border`, and `ring-ring`; they do not duplicate palette literals.

## shadcn configuration and exports

`frontend/packages/ui-core/components.json` configures the New York style,
Tailwind 4, Lucide icons, and aliases rooted in `@ava/ui-core`. Components are
stored under `src/components/ui`; AVA-specific shared visual components belong
under `src/components/ava`. The package exports all new primitives through
`shadcn` while retaining legacy root exports. `src/lib/utils.ts` contains the
single shared `cn()` helper. To add a primitive, add its implementation and
barrel export under `components/ui`, add its Radix dependency to ui-core if
needed, and use semantic classes.

Available primitives are Button, Input, Textarea, Select, Dropdown Menu,
Tooltip, Dialog, Tabs, Badge, Switch, Separator, Scroll Area, Card, and
Skeleton. Existing AVA controls have not been migrated.

## Rounded Button and Lucide action standards (UI-1A)

`@ava/ui-core` owns the default Button geometry. The shared shadcn Button base
uses `rounded-md` for every supported variant (`default`, `secondary`,
`destructive`, `outline`, `ghost`) and every size (`sm`, `default`, `lg`, `icon`).
The semantic radius scale is centralized in `src/styles/appearance.css`:
`--radius` is `0.625rem` (10px at a 16px root size) and `--radius-md` is
`calc(var(--radius) - 2px)` (8px). Theme mode changes colors, not geometry.
Feature packages should consume shared Button styles and avoid default radius
overrides; future templates can alter centralized structural tokens without
editing every Button.

`lucide-react` is the canonical icon library for new shared UI. Familiar,
repetitive contextual actions should use compact icon-first controls. Actions
with workflow significance, ambiguity, or destructive consequences may keep
visible text or combine text with an icon. `Button` supplies consistent
icon/text spacing via `gap-2`. Do not use emoji as action icons when Lucide has
a suitable symbol. This is a migration standard for future work; UI-1A does not
mass-migrate existing production controls.

The shared icon action is `src/components/ui/icon-button.tsx`, exported by the
`shadcn` namespace as `IconButton`. The pre-existing root `IconButton` API
remains intact for legacy consumers, so new feature work should import the
canonical primitive from the shared UI surface. The new primitive accepts a
required `icon: LucideIcon` and `label`, optional `tooltip` (defaults to the
label; `false` intentionally suppresses it), Button variant/disabled/event
props, `size="default" | "compact"`, and `shape="rounded" | "circle"`. It
delegates colors, focus, disabled state, and geometry to shared Button. The
default is a 36×36 `rounded-md` ghost control with an 18px icon; compact is
32×32 with a 16px icon. The circular `rounded-full` shape is opt-in only.
Tooltip text supplements the required accessible name and never replaces it.
Feature code supplies the icon, label, optional tooltip, and action; the
primitive contains no archive/delete/retry semantics.

The development-only `/dev/ui` preview has dedicated Buttons and Icon Actions
sections showing variants, sizes, Lucide mappings, tooltip/accessibility
behavior, and the intentional circular exception. Its standards note stays out
of production UI.

## Settings and preview

Settings adds one Appearance section with a native, keyboard-accessible
System/Light/Dark mode selector. UI-1 does not expose template or named-theme
selection because there is only one of each. A future Settings design may add:

```text
Appearance
Template  [ AVA Default ▼ ]
Theme     [ AVA ▼ ]
Mode      [ System ▼ ]
```

The development-only `/dev/ui` path renders `src/components/ava/DesignSystemPreview.tsx`.
It displays current template/theme/mode/resolved mode, primitive variants,
form and interactive controls, skeleton examples, a scroll region, and semantic
token swatches. It is not added to primary navigation.

## Extending appearance

To add a named theme:

1. Add its semantic variable definitions in shared theme CSS.
2. Register its `ThemeName` and entry in `ThemeRegistry`.
3. Optionally expose it in a later Appearance Settings control.
4. Keep feature components independent of theme identity.

To add a template:

1. Add its presentation definition/layout and structural tokens if needed.
2. Register its `TemplateId` and entry in `TemplateRegistry`.
3. Optionally expose it in a later Appearance Settings control.
4. Compose shared feature components; do not duplicate app or domain behavior.

The separated IDs and provider setters make later profile-backed persistence
possible. UI-1 intentionally keeps preferences local and does not add backend
synchronization.

## Application integration and migration boundary

Web and Desktop import the shared stylesheet and wrap their app with the same
AppearanceProvider. The stylesheet uses no global reset, and existing
`index.css`, inline styles, `defaultTheme`, shell, sidebar, and feature views
remain. UI modernization can migrate those surfaces incrementally in later UI
work; this foundation introduces no business-component or API migration.

The React, Vite, and Tailwind configuration choices were checked against the
official [shadcn monorepo guidance](https://ui.shadcn.com/docs/monorepo),
[shadcn theming guidance](https://ui.shadcn.com/docs/theming), and
[Tailwind Preflight documentation](https://tailwindcss.com/docs/preflight).

## UI-1A certification record

The current verification run passed all recursive frontend tests, all
recursive TypeScript checks, the dedicated ui-core suite (12 files, 64 tests),
and Web/Desktop production builds. AppearanceProvider tests cover defaults,
Light/Dark/System selection, live OS mode changes, persistence across remount,
invalid-value fallback, DOM markers, and preview interaction. Button tests
cover every supported variant and size; IconButton tests cover Lucide output,
accessible name, tooltip, variants, compact sizing, disabled behavior, and
rounded/circle geometry. The preview's interactive controls are also tested.
The native release executable and DEB/RPM bundles rebuilt successfully.
`git diff --check` passes, with no backend, migration, or API files changed.
Both Vite dev servers were unavailable in this sandbox (listen failed with
`EPERM`), so live browser preview certification was not repeated in this run.

UI-1B obtained partial native evidence using the host GNOME/X11 session. The
rebuilt release executable opened an actual Tauri window with a WebKit process.
Light, Dark, and System selection worked; Dark persisted after a full release
restart, and System remained selected after a further restart. Chat loaded an
existing conversation and composer, the existing Project opened, and Documents
rendered existing records. The full evidence and remaining open checks are in
[`docs/AVA_UI_1B_Native_Appearance_Certification.md`](AVA_UI_1B_Native_Appearance_Certification.md).
The development-only native `/dev/ui` preview did not get a window, and native
DOM markers and preview-specific primitives could not be inspected. The X11
window manager stopped responding during the final Settings smoke. UI-1 remains
open; partial release-mode evidence does not close the native checklist.

The original Tauri linuxdeploy failure was investigated against
`/home/bizon/.cache/tauri/linuxdeploy-x86_64.AppImage`: it is an x86_64 ELF
AppImage (mode 770), with its standard `libdl`, `libpthread`, `libz`, and `libc`
dependencies resolved. `--version` without extraction exited 127 with `fuse:
device not found`; `/dev/fuse` is absent although `fusermount3` exists. With
`APPIMAGE_EXTRACT_AND_RUN=1`, both `--version` and `--help` work, and the Tauri
linuxdeploy command completes GTK/WebKit dependency deployment. Its AppImage
plugin then invokes appimagetool, which fails downloading the type-2 runtime
from GitHub (`server returned status code 0`). No local `runtime-x86_64` was
found. The retry therefore exits 1 and produces no AppImage. The classification
is environmental: the normal mount path is blocked by missing FUSE, while the
supported extraction path reaches packaging but cannot fetch the runtime on
this restricted-network host. No AVA packaging configuration was changed.
Native application functionality is independently unverified here, so this
environmental AppImage diagnosis alone does not close UI-1. DEB and RPM remain
separate successful targets.

The extraction-mode retry command was:

```bash
timeout 240s env APPIMAGE_EXTRACT_AND_RUN=1 \
  /home/bizon/.cache/tauri/linuxdeploy-x86_64.AppImage \
  --appimage-extract-and-run --verbosity 1 \
  --appdir '/home/bizon/AvaUi/frontend/apps/desktop/src-tauri/target/release/bundle/appimage/AVA Desktop.AppDir' \
  --plugin gtk --output appimage
```

The Tauri bundler's corresponding linuxdeploy invocation adds the same
`--appimage-extract-and-run`, `--verbosity 1`, AppDir, GTK plugin, and AppImage
output arguments. The first wrapper attempts exited 127; this retry exited 1
only after the output plugin attempted the unavailable runtime download.

UI-2 migration order is shell/navigation, Conversation sidebar, Chat
header/actions, composer, message actions, Projects, Documents, then Settings.
Each step should consume shared rounded Buttons, Lucide IconButtons, semantic
theme tokens, and Tooltip behavior. UI-2 remains blocked until UI-1 native
certification is complete.

## UI-1C native certification and final status

UI-1C completed the native Tauri `/dev/ui` preview and shared-control checks.
Native Button variants and rounded geometry, standard/compact IconButtons and
Lucide icons, Tooltip hover, Dialog/Escape, Dropdown, Select, Tabs, Switch,
Scroll Area, semantic/chart swatches, and skeletons rendered or interacted
successfully. Light and System/dark previews preserved control geometry. Native
WebKit Inspector directly confirmed `data-template="ava-default"`,
`data-theme="ava"`, and the resolved-dark `dark` class; forced Light removed
that class. Providers, Models, Runtimes, Defaults, System Prompts, and
Appearance Settings sections all rendered in native Tauri. See the detailed
[UI-1B / UI-1C certification record](AVA_UI_1B_Native_Appearance_Certification.md)
and its [`native evidence captures`](ui1b-native-evidence/).

The previously passed release Light/Dark/System selection, Dark/System restart
persistence, and Chat/Projects/Documents smoke are carried forward. Automated
frontend suites, lint/TypeScript checks, Web/Desktop builds, and the native
Tauri release plus DEB/RPM builds pass. AppImage remains an environmental
limitation (`/dev/fuse` absent); the existing 994.55 kB chunk warning remains
outside scope. No blocking appearance defect remains: **UI-1 is complete and
certified; UI-2 is not started.**
