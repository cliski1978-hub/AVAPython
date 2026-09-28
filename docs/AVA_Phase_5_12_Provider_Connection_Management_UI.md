# AVA Phase 5.12 — Provider Connection Management UI

Phase 5.12 turns the Providers section from a read-only inventory into a
management surface. It uses the Phase 5.11 foundation as-is — the section
structure, `SettingsInventory`, `SettingsModal`, and the shared
loading/error/empty states — and adds the two generic form primitives that
5.11 identified as missing.

It adds **no** delete or remove action, no connectivity test, no secret input,
and no model, runtime, or defaults workflow. Those sections stay read-only, and
the architecture guard still refuses their writes.

## 1. Scope

```text
Main Navigation -> Settings -> Providers -> Add / Edit -> modal dialog
```

| Concern | Decision |
| --- | --- |
| Generic `Select` | added to `@ava/ui-core` |
| Generic enabled control | `Checkbox` added to `@ava/ui-core` |
| Provider inventory actions | Add Provider; Edit per row |
| Add modal | `SettingsModal`, all six domain fields |
| Edit modal | same fields, identity frozen |
| Model / runtime / defaults | unchanged, read-only |

Feature logic stays in `@ava/settings-core`. Generic controls live in
`@ava/ui-core`. Neither shell implements any part of it, and no provider form
was added to `web`, `desktop`, or `workspace`.

## 2. Generic `Select`

`frontend/packages/ui-core/src/components/Select.tsx`

Built on the native `<select>` rather than a custom listbox. That choice
inherits keyboard behaviour, screen-reader support, and mobile pickers for free,
and it keeps a second UI dependency out of the repo.

- `label` renders a real `<label htmlFor>` associated with the control.
- `value` / `onChange` make it controlled.
- `options` is a generic `SelectOption[]` (`value`, `label`, `disabled`) —
  nothing about providers is baked in.
- `disabled`, `placeholder`, `helpText`, and `error` are supported.
- `helpText` / `error` are linked with `aria-describedby`, and `error` also sets
  `aria-invalid`.

### An accessibility fix made here

`Input` and `Select` previously wrapped the control in a `<label>` and put the
label text in a `<span>`. Once help text was added, that produced an accessible
name of "Provider type Installed provider types." — the guidance was being
announced as part of the field's name. Both components now render a standalone
`<label htmlFor>` with the message outside it, so the accessible name is the
label and the guidance is a description. The tests assert this, because it is
easy to regress.

## 3. Generic enabled control

`frontend/packages/ui-core/src/components/Checkbox.tsx`

A labelled checkbox, not a switch: `enabled` is plain on/off configuration.

- `checked` / `onChange` make it controlled.
- The label is a real `<label htmlFor>`, so the accessible name is the visible
  text and clicking the text toggles the control.
- `disabled` and `helpText` are supported; help text is linked with
  `aria-describedby`.
- The native `input[type=checkbox]` stays in the accessibility tree, so
  keyboard, screen-reader, and form semantics remain correct.

The provider form labels it **Enabled**, with help text stating that it means
availability for selection, not an access or authorization setting. There is no
"Allow access" phrasing anywhere.

## 4. Provider inventory actions

`frontend/packages/settings-core/src/sections/ProviderConnectionsSection.tsx`

- **Add Provider** sits in a section header above the inventory, and is also
  offered from the empty state, so a first-run operator with zero connections has
  a way in.
- **Edit** appears per row, via the `renderActions` slot that 5.11 left for this
  phase. Its accessible name is `Edit <display name>`, which keeps several Edit
  buttons distinguishable to a screen reader.
- No Delete and no Remove, on the rows or anywhere else.
- Disabled connections stay visible *and* stay editable.
- Enabling and disabling is a field of the edit form, not a row-level mutation,
  so a row and the form that edits it can never disagree about what a status
  change does. The architecture guard keeps asserting this.

The row gained a dedicated line for the stable connection id, because 5.11 only
showed the id when no association or metadata was present — which, for a
provider, it never is. Rows now show:

```text
Acme Primary                              [Enabled]
acme-primary
acme · https://api.acme.test · env:ACME_API_KEY          [Edit]
```

`SettingsInventory` gained `data-testid="settings-inventory-entry-id"` and
`settings-inventory-entry-meta` so tests can address the two lines directly
rather than by guessing at text.

## 5. Add Provider

`ProviderConnectionEditor` with `record = null`. Fields, in order:

| Field | Control | Required | Notes |
| --- | --- | --- | --- |
| Connection ID | `Input` | yes | user-supplied, trimmed |
| Provider type | `Select` (or `Input`) | yes | see §7 |
| Display name | `Input` | yes | trimmed |
| Endpoint | `Input` | no | opaque, see §9 |
| Enabled | `Checkbox` | — | defaults to `true` |
| Credential reference | `Input` | no | see §10 |

All state is local `useState` inside the editor. The section holds only which
record is open (`null` | `"new"` | record). There is no global state, no store,
and no persistence of a draft.

## 6. Provider type source

`frontend/packages/settings-core/src/providers/useProviderTypeChoices.ts`

