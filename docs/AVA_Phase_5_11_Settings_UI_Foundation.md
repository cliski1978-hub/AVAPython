# AVA Phase 5.11 — Settings UI Foundation

Phase 5.11 makes Settings a first-class area of the AVA application. It adds
navigation, section structure, shared loading/error/empty patterns, a
read-only inventory, and the modal pattern that the management phases will use.

It adds **no** create, edit, enable, disable, or delete workflow. There is no
provider, model, runtime, or defaults form in this phase, and no dead control
that looks like one.

## 1. Where Settings lives

Settings is a new shared package, `@ava/settings-core`, composed by
`@ava/workspace` and reached identically from both shells.

```text
frontend/packages/settings-core     <- the Settings feature (implementation center)
frontend/packages/workspace         <- composes chat, documents, and settings panes
frontend/apps/web/src/App.tsx       <- unchanged, thin shell
frontend/apps/desktop/src/App.tsx   <- unchanged, thin shell
```

This follows the existing feature-package pattern (`@ava/document-core` is
composed the same way by `@ava/workspace`). Settings is a whole feature area
with its own sections, state, and tests; putting it in `ui-core` would make the
presentation package depend on the API client, and putting it in `workspace`
would turn the composer into a feature host.

`web/src/App.tsx` and `desktop/src/App.tsx` are byte-identical and untouched.
Both builds emit the same bundle hash (`index-DdGtUhLR.js`), which is the
practical proof that there is one implementation and not two that happen to
look alike.

### Why the modal primitive is not in `settings-core`

`Modal` lives in `@ava/ui-core`. There is exactly one dialog system in the
frontend, and it belongs with the other presentation primitives so documents
and conversations can reuse it later. `SettingsModal` is a thin Settings-shaped
wrapper over it, not a second modal system. A feature-local dialog would have
become the competing system the phase explicitly rules out.

## 2. Entering Settings from main navigation

Settings is a third tab in the existing `WorkspaceTabs` control, alongside Chat
and Documents:

```text
[ Chat ] [ Documents ] [ Settings ]
```

`WorkspaceId` becomes `"chat" | "document" | "settings"` and the tab list gains
one entry. This is the application's current navigation pattern, so Settings is
a normal top-level view: same `role="tab"` semantics, same `aria-selected` and
`aria-controls`, same styling, same keyboard reachability. No second navigation
framework, no route, and no developer-only entry.

Two composition details in `AppWorkspace` matter:

- **The Settings pane is mounted lazily.** `settingsOpened` mirrors the existing
  `documentOpened`, so the surface is not created — and no Settings request is
  issued — until the user actually opens Settings. A test asserts that no
  Settings call happens on app start.
- **The conversation sidebar is hidden outside Chat.** `AppShell` gained an
  optional `showSidebar` prop (default `true`, so existing compositions are
  unaffected) and `AppWorkspace` passes `workspace === "chat"`. Without this the
  Settings view would sit beside a "Conversations" sidebar, which is
  conversation-specific chrome. This follows a precedent already in the file:
  the prompt composer is likewise hidden outside Chat. The composer stays
  *mounted* and is hidden with `display: none`, so composer drafts and in-flight
  run state survive a visit to Settings.

## 3. Section navigation

Four sections, rendered as a segmented `role="tablist"` that mirrors the
workspace tabs:

```text
Settings
 [ Providers ] [ Models ] [ Runtimes ] [ Defaults ]
```

The choice of a segmented control over a sidebar or nested routes is driven by
what this frontend actually is: there is no router anywhere in it. View
selection is a `useState` enum in `AppWorkspace`. Adding nested routes for four
panels would have meant introducing a router to satisfy a layout preference.

Section selection is plain `useState<SettingsSectionId>` inside
`SettingsWorkspace`. That makes it directly testable — a test clicks a tab and
asserts both `aria-selected` and the rendered panel — with no router, no URL,
and no cross-component coordination. `SettingsWorkspace` accepts an
`initialSection` prop so a test or a future deep link can start on a chosen
section.

`SETTINGS_SECTIONS` is the single definition of the four sections; the nav, the
panel id, and the tests all read from it.

## 4. Read-only API data is loaded

Yes. The 5.10 typed client made this straightforward, and read-only display is
inside the phase boundary while management workflows are not. Each section calls
one typed wrapper:

| Section | Client call | Endpoint |
| --- | --- | --- |
| Providers | `listProviderConnections` | `GET /settings/providers` |
| Models | `listModelConfigurations` | `GET /settings/models` |
| Runtimes | `listRuntimeConfigurations` | `GET /settings/runtimes` |
| Defaults | `getExecutionDefaults` | `GET /settings/defaults` |

