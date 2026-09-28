# AVA Phase 5.14 — Runtime Management UI

Phase 5.14 turns the Runtimes section from a read-only inventory into a
management surface, on the foundation 5.11–5.13 established: `SettingsModal`,
`SettingsInventory`, `useSettingsForm`, `useSettingsResource`,
`settingsErrorMessage`, and the generic `Select` / `Checkbox` / `Input`
controls. It adds no new UI control and no new dependency.

It adds **no** delete or remove action, no runtime options, and no live
execution behaviour. Defaults stays read-only and the architecture guard still
refuses its write.

## 1. Scope

```text
Main Navigation -> Settings -> Runtimes -> Add / Edit -> modal dialog
```

| Concern | Decision |
| --- | --- |
| Inventory actions | Add Runtime; Edit per row (enabled and disabled) |
| Add modal | `SettingsModal`, the four domain fields |
| Edit modal | same fields, identity and type frozen |
| `runtime_type` | known types from discovery **plus** a custom escape |
| Registry availability | stated per row, derived from discovery, never a save gate |
| Delete / remove | **not** offered |
| Defaults | unchanged, read-only |

Feature logic stays in `@ava/settings-core`. Neither shell implements any part
of it, and no runtime form was added to `web`, `desktop`, or `workspace`.

## 2. The rule that shaped this phase

Phase 5.6 decided `runtime_type` is an opaque adapter kind, and Phase 5.7
persisted it as `TEXT NOT NULL` with **no vocabulary check**, specifically so
the schema would not decide which runtimes are installed:

> Hard-coding the registry keys at the database layer "would make the schema
> decide which runtimes are installed, and would reject a legitimately
> configured `langgraph` or `agentcore` instance before any code runs."

So the UI must not be stricter than the backend. Concretely:

- `runtime_type` is a **select with an escape hatch**, not a closed select. The
  registered keys are a convenience list.
- An unregistered type is creatable, and no validation, help text, or error
  claims otherwise.
- No type is hard-coded in the frontend. The list comes from `GET /runtimes`,
  which today reports `native` and `openhands`. `langgraph` and `agentcore`
  appear in tests only as *values the operator types*, never as options the
  form invents.

This is deliberately the opposite of 5.13. There, `provider_connection_id` is a
closed select with no escape hatch, because the backend **does** enforce that
relationship and a free-text value could only produce a broken model. Here the
backend enforces nothing, so the UI enforces nothing. The asymmetry is the
point, and it is the reason the two editors do not share a "type" component.

## 3. Add / Edit

Both flows use one `RuntimeConfigurationEditor`.

Create sends the full `CreateRuntimeConfigurationRequest`. Update sends
`UpdateRuntimeConfigurationRequest` with `runtime_configuration_id` as the
**path parameter** and `runtime_type` **echoed unchanged** — the contract
permits omitting it or resending the current value, and echoing makes the
preserved type explicit rather than implied by its absence.

Both `runtime_configuration_id` and `runtime_type` are rendered on edit as
read-only text inputs. There is no identity control and no type control, so
`native → openhands` under the same stable id is not merely rejected, it is
unreachable.

### Unknown stored types cannot be coerced

5.13 had to teach a closed select to preserve a value it did not recognise,
because `hosting_mode` had to stay editable. This phase does better by not
needing that guard at all: `runtime_type` is immutable, so it is never
round-tripped through a list of options. A stored `langgraph` is displayed
verbatim, and there is no control present that could rewrite it. Tests assert
both the displayed value and that no combobox exists in the edit dialog.

## 4. Runtime type selection

Discovery is `GET /runtimes`, which reports the keys in AVA's `RuntimeRegistry`
as `runtime_info.runtime_id` with an optional adapter display name. The select
uses the **key as the value** and appends the registered display name as
secondary text — `native — AVA Native Runtime` — because the value is what a
persisted `runtime_type` is compared against.

| Situation | Control |
| --- | --- |
| Editing | read-only `Input`, exact stored value |
| Creating, discovery answered | `Select` of registered keys + "Other runtime type…" |
| "Other" chosen | extra `Input` for an arbitrary type |
| Discovery failed, empty, or still in flight | plain `Input` |

The custom field's visibility tracks an explicit "chosen" flag as well as the
value, because choosing the escape hatch clears the value — inferring the mode
from the value alone would hide the field the instant it was asked for. The
value test additionally covers discovery answering *after* the operator started
typing, so a late answer cannot blank a value already entered. If a custom type
later turns out to be registered, the field collapses back into the select.