Source: **`GET /model-providers`** (discovery). That endpoint reports the
provider adapters currently installed in AVA, which is the set of types a new
connection most plausibly references.

The distinction the phase requires is preserved exactly:

```text
/settings/providers   = configured connections (the inventory, the source of truth)
/model-providers      = installed adapter types (the create form's options)
```

They are never merged. A test asserts the select offers `acme` and `openai` from
discovery but **not** `acme-primary`, a configured connection id — a configured
record must never masquerade as a provider type. An installed adapter with zero
configured connections is a normal state, and a persisted disabled connection
stays visible.

Three details are deliberate:

1. **The select is not the only way in.** Discovery reports availability, not
   configuration. The backend does not validate `provider_id` against the
   installed set — it is a free non-blank string — so a connection for an
   adapter that is temporarily unavailable must still be creatable. The select
   therefore ends with **"Other provider type…"**, which swaps in a text input.
   Restricting creation to currently-installed types would make the frontend
   stricter than the domain with no product reason.
2. **If discovery fails or returns nothing, the field degrades to a plain text
   input** rather than presenting an empty select with no way forward.
3. **Edit never calls discovery at all.** The type is frozen when editing, so
   `useProviderTypeChoices` takes an `enabled` flag and issues no request. A test
   asserts `getModelProviders` is not called on the edit path.

## 7. Connection ID UX

`provider_connection_id` is AVA-owned and stable. The backend requires it on
create and the update contract takes it as a **path parameter**, so there is no
API to ask for a generated one and no existing frontend ID-generation convention
to reuse. Inventing client-side UUIDs would produce ids nobody can read or type
later.

So the field is user-supplied, like the rest of AVA's configuration keys, with
help text that separates it from the display name:

> Stable identity AVA uses for this connection — a short key, not a label.
> Selectors show the display name.

The placeholder is `acme-production`. The domain rule that the connection id
must differ from the provider type is checked client-side, because the backend's
generic "field is required" message would not tell the operator which of the two
values to change.

## 8. Immutable fields on edit

`provider_id` is immutable per the 5.10 contract, and
`provider_connection_id` is the record's identity. On edit both are frozen:

- **Connection ID** — an `Input` with `readOnly`. Not `disabled`: the value is
  real, so it stays focusable and selectable and the operator can read and copy
  it. Help text says it cannot be changed.
- **Provider type** — a `readOnly` `Input`, not a select, because there is
  nothing to choose. Help text says the type is immutable and the connection
  must be recreated to change it.

A test asserts `readOnly === true` on both, and that the type field is an
`INPUT` rather than a list on the edit path.

On submit the update payload:

- carries **no** `provider_connection_id` — it is a path parameter, so the
  request can only ever address the record the dialog was opened for;