Every call goes through `@ava/api-client`; no section calls `fetch`. A guard
test fails the build if `fetch(`, `XMLHttpRequest`, `axios`, `EventSource`, or
`WebSocket` appears anywhere in the package, and the pre-existing cross-package
`step411` guard now scans `packages/settings-core/src` too.

### One async primitive, not four

`useSettingsResource` is the only data hook in the package. It returns
`{ status, data, error }` plus `reload`, and every section uses it, so loading,
error, retry, and empty behaviour are defined once. This is what the phase's
"do not create four unrelated loading implementations" requirement needs
structurally rather than by convention.

It follows the existing `useEffect` + `cancelled` pattern from
`AppWorkspace`/`ConversationProvider`, adds no cache and no state library, and
carries a generation counter so a retry cannot be overwritten by a slower
earlier request. During a *reload* it keeps the current data visible instead of
collapsing to a loading skeleton, which is what the management phases want
after a successful write.

## 5. Loading, error, and empty states

Three components, in `SettingsSectionState`, shared by all four sections:

- **`SettingsLoading`** — reuses `LoadingIndicator` from `ui-core` (which
  already carries `role="status"`), centred in a reserved `min-height` box.
- **`SettingsError`** — `role="alert"`, the sanitized message, and a retry
  button with a section-specific label ("Retry loading providers").
- **`SettingsEmpty`** — reuses `EmptyState` from `ui-core`.

All three render *inside the section body*. The Settings shell — heading, section
navigation, panel frame — is rendered unconditionally, so a slow or failing
request never removes the controls a user needs to leave. That is the whole
reason the shell and the body are separate, and it is asserted directly: a test
clicks a different section while a section is failing.

### Error messages cannot leak backend detail

`settingsErrorMessage` maps a failure to one of two things:

1. A backend `ErrorResponse` message, shown verbatim. Phase 5.10 returns
   operator-facing sentences ("Unknown provider connection: acme"), so this is a
   designed UI string rather than a diagnostic.
2. Otherwise, a fixed sentence chosen by status category. A thrown value is
   never rendered.

The reason is that a raw thrown value carries a stack frame, an internal URL, a
driver message, or request detail. `TypeError: Failed to fetch:
http://10.0.0.5:8000/settings/providers` and
`sqlite3.OperationalError: no such table` are both asserted to produce output
containing neither the host, the port, nor the driver name. Ten unit tests pin
this, because one leak is one test failure too many.

### Unconfigured defaults are not an error

`GET /settings/defaults` answers `200` with `configured: false` when nothing is
configured. The section branches on that flag and renders the ordinary empty
state, "Execution defaults are not configured." Treating it as a missing
resource is precisely the mistake the 5.10 contract was shaped to prevent, and
two tests assert the empty state appears with no error element present.

## 6. Inventory pattern

`SettingsInventory` is a list of rows, not a data grid:

```text
[ Acme Primary                      acme · https://api.acme.test   ● Enabled ]
```

Each row takes an already-shaped descriptor — `id`, `title`, `association`,
`metadata`, `enabled` — so the sections own their domain wording and the
pattern itself stays domain-free. The management phases add a per-row action
through the existing `renderActions` slot rather than a redesign.

Enabled/disabled uses the existing `StatusIndicator` badge, so it matches the
rest of the application. Rows are rendered in a `<ul>` with an accessible name
("Configured provider connections").

A grid was deliberately not built. Each inventory has a handful of rows, and
sorting/filtering/column configuration is work the later phases would have to
work around.

**Disabled records are never filtered.** A record a user configured must stay
visible so it can be found and re-enabled. All three inventories have a test
asserting a disabled record still renders with a "Disabled" badge.

The defaults section does not use this pattern: it is a single record of three
references, not a list, so it renders three labelled rows instead.

## 7. Modal foundation

`SettingsModal` fixes the vocabulary every future dialog shares — title, body
slot, primary action, cancel, close, busy primary, disabled primary, and a
validation/error area — so Add Provider, Edit Model, and Edit Defaults cannot
each invent a different shape.

```tsx
const [modal, setModal] = useState<SettingsModalState | null>(null);
const [error, setError] = useState<string | null>(null);

<SettingsModal
  open={modal !== null}
  title="Add Provider"
  primaryAction="Create"
  onPrimaryAction={submit}
  onClose={() => setModal(null)}
  error={error}
  primaryBusy={modal === "busy"}
>
  {/* future form fields */}
</SettingsModal>
```

`SettingsModalState` is `idle | busy` — the two states a form needs to
distinguish "editable" from "submitting".

### Accessibility