> **This is a bug found in 5.12 and fixed here.** The 5.12 provider editor had
> the value-only inference, so its "Other provider type…" escape hatch could
> never appear and a provider type outside the discovered list was
> unreachable. The 5.12 form had no test covering that path. The fix is applied
> to both editors and the provider form gained two regression tests, verified to
> fail against the old code.

## 5. Runtime availability presentation

The inventory states, on a separate line from `enabled`, whether the adapter
kind is currently in the registry: `Registered runtime` or
`Not currently registered`.

Three deliberate constraints:

- **It says "registered", not "available".** Discovery answers one narrow
  question — is this key in `RuntimeRegistry` — and the registry key is a
  lookup for an already-constructed port, not a guarantee that a configured
  instance is usable. Nothing in Settings supplies an endpoint, a credential,
  or the composition-owned policy objects an adapter needs. A match does not
  promise the runtime will work; a miss does not mean the record is invalid.
- **Unknown is not "no".** The line is omitted entirely while discovery is
  loading *and* when discovery could not be reached. A failed lookup and an
  empty registry both yield an empty list, and only the second may be reported
  as not-registered; conflating them would assert something false about every
  configured runtime on screen.
- **It never gates a save.** Registration is not a create or edit prerequisite,
  and a configuration whose adapter is not registered stays fully editable.

It is also kept off the `association` line, which shows the `runtime_type`
itself, so the record's own data is never confused with live registry state.

## 6. What is deliberately absent

- **Delete / remove.** A record is retired by being disabled, so it stays
  findable and re-enablable.
- **Row-level enable/disable.** `enabled` is a modal field, so every change is
  an explicit save. Asserted in the workspace test.
- **Runtime options.** Phase 5.6 intentionally added no configuration bag, so
  there is no executable, host, endpoint, workspace path, or per-adapter
  settings field. OpenHands' constructor inputs are composition-owned policy
  objects, not reusable instance settings.
- **Model, provider, credential, or authority fields.** Tests assert these
  labels are absent from the dialog, matching the 5.10 rule that posting them
  yields `422`.
- **Anything execution-facing.** `RuntimeRegistry`, `RuntimeResolver`,
  `AgentPort`, `RunService`, execution profiles, and defaults resolution are
  untouched. Saving a configuration mutates no live behaviour; 5.16 makes
  configuration authoritative.

## 7. Architecture guard

Narrowed to allow exactly the six Settings writes that exist — provider, model,
and runtime create/update. `setExecutionDefaults` is the only remaining
forbidden write, so the list is one entry wide and reaching for defaults
editing ahead of 5.15 fails the build. Verified by temporarily adding a file
that calls `setExecutionDefaults` and confirming the guard fails.

The delete/remove and non-GET-transport guards continue to span all three
records.

## 8. Tests

`src/runtimes/runtime-management.test.tsx` (35) covers the inventory, both
flows, known/custom type selection, discovery failure, unregistered types, busy
and error behaviour, and the absence of every out-of-domain field.
`src/settings/settings-workspace.test.tsx` now narrows its read-only assertion
to Defaults alone, checks all three managed sections for delete/remove, and
asserts no enabled checkbox appears outside a dialog. `src/providers/provider-management.test.tsx`
gained the two escape-hatch regression tests described above.

## 9. Next: what this changes for 5.15

Defaults editing is the one write the guard still refuses. Three things 5.14
established that 5.15 should carry forward:

1. **`runtime_type` is not a lookup key.** 5.7's finding 1 says the defaults
   record must validate against `runtime_configuration_id`, never against
   `RuntimeRegistry` keys or `runtime_type` values. The UI's registry line is
   display-only, and 5.15 must not turn it into a picker: a default must be
   choosable from *configured* runtimes, and a configured runtime whose adapter
   is unregistered is still a valid choice.
2. **Unknown is not absent.** The loading/unavailable distinction added here
   matters more in 5.15, which must reach into the provider, model, **and**
   runtime inventories at once to populate three selects. Each can fail
   independently, and a failed lookup must not silently produce an empty
   required select.
3. **A default may reference a disabled record.** 5.8 validates that a default
   points at an *enabled* record. So the 5.15 select must include disabled
   records — showing their state — or a stored default pointing at a
   since-disabled runtime would become unsaveable, the same trap 5.13 hit in
   reverse when its create-only gate blocked editing an existing model.
