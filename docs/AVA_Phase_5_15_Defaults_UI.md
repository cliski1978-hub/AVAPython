# AVA Phase 5.15 — Defaults UI

Implements the Settings surface for `ApplicationExecutionDefaults`, the
singular record Phase 5.8 defined and Phase 5.10 exposed. The Defaults section
is now the fourth and last Settings section that can be edited.

## 1. What this phase adds

Two files, plus a rewritten section:

| File | Role |
| --- | --- |
| `src/defaults/defaultChoices.ts` | Turns three Settings inventories into three closed selects, and keeps "unknown" distinct from "empty". |
| `src/defaults/ExecutionDefaultsEditor.tsx` | The one modal. Handles both first-time configuration and later changes. |
| `src/sections/ExecutionDefaultsSection.tsx` | Loads `/settings/defaults` plus the three inventories, renders the read-only display, hosts the modal. |

The section owns the three inventory loads rather than the editor. The read-only
display resolves stored ids to configured display names, so it needs the same
data; loading it in the section means the editor opens with populated selectors
instead of flashing three spinners.

## 2. There is no create/update branch

Phase 5.8 made the repository singular — `get` and `set`, no list, no delete —
and 5.10 exposed exactly one write, `setExecutionDefaults`. Configuring defaults
for the first time and changing them later are the same operation against the
same single row, so the modal takes the current values when they exist and empty
ones when they do not.

The only difference is wording, and the wording follows from the domain rather
than from the operation:

- `configured: false` → **Configure Defaults**
- `configured: true` → **Edit Defaults**

There is deliberately no **Add Default**. There is no such thing as a second
record to add, and an "Add" affordance on a singular resource would promise
something the API cannot deliver.

## 3. Selector sources are configured records, never discovery

| Field | Value | Source |
| --- | --- | --- |
| Default provider connection | `default_provider_connection_id` | `listProviderConnections()` → `/settings/providers` |
| Default model | `default_model_id` | `listModelConfigurations()` → `/settings/models` |
| Default runtime | `default_runtime_configuration_id` | `listRuntimeConfigurations()` → `/settings/runtimes` |

`/model-providers`, `/models`, and `/runtimes` are **not** used. They report
what the host happens to support; `/settings/*` reports what the operator has
configured. A default is a persisted reference that 5.8 validates against
configured records, so sourcing a default id from discovery would produce a
value the API rejects — or worse, one that happens to be accepted and silently
means something else.

This is the opposite of 5.14's custom runtime type, and the reason is worth
stating because the two look alike. In 5.14 the backend did not validate the
value, so a typed entry was legitimate. Here every field is validated, so a
typed value could only ever name something that does not exist. All three
fields are closed selects with no free-text escape.

Whether the selected runtime's adapter is currently registered is **not**
checked. 5.7 established that registry membership and configured-instance
identity are different things, and 5.8 validates only against configured
records.

An architecture test asserts this scoping directly, so a later phase cannot
quietly reach for discovery when it is easier.

## 4. "Unknown" is not "empty"

This is the problem that shapes most of the phase. `useSettingsResource`
reports a failed request as `error` and a successful empty list as `ready` with
`[]`. Both produce zero records, so a select that renders an empty list in both
cases tells the operator they have no runtimes when in fact AVA could not ask.

Every source therefore keeps four states, and two of them block a save:

| State | Records | Blocking | Why |
| --- | --- | --- | --- |
| `loading` | none | yes | The answer is not in yet. |
| `unavailable` | none | yes | The answer is unknown; the request failed. |
| `empty` | none | no | A true answer. "You have nothing configured." |
| `ready` | present | no | A true answer. |

`blocking` is a separate field from `status` precisely so a caller does not have
to remember the mapping. A save while any source is blocking would be a guess,
so the primary action is disabled and the affected field carries its own
message and a **Retry** button that re-runs only that source.