The underlying `Modal` implements one contract, tested in both packages:

- `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` pointing at the
  title
- focus moves into the dialog on open and is **restored to the previously
  focused element** on close
- `Tab` and `Shift+Tab` cycle within the dialog (focus trap); with no focusable
  content, focus stays on the dialog
- `Escape` closes; so does a backdrop click; an inner click does not
- background scroll is locked while open and restored afterwards
- the close affordance has `aria-label="Close dialog"`; a busy primary action
  gets `aria-busy="true"` and `disabled`

One decision worth stating because a test initially asserted the opposite:
focus lands on the **first control in DOM order**, which is the close button in
the header, not the first form field. The first field is one `Tab` away. The
tests now assert that focus is inside the dialog and that it is the close
affordance, which is the behaviour that is actually intended.

## 8. Modal state ownership

Local `useState` in whichever section opens the dialog. No store, no modal
manager, no registry, and no new state library. The test harness in
`settings-modal.test.tsx` *is* the pattern the management phases will follow, so
the foundation is proven by being used rather than by documentation alone.

Phase 5.11 ships the pattern with no consumer, which is why the modal tests
drive it through a harness instead of through a real form.

## 9. Credential safety

The only credential concept anywhere in the frontend is
`credential_reference`, an opaque location such as `env:OPENAI_API_KEY`. The
Providers section displays it as read-only configuration metadata, the same way
the backend designed it to be displayed.

A guard test fails the build if `SecretValue`, `resolveCredential`,
`resolveConnectionCredential`, `api_key`, `apiKey`, or `secretValue` appears
anywhere in the package. A second guard fails if `localStorage`,
`sessionStorage`, `indexedDB`, or `document.cookie` appears, so credential
material cannot be persisted in the browser even accidentally.

No frontend concept for a resolved key, password, or token exists, because the
backend never returns one and a client cannot render what it may not receive.

## 10. Discovery and Settings are not conflated

Settings shows *persisted configuration*; discovery reports *what is currently
available*. The two are separate concepts, separate endpoints, and separate
mental models:

| Concept | Endpoint | Shows |
| --- | --- | --- |
| Configured runtimes | `/settings/runtimes` | runtime records an operator created |
| Available runtimes | `/runtimes` | registered runtime implementations |
| Configured models | `/settings/models` | declared model bindings |
| Available models | `/models` | registered models |

A section never calls a discovery endpoint, and none of the four sections
mixes the two. This matters most for runtimes: a configuration may name an
adapter kind that is not installed, and that record is still shown, because the
configuration exists regardless of what is currently reachable. Flagging it as
broken would be an error this phase has no basis to declare.

## 11. Web and desktop sharing

Both shells render `<AppWorkspace client={client} />` and nothing else. Settings
is composed inside `@ava/workspace`, so there is no `WebSettings` or
`DesktopSettings`, and no shell needed an adapter. The shells were not modified
at all in this phase.

## 12. Conversation UI stability

Nothing in the conversation surface changed. Verified by the pre-existing
`AppWorkspace` suite (46 tests, including conversation state preservation
across workspace switches, composer behaviour, run controls, and document
hydration) plus ten new tests in `settings-navigation.test.tsx` covering:

- the Settings entry appears and is not selected by default
- Settings is not mounted and issues no request before it is opened
- opening Settings, loading its sections, and returning to Chat
- Documents still reachable from Settings
- the sidebar is hidden in Settings and restored in Chat
- the composer is hidden in Settings and visible again in Chat
- conversation state survives a visit to Settings

## 13. Tests

```text
@ava/settings-core   53 tests   4 files
  settings-workspace.test.tsx   21  section navigation, four sections, API data,
                                     disabled records, loading/error/empty,
                                     unconfigured defaults, scoped failures
  settings-modal.test.tsx       13  open, cancel, close affordance, Escape,
                                     ARIA, focus in/restore, busy, disabled,
                                     error slot, single-primitive guard
  settingsErrorMessage.test.ts  10  no backend detail ever reaches the UI
  settings.architecture.test.ts   9  transport, secret, storage, and phase
                                     boundary guards

@ava/workspace        46 tests   settings-navigation.test.tsx (10) plus the
                                   pre-existing suite, unchanged
@ava/ui-core          38 tests   modal.test.tsx (13), modal-render.test.tsx (3),
                                   plus 22 pre-existing
```

No provider/model/runtime/defaults CRUD behaviour is tested, because none
exists. One test asserts the negative directly: the Providers section with a
record loaded renders no button matching Add, Edit, Delete, Remove, Enable,
Disable, or Save.

### Two guard families in `settings.architecture.test.ts`

