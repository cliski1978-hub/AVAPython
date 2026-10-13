# UI-1B / UI-1C — Native Appearance Certification

**Status: complete. UI-1 is complete.** UI-1B's release-mode Light/Dark/System
and restart-persistence checks remain valid. UI-1C closed the remaining native
preview, shared-control, Tooltip, DOM-marker, and Settings evidence gaps without
changing production behavior.

## Native environment

The certification used the local GNOME/X11 session (`DISPLAY=:1`,
`XDG_SESSION_TYPE=x11`, `WAYLAND_DISPLAY` unset) with GTK 3.24.33 and
WebKitGTK 4.1 2.50.4. The session and window manager were responsive when
checked; an earlier transient X11/window-manager stall recovered and was
classified as environmental, with no AVA change made for it.

The release executable had already launched successfully in UI-1B. In UI-1C,
the repository Tauri development command also opened a real `AVA Desktop`
WebKit window. It was used only for the development-gated `/dev/ui` preview.
The native window remained responsive throughout the preview interactions and
Settings sweep.

## Native preview and shared controls

The actual native `/dev/ui` preview rendered Appearance status; Button and
Icon Actions; inputs, textarea, select, switch, badges, cards, dialog, tabs,
dropdown, tooltip, scroll area, skeletons, semantic swatches, and chart swatches.
The saved native preview captures are in
[`ui1b-native-evidence/`](ui1b-native-evidence/).

- Shared Button default, secondary, destructive, outline, ghost, disabled, and
  small/default/large/icon examples rendered. Their canonical rounded geometry
  remained consistent across Light and System/dark; mode changed semantic
  styling, not dimensions or icon alignment.
- Shared IconButton standard, compact, ghost, outline, destructive, disabled,
  circle, and icon-plus-text examples rendered. The Plus, Search, Pencil, Copy,
  RefreshCw, Archive, Trash2, Download, Upload, Settings, Ellipsis, X,
  ArrowUp, and Square Lucide icons were crisp, present, and unclipped. Standard
  and compact examples matched the shared 36×36 / 18px and 32×32 / 16px
  specifications.
- Hovering the Add IconButton displayed its “Add” Tooltip without blocking
  activation.
- Dialog opened above the preview and closed with Escape. Dropdown opened in
  place. Select changed to Option two. Tabs changed active content. Switch
  toggled. The bounded Scroll Area scrolled normally.
- Light and System/dark preview states retained the same control geometry.

## Appearance and DOM markers

UI-1B's release evidence remains the source for native Light, Dark, and System
selection and Dark/System persistence across full restarts. System resolved to
the host's dark preference. UI-1C additionally verified the preview in Light
and System/dark in the native WebView.

WebKit Inspector directly showed:

```html
<html lang="en" data-template="ava-default" data-theme="ava" class="dark">
```

under resolved dark/System. Forced Light removed the `dark` class while
retaining `data-template="ava-default"` and `data-theme="ava"`. DOM marker
certification is direct. The host OS preference was not changed live because
that was unnecessary and could risk the desktop session; the existing passing
AppearanceProvider tests cover the reactive `prefers-color-scheme` listener.

Settings → Appearance exposed only System, Light, and Dark; no template or
single-option theme selector was added.

## Application and Settings smoke

The UI-1B release smoke remains valid: Chat and an existing conversation,
Projects and an existing workspace, and Documents and existing document
content rendered. Release Light/Dark/System checks found no catastrophic
readability or layout regressions on Chat, Projects, Documents, and Settings;
legacy surfaces retaining their existing styling is within UI-1's no-migration
scope.

In the UI-1C native app, each major Settings section rendered: Providers,
Models, Runtimes, Defaults, System Prompts, and Appearance. No edit/create
actions were performed. Captures are saved in the evidence directory.

## Validation

The UI-1C validation run passed:

```text
@ava/ui-core       12 files, 64 tests
@ava/desktop        1 file, 11 tests
@ava/agent-ui      21 files, 294 tests
@ava/workspace     15 files, 209 passed, 6 skipped
@ava/api-client    14 files, 112 tests
@ava/contracts     13 files, 42 tests
@ava/document-core  7 files, 70 tests
@ava/settings-core 11 files, 210 tests
pnpm -r lint       PASS (recursive lint/TypeScript checks)
Web production     PASS
Desktop frontend   PASS
Tauri release      PASS
DEB/RPM            PASS
```

The canonical native Tauri release build was rerun during UI-1C and passed,
including DEB and RPM. No production files were changed during the UI-1C
certification step. Backend, migration, and API changes are none.

The existing Web build warning remains: the largest JavaScript chunk is
994.55 kB minified (303.11 kB gzip). It is outside UI-1 scope and was not
optimized here.

## Accepted limitations and closure

AppImage remains **NOT PRODUCED — ENVIRONMENTAL LIMITATION**. `/dev/fuse` is
absent and no local `runtime-x86_64` is available; the environment did not
materially change, so no retry was required. The native executable, DEB, and
RPM succeeded.

No blocking appearance defect remains. UI-1C is complete; UI-1 is complete.
UI-2 remains not started. AVA's design-system and appearance foundation,
rounded-button standard, and Lucide icon-first standard are certified.