The consequence worth noting: `empty` is the only state that renders as an empty
list, and it also renders the explanatory sentence ("No runtime configurations
are configured."). `unavailable` never does.

## 5. Stored references outlive the inventory that justified them

A default may name a record that has since been disabled, and the API can
return a default whose id is not in the currently loaded list at all. Neither
may be coerced away: the operator has to see what is actually stored in order to
decide what to change it to.

So each option builder appends the stored id when it is missing, labelled so
the situation is legible, and disabled so it cannot be re-chosen:

- **absent from a successful response** → `<id> (not present in current configuration)`
- **present but disabled** → shown with its real name, disabled
- **model from another connection** → `<name> (belongs to a different provider connection)`
- **no answer yet** → `<id> (still loading)` / `<id> (inventory unavailable)`

The model case is separated from the missing case because they are different
problems. A dangling id is a broken reference; a model from another connection
is a repairable mistake, and the label has to say which one it is rather than
implying the record is gone.

The last row is the one that constrains the others: "not present" is a claim, and
only a `ready` or `empty` source can support it. A `loading` or `unavailable`
source produces an empty record list, which is indistinguishable from absence
unless the status is checked — see the first bug in section 8.

The read-only display follows the same rule: it resolves the configured display
name and falls back to the raw id. A reference whose record cannot currently be
found still renders the id rather than blank — blank would make stored
configuration look unset. When the label *does* resolve, the id is kept as
secondary text, because the display name is a convenience and the stored
reference is the thing that has to stay auditable. The secondary line is
suppressed when it would only repeat the value.

## 6. Model filtering and the provider reset

`ModelConfiguration.provider_connection_id` is a persisted relationship, and 5.8
rejects a default whose model belongs to a different connection. The select is
filtered to the selected connection so that pairing cannot be built in the first
place, rather than being discovered as a `422`.

Two consequences:

- With no provider chosen the model list is **empty**, not "all models".
  Offering everything would invite the mismatch the filter exists to prevent,
  and the field says why it is empty.
- Changing the provider clears a model that no longer belongs, rather than
  auto-selecting the first matching model. 5.13 made the relationship immutable,
  so there is no in-place repair; clearing forces an explicit choice, which is
  the only option that cannot be wrong about intent.

Opening the dialog alone still repairs nothing — a stored mismatch is displayed,
not silently corrected.

## 7. Validation

Checked client-side so the operator sees the problem before a round trip, and
in the backend's own order — existence, then enabled, then compatibility — so
the first message is the one worth fixing first:

| Field | Rules |
| --- | --- |
| Provider | required · exists in the loaded inventory · enabled |
| Model | required · exists · belongs to the selected connection · enabled |
| Runtime | required · exists in the loaded inventory · enabled |

One message per field. A field can be wrong in more than one way — a model from
another connection is usually disabled too — and stacking both in one control is
noise.

No discovery-membership validation appears here, and this is a deliberate
omission rather than an oversight: 5.8 validates against configured records, so
a runtime whose adapter is not currently registered is still a valid default.

## 8. Errors and busy behaviour

- Inventory failure → field-local message plus a per-source retry. The section
  itself does not blank: one failed inventory is not a failed section, and the
  other two references remain readable.
- Defaults-record failure → the section's own `SettingsError` with a retry,
  because there is nothing to display at all.
- Save failure → a modal-global message. Field-local errors are reserved for
  client-side problems the client can describe.
- A thrown non-`Error` value falls back to a fixed message, never an
  interpolated value, via the shared `settingsErrorMessage`.

While a save is in flight the primary action is disabled, a second click cannot
produce a second request, and dismissal is blocked. `useSettingsForm` owns all
of this; the editor adds no state of its own.

On success the modal closes and **only** `/settings/defaults` is re-read. The
three inventories are unchanged by a defaults write, and re-fetching them would
flicker the display for no reason.

### Two bugs found by review, not by the first test run

Both were caught after the suites were already green, and both are the same
underlying mistake: making a claim the UI does not have the facts to support.

1. **A stored id was labelled "not present in current configuration" while its
   inventory was still loading or had failed.** The option builders were handed
   only the record list, which is empty in all three of `loading`,
   `unavailable`, and `empty`, so they could not tell them apart and fell
   through to the missing label. The consequence was concrete: an operator whose
   runtime list had failed to load would be told their working default pointed
   at a record that does not exist, and would replace it. The builders now take
   the `ChoiceSet` and the wording is `still loading` / `inventory unavailable`
   in those states. Covered by four tests.

2. **An empty *source* and an empty *filtered* list both rendered as the same
   prompt.** With no models configured at all, the model field said "choose a
   provider connection to see its models" — advice that sends the operator down a
   dead end, because no choice would reveal a model that does not exist. The
   explanation is now chosen from the most specific true statement, testing
   `empty` before the filter case.

A third, smaller one came from a test rather than review: the read-only display
printed the raw id twice when the display name could not be resolved, since the
value fell back to the id and the secondary line repeated it. That reads as two
different things, so the secondary line is now suppressed when it would only
echo the value.

## 9. Unchanged

Nothing outside `@ava/settings-core` was touched.

- `ExecutionDefaults` remains persisted configuration only. No run behaviour
  changed; Phase 5.16 makes these values authoritative.
- `RunService`, `ExecutionSelector`, `ExecutionProfile`, `RuntimeRegistry`,
  `RuntimeResolver`, and `ModelOrchestrator` are untouched.
- `ExecutionProfile` is unchanged, as 5.8 established.
- Web and Desktop remain thin shells over the workspace.
- No delete or remove affordance anywhere: retirement in this domain is done by
  disabling, and the API exposes no delete.

## 10. Tests

**`src/defaults/defaultChoices.test.ts`** (21 tests) — the option-shaping rules:
the four states and which of them block, disabled-but-visible records, stored
ids that are missing versus present-but-from-another-connection, provider
filtering, the display-name fallbacks, and the three cases in which a stored id
must *not* be labelled absent because no answer arrived.

**`src/defaults/defaults-management.test.tsx`** (19 tests) — what only
integration can check: the unconfigured empty state, `configured: false` never
rendering as an error, id fallbacks when an inventory is unavailable, the
closed-select shape, provider-reset clearing the model, preserved missing
references, the exact `setExecutionDefaults` payload, one-message-per-field
validation, blocking plus per-source retry, busy/dismissal behaviour, and safe
handling of a thrown string.

**`src/settings.architecture.test.ts`** (15 tests) — the write set is now derived
from the API module rather than restated, so it fails if a write is added on
either side without the other:

- the Settings API exposes exactly the seven writes
- the surface reaches every one of them and no other wrapper
- every imported wrapper name is actually exported
- the defaults editor references no discovery endpoint
- no non-GET request is spelled out, and no delete or remove is called

The previous 5.14 guard forbade a named not-yet-opened write. With 5.15 there is
no later phase in Phase 5, so the assertion inverts: it pins the exact allowed
set, which also stops a future phase from quietly adding an eighth write.

**`src/settings/settings-workspace.test.tsx`** (24 tests) — the boundary
narrowed from "Defaults is the last read-only section" to the specifics of a
singular resource: an edit action, never an add action, and no delete or remove
anywhere including Defaults.

`fireEvent` is used throughout; no `@testing-library/user-event` dependency was
added.

## 11. Validation

```text
pnpm --filter @ava/settings-core test
191 passed

pnpm test
627 passed, 4 skipped, 0 failed

pnpm lint
All 10 packages clean (tsc --noEmit)

pnpm build:web
dist/assets/index-B5rVG0Jv.js    650.77 kB
dist/assets/index-DuWeGZp6.css     3.63 kB

pnpm --filter @ava/desktop build
dist/assets/index-B5rVG0Jv.js    650.77 kB
dist/assets/index-DuWeGZp6.css     3.63 kB

git diff --check
Clean
```

The CSS hash is unchanged from 5.14 (`index-DuWeGZp6.css`), confirming no
styling was added. Both shells produce byte-identical bundles, confirming the
feature lives entirely in the shared package. The JS hash moved from
`index-C3SR2dNK.js` to `index-B5rVG0Jv.js` as expected from the new section
logic.

## 12. Implications for Phase 5.16

The defaults record is now editable, and 5.8 left two facts for 5.16:

1. **A stored default can become invalid after the fact.** `set` rejects
   disabled or missing records, but nothing re-validates a default when the
   record it names is disabled later. 5.13 already accepts this for models
   whose connection was disabled afterwards, and the editor now makes it
   *visible* — a stored disabled record stays on screen rather than being
   dropped — so the operator has a chance to repair it. A resolver must still
   handle it at resolution time rather than trusting the record.
2. **Resolve by configured identity, never by adapter key.** The editor stores
   `runtime_configuration_id`, not a `RuntimeRegistry` key, and 5.15's
   architecture test locks the source of that value to `/settings/runtimes`.
   The registry adapter is reached through `RuntimeConfiguration.runtime_type` —
   the same join 5.6 and 5.7 established.

One thing this phase deliberately does not decide: the precedence question
between a persisted default and an environment or bootstrap value. That remains
Phase 5.17's, as 5.8 recorded.