Transport and safety guards hold for every future phase. Phase-boundary guards
hold only until the management phases: the write-endpoint list and the
non-GET-method check encode "5.11 added no CRUD", and 5.12–5.15 will each
delete their own entry when they deliberately add a write. A boundary that is
never lifted cannot tell anyone anything.

## 14. Changes to the shared architecture guard

`step411.architecture.test.ts` now also scans
`packages/settings-core/src`, and its `fetch(` pattern covers `/settings`.

It now skips `*.test.*` files. This was necessary and is correct: a test must be
able to name a forbidden token in order to assert the shipped code never
contains one, which both the 5.9 credential guard and the new 5.11 Settings
error guard do. A test file is not shipped UI. Previously only the guard file
itself was excluded, because nothing else in those directories mentioned a
forbidden token.

## 15. Validation

```text
pnpm -r test    476 passed, 4 skipped, 0 failed  (10 projects)
pnpm -r lint    10/10 clean (tsc --noEmit)
pnpm build:web  built in 1.18s
pnpm --filter @ava/desktop build   built in 1.18s
git diff --check   clean
```

Both builds emit identical asset hashes (`index-DdGtUhLR.js`,
`index-DuWeGZp6.css`).

The backend was not touched in this phase and its suite is unaffected.

## 16. Implications for 5.12–5.15

**5.12 — Provider Connection Management UI.** Open `SettingsModal` from
`ProviderConnectionsSection` with local `useState`. The form needs a **select
for `provider_id`**, and `@ava/ui-core` has no `Select` primitive today — only
`Input` and `Textarea`. This is the single largest piece of missing groundwork
in the UI layer and 5.12 will have to add it. There is also no checkbox or toggle for `enabled`.
`Display name` is a text `Input`;
`endpoint` and `credential_reference` are nullable text inputs, where clearing
means sending an explicit `null`; `enabled` is a boolean. On `409`, show the
`ErrorResponse` message in the modal's error slot and keep the dialog open. On
success, call `reload()`. Remember to delete `createProviderConnection` and
`updateProviderConnection` from the architecture guard's write list.

> **Status (Phase 5.12):** done. `Select` and `Checkbox` are in `@ava/ui-core`,
> provider add/edit is implemented, and exactly those two entries were removed
> from the guard's write list. See
> `AVA_Phase_5_12_Provider_Connection_Management_UI.md`. One finding from that
> phase qualifies the advice above: the provider-type field is a select of
> discovered types *plus* a free-text escape, because the backend does not
> validate `provider_id` against installed adapters and the frontend must not be
> stricter than the domain.

**5.13 — Model Configuration Management UI.** The form depends on 5.12: the
`provider_connection_id` select must be populated from
`listProviderConnections`, so 5.13 cannot land before 5.12. `hosting_mode` is a
three-value enum — `ModelHostingMode` is exactly `"local" | "company_hosted" |
"external"` — and needs a select. `capabilities` is a nested
object with a defaulted shape; decide deliberately whether it gets a structured
editor or a JSON field, because `extra="forbid"` on the request contract means
an unrecognised capability key is rejected. Delete
`createModelConfiguration` and `updateModelConfiguration` from the guard.

> **Status (Phase 5.13):** done. The capabilities question is settled — an
> eight-checkbox fieldset, not a JSON field, and no "add custom capability"
> escape hatch, which `extra="forbid"` would reject anyway. The vocabulary is
> fixed in `modelCapabilities.ts` and the architecture test cross-checks the
> labels against `ModelCapabilities` in `@ava/contracts`, so the two cannot
> drift. `createModelConfiguration` and `updateModelConfiguration` were removed
> from the guard. See `AVA_Phase_5_13_Model_Management_UI.md`.
>
> Two findings from that phase qualify the advice above. First, the
> `provider_connection_id` select is **not** given a free-text escape, unlike
> the 5.12 provider-type field, because the backend *does* enforce this
> relationship and unlike `provider_id` the front end is not being stricter
> than the domain. Second, a closed `Select` silently coerces an unrecognised
> value to its first option, so the editor appends a record's own
> `hosting_mode` as a visible `… (not offered by this build)` option when it is
> not one of the three — otherwise a save would quietly rewrite the stored
> mode. 5.14 and 5.15 both use closed selects and should apply the same guard.

**5.14 — Runtime Configuration Management UI.** The simplest of the three:
four fields, and `runtime_type` is immutable after creation. The phase decided
an immutable field may be **omitted** or **resent with the current value** but
never changed, so the form should send it unchanged on edit and simply not
offer retyping as an editable control. Note that `runtime_type` is not validated
against installed runtimes, so the form should present it as free text or a
select over known adapters without implying the backend will reject an unknown
one. Delete `createRuntimeConfiguration` and
`updateRuntimeConfiguration` from the guard.