- echoes `provider_id` unchanged, which the contract explicitly permits ("omit
  it, or resend the current value") and which makes the preserved type explicit
  in the payload.

A test asserts the payload contains no `provider_connection_id` key at all, so
identity cannot be rewritten even by a future refactor.

## 9. Endpoint

Optional, plain text, stored exactly as entered. There is **no** browser URL
validation and no `type="url"`, because Phase 5.2 deliberately did not force URL
semantics: future provider schemes may not be URLs. The field's help text says
so, and a test creates a connection with the endpoint `acme-internal:9000` to
prove the value is not parsed, normalized, or rejected.

## 10. Credential reference

`credential_reference` is editable configuration metadata, e.g.
`env:OPENAI_API_KEY`. Help text:

> Optional reference to a credential, e.g. env:OPENAI_API_KEY. This names where
> AVA resolves the secret — it is not the secret, and no secret is ever entered
> or stored here.

- No API key, password, token, or resolved-value field exists. A test collects
  every textbox label in the dialog and asserts none of `api key`, `apikey`,
  `password`, `secret`, or `token` appears.
- No password-masking widget is applied to the reference; masking would imply
  the field holds a secret, and it does not.
- The reference is displayed in the inventory row as-is, and never resolved in
  the browser.
- Syntax validation stays with the backend, which returns a designed message
  that surfaces in the modal's error slot.

## 11. No fake credential test

There is no "Test Connection" button. Phase 5.10 established that resolving a
credential from the environment proves only that the variable is set, not that
the provider is reachable, so a test-connection endpoint would report a
meaningless success. Nothing simulates connectivity.

## 12. Create and update flow

```text
Add Provider / Edit row
  -> SettingsModal opens (Add or Edit, prefilled on edit)
  -> local validation
  -> createProviderConnection / updateProviderConnection (typed wrappers)
  -> success: close the modal, then re-read /settings/providers
```

- Refresh is a **re-read**, not an optimistic patch: `useSettingsResource.reload`
  is called after the write resolves. The UI never shows server state it has not
  confirmed.
- Only the Settings surface reloads. No page reload, no application-wide
  refetch, and nothing outside the section is touched.
- Optional fields that were left blank are sent as `null`, never `""`, because
  the domain treats a non-blank string as a present value — an empty string would
  arrive as a real, meaningless endpoint.
- Text values are trimmed before submission.

## 13. Busy and double-submit protection

Busy state uses the existing `SettingsModal` / `Modal` support — there is no
second busy implementation.

While a write is in flight: the primary action is disabled and `aria-busy`, and
the secondary action is disabled by the modal. Dismissal is refused by the
editor's own `close()` guard, which returns early while busy — that is what stops
Escape and an overlay click from discarding a submit that is still running, and
it is independent of `Modal`, which does not suppress dismissal on its own.
Finally `save()` returns immediately if called again, so a second click cannot
issue a second write. A test uses a promise it settles by hand, asserts the
primary button is disabled, clicks it again, and asserts the wrapper was still
called exactly once — and that the typed values survived the wait. A second test
asserts Escape does not dismiss the dialog mid-flight.

## 14. Error behaviour

Reuses `settingsErrorMessage`, which was extended with an optional second
argument for a caller-supplied final sentence (the default is unchanged, so the
four read-only sections behave exactly as in 5.11).

- A backend `ErrorResponse` message is shown as-is, because 5.10 already returns
  operator-facing sentences: `A provider connection with that ID already exists:
  openai-prod`, `provider_id is immutable for acme-primary`, and so on.
- Anything else is reduced to a fixed `AVA could not save this provider. Try
  again.`
- A test throws an `Error` carrying `connect ECONNREFUSED 127.0.0.1:8000 … at
  main.py:42` and asserts neither the host, the port, nor the file path reaches
  the dialog.

On failure the modal stays open, the operator's input is preserved, and the
message renders in the modal's existing `role="alert"` slot. Client validation
covers only what the domain states plainly — required id, required type,
required display name, and id ≠ type. Credential syntax, duplicates, and
immutability remain the backend's job.

## 15. Architecture-guard change

`frontend/packages/settings-core/src/settings.architecture.test.ts` was narrowed,
not removed. `WRITES_ADDED_BY_LATER_PHASES` lost exactly two entries:

```text
- "createProviderConnection"
- "updateProviderConnection"
```

and still lists `createModelConfiguration`, `updateModelConfiguration`,
`createRuntimeConfiguration`, `updateRuntimeConfiguration`, and
`setExecutionDefaults`, so drift into 5.13–5.15 still fails the build.

The transport guards are unchanged and still active: the surface never names an
HTTP verb, and never builds a request (`client.request(`, `fetch(`,
`XMLHttpRequest`, `WebSocket`, `EventSource` are all refused). Two guards were
added: no delete/remove action, and no direct request construction. Both scan
feature sources only, since test files legitimately spell the forbidden words
out in order to assert their absence.

## 16. Credential safety

- The only credential concept anywhere in the provider UI is the opaque
  `credential_reference`.
- No resolved value is requested, received, rendered, or cached. A test asserts
  no secret-shaped value appears in the inventory.
- Nothing is written to `localStorage`, `sessionStorage`, `indexedDB`, or
  cookies — the existing storage guard still holds.
- No state-management library was added.

## 17. Web and desktop parity

Neither shell was touched; `frontend/apps/web/src/App.tsx` and
`frontend/apps/desktop/src/App.tsx` remain byte-identical. Both builds emit the
same bundle hashes, which is the practical proof that there is one provider
implementation and not two:

```text
index-yo9NLsww.js   627.70 kB
index-DuWeGZp6.css    3.63 kB
```

The pre-existing Vite chunk-size warning (>500 kB) is unchanged and unrelated.

## 18. Models, runtimes, and defaults remain read-only

Their sections, inventory composition, and `useSettingsResource` wiring are
untouched. The 5.11 workspace test that asserted "no management control
anywhere" was narrowed to those three sections and a second test was added to
keep Delete and Remove out of Providers — the assertion moved with the phase
boundary instead of being deleted.

## 19. Effects on Phase 5.13

- **The model form has its primitives.** `Select` and `Checkbox` exist and are
  tested, so 5.13 adds a form rather than a control library. `ModelHostingMode`
  is a closed three-value enum, so it is a plain `Select` with no "other" option
  and no discovery dependency.
- **`provider_connection_id` is now a real chooser problem.** Phase 5.13 must
  populate a select of configured connections from `listProviderConnections`
  (Settings, not discovery), show each option as `display_name`, filter by
  `enabled` in the picker while still allowing a disabled connection to be
  *shown* as unavailable, and must not offer creating a connection inline.
- **The row actions pattern is settled.** A management section composes
  `SettingsInventory` + `renderActions` + `SettingsModal`; the descriptor model
  now has both an id line and a metadata line, so 5.13/5.14 need no inventory
  change.
- **A 5.11 note is now stale and should be read with this phase.** 5.11 recorded
  that provider type selection might need a free-text fallback; the reason is
  that the backend does not validate `provider_id` against installed adapters.
  5.13's provider selector has the opposite property — `provider_connection_id`
  *is* referentially validated — so it should be a closed select with no custom
  entry.
- **The `enabled` rule carries over.** A model whose provider connection is
  disabled is `degraded` with `PROVIDER_CONNECTION_DISABLED`, not `unavailable`.
- **Ordering still matters.** A model cannot be created before a connection
  exists, so the empty state for Models should point at Providers.
