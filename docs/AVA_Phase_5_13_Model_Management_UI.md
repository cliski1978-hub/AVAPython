# AVA Phase 5.13 — Model Management UI

Phase 5.13 turns the Models section from a read-only inventory into a
management surface, on exactly the foundation 5.12 established: `SettingsModal`,
`SettingsInventory`, `useSettingsResource`, `settingsErrorMessage`, and the
generic `Select` / `Checkbox` / `Input` controls. It adds no generic UI control
and no new dependency.

It adds **no** delete or remove action, no model discovery, no provider
creation, no runtime, no defaults, and no live execution behaviour. Those
sections stay read-only and the architecture guard still refuses their writes.

## 1. Scope

```text
Main Navigation -> Settings -> Models -> Add / Edit -> modal dialog
```

| Concern | Decision |
| --- | --- |
| Inventory actions | Add Model; Edit per row (enabled and disabled rows) |
| Add modal | `SettingsModal`, the seven domain fields plus capabilities |
| Edit modal | same fields, `model_id` and relationship frozen |
| Provider relationship | closed select sourced from Settings providers |
| Declared capabilities | fixed eight-checkbox fieldset, contract-shaped |
| Delete / remove | **not** offered |
| Runtime / defaults | unchanged, read-only |

Feature logic stays in `@ava/settings-core`. Neither shell implements any part
of it, and no model form was added to `web`, `desktop`, or `workspace`.

## 2. The two relationships this form is easy to get wrong

The model form touches two different provider concepts, and Phase 5.4's
persistence was explicit that they must not be confused:

- `/settings/providers` — **configured** provider connections. This is the
  only legal source of a model's `provider_connection_id`.
- `/model-providers` — **discovery** of the provider types the backend
  supports. 5.12 uses this for a provider's own type field. It has nothing to
  do with choosing which configured connection a model runs on.
- `/models` — **discovered** catalog of models a provider offers. Not a source
  of model IDs either.

So the connection select is populated from `listProviderConnections()`, with the
option value `provider_connection_id` and the option label `display_name`.
There is no free text, no "Other…", and no inline provider creation, because a
model that points at an unconfigured connection cannot be used or validated.

A disabled connection stays **visible** — it is still configured, and hiding it
would make existing models look orphaned — but is disabled as a selection for a
new model. This is stricter than the backend, which currently checks only that
a connection exists:

> backend `ModelConfigurationService` `_require_provider_connection` verifies
> existence, not `enabled`. A disabled connection is still accepted by the API.
> The 5.13 UI closes that gap for new configurations without contradicting the
> API, which remains the enforcement point if a caller ignores the form.

## 3. Add / Edit

Both flows use one `ModelConfigurationEditor`.

Create sends the full `CreateModelConfigurationRequest`. Update sends
`UpdateModelConfigurationRequest` with `model_id` as the **path parameter** and
the relationship **echoed unchanged**:

- `model_id` — read-only on edit, and never present in the update body. It is
  the identity, and Phase 5.5 made it immutable.
- `provider_connection_id` — read-only on edit, rendered as the resolved
  connection display name with the raw id as fallback, and echoed into the
  update body. Reassignment is out of scope for this phase.
- `provider_model_name` — opaque, nonblank, stored exactly as entered. No
  provider-specific formatting is imposed, because the backend relays it.
- `display_name`, `hosting_mode`, `capabilities`, `enabled` — editable.

Local validation is deliberately minimal: required fields, plus the three
pairwise distinctness rules Phase 5.4 documents. Credential syntax, duplicate
ids, and relationship integrity are the server's to report — the UI does not
pre-guess them, and a safe error is shown when the server disagrees.

One field carries one message, so where `model_id` could collide with both the
connection id and the provider model name, the connection conflict is reported
first rather than one silently overwriting the other.

## 4. Hosting modes and declared capabilities

`hosting_mode` is a closed `Select` over the three canonical contract values,
with friendly labels:

| Value | Label |
| --- | --- |
| `local` | Local |
| `company_hosted` | Company Hosted |
| `external` | External |

A closed select silently coerces a value it does not recognise to the first
option. That would quietly rewrite a stored hosting mode on the next save, so
the editor adds the record's own value as a visible
`… (not offered by this build)` option when it is not one of the three. The
value round-trips unchanged and the discrepancy is visible instead of silent.
The contract cannot produce this case today; the guard is cheap.

`capabilities` is a `ModelCapabilities` object — eight booleans plus
`contract_version`. It is edited as a fieldset of eight checkboxes, labelled
`Chat`, `Streaming`, `Tool calling`, `Structured output`, `Vision`,
`Embeddings`, `Reasoning`, `Code specialization`. The vocabulary is fixed in
`modelCapabilities.ts` and the architecture test cross-checks the labels against
`ModelCapabilities` in `@ava/contracts`, so the UI cannot drift from the
contract. Conversion is total in both directions: every flag is always present
in the payload, so a flag is never dropped by omission.

The inventory summarises capabilities compactly (`chat · stream`), and states
`No declared capabilities` when nothing is declared rather than leaving the
line blank.

## 5. What is deliberately absent

- **Delete / remove.** Configuration records are retired by being disabled, so
  they stay findable and re-enablable. Deleting a model configuration that a
  saved run refers to is a Phase 5.14+ concern.
- **Row-level enable/disable.** `enabled` is a modal field, so every change
  goes through one explicit save. A checkbox in a table row makes an accidental
  toggle too easy.
- **Model discovery.** `provider_model_name` is typed. The configured ID space
  is the operator's, and binding it to a live catalog query would make Settings
  depend on provider reachability.
- **Provider creation.** Handled in Settings → Providers, where the credential
  lives. 5.13 reads that inventory, never writes it.
- **Runtime / defaults / execution.** Untouched. Nothing in this phase changes
  which runtime a model runs on or how execution profiles resolve.

## 6. Shared form lifecycle

`useSettingsForm` was extracted from the 5.12 provider editor during 5.13,
because the model editor would otherwise duplicate its submit lifecycle. It
owns values, field errors, validation, busy state, duplicate-submit refusal,
safe error mapping, and close-during-save protection. Both editors now use it,
so the two sections cannot drift on those behaviours.

It also cleared a stale comment: the inventory's `renderActions` slot is now
supplied by providers **and** models, and only runtimes and defaults omit it.

## 7. Sections affected

| Section | Change |
| --- | --- |
| Providers | unchanged by 5.13; refactored onto the shared hook |
| Models | Add/Edit modal, closed relationship select, capability fieldset |
| Runtimes | unchanged, read-only |
| Defaults | unchanged, read-only |

`ModelConfigurationsSection` loads the model list and the provider list
separately. A provider-list failure does not hide models: the inventory falls
back to showing raw connection ids and editing stays possible. The modal reads
the already-loaded list, so opening it issues no second request.

## 8. Tests

`frontend/packages/settings-core/src/models/model-management.test.tsx` (28) and
`frontend/packages/settings-core/src/state/useSettingsForm.test.tsx` (4) cover
the inventory and both flows, and pin the relationship rules: option values are
ids, labels are display names, disabled connections are visible but
unselectable, edit never repoints a relationship, `model_id` is never in the
update body, and an absent connection list blocks creation but never an edit of
an existing model.

`frontend/packages/settings-core/src/settings.architecture.test.ts` was
narrowed to allow exactly the provider and model writes, and extended with the
capability-vocabulary check.

## 9. Next

5.14 (runtime management) and 5.15 (execution defaults) follow the same shape.
Neither may add a delete action or a row-level enable toggle, and 5.14's runtime
form will face the same closed-select coercion question this phase had to guard.