> **Status (Phase 5.14):** done. Runtime add/edit is implemented on the same
> foundation, and `createRuntimeConfiguration` / `updateRuntimeConfiguration`
> were removed from the guard, leaving `setExecutionDefaults` as the only
> forbidden write. See `AVA_Phase_5_14_Runtime_Management_UI.md`.
>
> Three findings from that phase bear directly on 5.15:
>
> 1. The advice below to present `runtime_type` as "free text or a select over
>    known adapters" is settled as a **select over registered adapters plus a
>    custom escape**, not free text — free text would discard the discovery
>    convenience without gaining anything, since the backend does not validate
>    either way.
> 2. The inventory states registry membership on a line separate from `enabled`,
>    and the line is **omitted** when discovery is loading or unreachable rather
>    than guessed. "Not currently registered" must never be inferred from a
>    failed lookup. 5.15 reads three inventories to populate three selects, so
>    it inherits this three-way distinction (loading / unavailable / empty).
> 3. A create-only gate must not be reused as an edit gate. 5.13 had that bug —
>    "no selectable provider connection" disabled *editing* a model whose
>    connection had been disabled since — and 5.15's selects must include
>    **disabled** records, because 5.8 validates a default against an *enabled*
>    record: a stored default pointing at a since-disabled runtime would
>    otherwise become unsaveable.
>
> One bug from that phase is worth recording against 5.12 as well: its
> "Other provider type…" escape hatch was unreachable, because choosing it
> cleared the value that the custom-field predicate required to be non-empty.
> No test covered that path. Both escape hatches now track an explicit choice
> flag alongside the value test, and each has a regression test.

**5.15 — Execution Defaults Editing UI.** Not a list: a single record of three
selects (`default_provider_connection_id`, `default_model_id`,
`default_runtime_configuration_id`) with cross-validation. The backend enforces
that all three exist, all three are enabled, and the model's
`provider_connection_id` matches the chosen connection — so the UI should filter
the model select to models belonging to the selected connection and
communicate the "must be enabled" rule, rather than letting the user discover
it as a `422`. The `configured: false` branch becomes an "Add defaults" action
on the empty state. Delete `setExecutionDefaults` from the guard.

> **Status (Phase 5.15):** done, with one deliberate deviation from the wording
> above. The empty-state action is **Configure Defaults**, not "Add defaults",
> because 5.8 made the repository singular — one record, `get` and `set`, no
> list, no create, no delete. There is no second record to add, so an "Add"
> affordance would promise something the API cannot do. The configured state
> says **Edit Defaults** for the same reason.
>
> The three-way loading / unavailable / empty distinction anticipated above is
> implemented, and it turned out to be the central problem of the phase rather
> than a detail: all three inventories feed closed selects, and a failed request
> renders identically to an empty list unless it is prevented. `ChoiceSet`
> therefore carries a `blocking` flag separate from its status, so a save is
> refused while any source is unknown and a per-field retry is offered.
>
> The 5.13 finding about disabled records is also honoured, and extended: a
> stored default naming a since-disabled record stays visible and disabled
> rather than being dropped, and a stored id that is absent from a successful
> response is shown as `<id> (not present in current configuration)`. Dropping
> it would render the field as unset, which reads as "no default" rather than "a
> default points at something missing". A model belonging to a different
> connection gets its own wording, because that case is repairable and a missing
> record is not.
>
> The guard's `setExecutionDefaults` entry is gone, and because 5.15 is the last
> Settings phase the assertion inverts: it now pins the exact set of seven
> permitted writes, derived from the API module so it cannot drift on either
> side. See `AVA_Phase_5_15_Defaults_UI.md`.

**Cross-phase notes.**

- **Two primitives are missing from `ui-core`, not one.** There is no `Select`
  and no checkbox/toggle. 5.12 needs a `Select` for `provider_id` *and* a
  boolean control for `enabled`; 5.13 needs `Select` again for hosting mode and
  the connection binding; 5.15 needs three `Select`s. Adding both in 5.12 keeps
  a single implementation rather than three near-duplicates. `Input` and
  `Textarea` already exist and cover the text fields.
- A confirmation pattern for destructive actions does not exist, though no
  Settings resource has a `DELETE` endpoint, so this is unlikely to be needed.
- `SettingsInventory` has an unused `renderActions` slot and
  `monospaceId` escape hatch. The management phases will fill the first; the
  second may turn out to be unnecessary, in which case remove it rather than
  leaving an unused prop.
