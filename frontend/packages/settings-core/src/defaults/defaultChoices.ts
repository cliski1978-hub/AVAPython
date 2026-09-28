import type {
  ModelConfigurationResponse,
  ProviderConnectionResponse,
  RuntimeConfigurationResponse,
} from "@ava/contracts";
import type { SelectOption } from "@ava/ui-core";

import type { SettingsResourceState } from "../state/useSettingsResource";

/**
 * Turning three Settings inventories into three closed selects.
 *
 * The defaults editor is the first Settings surface that reads *other* sections'
 * data, and that is where its two hard problems live.
 *
 * **A failed lookup is not an empty inventory.** `useSettingsResource` reports
 * `error` for a failed request and `ready` with `[]` for a genuinely empty one.
 * Collapsing both into "no options" would tell the operator they have no
 * runtimes when in fact AVA could not ask. So every source keeps four distinct
 * states, and `blocking` marks the two in which a save must not proceed because
 * the answer is unknown rather than negative.
 *
 * **A stored reference outlives the inventory that justified it.** A default may
 * name a record that has since been disabled, and the API can return a default
 * whose id is not in the currently loaded list at all. Neither may be coerced
 * away: the operator has to see what is actually stored in order to decide what
 * to change it to. So each option builder appends the stored id when it is
 * missing from the records, labelled so the situation is legible, and disabled
 * so it cannot be re-chosen after the operator moves on.
 *
 * Only *new* choices are constrained. Phase 5.8 requires a saved default to
 * reference an enabled record, so an enabled record is selectable and a disabled
 * one is visible-but-unavailable — the same rule 5.13 used for provider
 * connections, and for the same reason: configuration history has to stay
 * readable.
 */

/** The four states a source can be in, none of them implied by another. */
export type ChoiceStatus = "loading" | "unavailable" | "empty" | "ready";

export interface ChoiceSet<TRecord> {
  status: ChoiceStatus;
  /** The mapped failure, for `unavailable` only. */
  error: string | null;
  records: TRecord[];
  /**
   * True when the answer is unknown — still loading, or unreachable — so a save
   * would be guessing. False for `empty` and `ready`, both of which are known
   * answers that may legitimately be acted on.
   */
  blocking: boolean;
}

/**
 * Normalise a resource state into a `ChoiceSet`.
 *
 * `pick` extracts the record list from whatever shape the response uses, so the
 * caller does not have to narrow the union itself.
 */
export function toChoiceSet<TData, TRecord>(
  state: SettingsResourceState<TData>,
  pick: (data: TData) => readonly TRecord[],
): ChoiceSet<TRecord> {
  if (state.status === "loading") {
    return { status: "loading", error: null, records: [], blocking: true };
  }
  if (state.status === "error") {
    return { status: "unavailable", error: state.error, records: [], blocking: true };
  }
  const records = pick(state.data);
  return {
    status: records.length === 0 ? "empty" : "ready",
    error: null,
    records: [...records],
    blocking: false,
  };
}

/**
 * Label for a stored id that a *successful* response did not contain.
 *
 * Only a `ready` or `empty` source can support this claim. While a source is
 * still loading or unreachable, the record's absence is unproven, and labelling
 * it "not present" would state a fact the UI does not have — the operator could
 * then conclude a working default is broken and replace it.
 */
export const missingRecordLabel = (value: string) =>
  `${value} (not present in current configuration)`;

/**
 * Label for a stored id whose inventory has not produced a usable answer.
 *
 * The id stays visible, because the reference exists whether or not it can be
 * resolved right now, but the wording says "unknown" rather than asserting
 * either presence or absence.
 */
function unresolvedLabel(choices: ChoiceSet<unknown>, value: string): string {
  return choices.status === "loading"
    ? `${value} (still loading)`
    : `${value} (inventory unavailable)`;
}

/**
 * The label for a stored id the operator cannot currently choose.
 *
 * Prefers the most specific true statement available: a mismatch if the record
 * was loaded and belongs elsewhere, "not present" if a successful response
 * omitted it, and "unknown" if no answer arrived at all.
 */
function storedLabel<TRecord>(
  choices: ChoiceSet<TRecord>,
  value: string,
  mismatch?: string,
): string {
  if (choices.status === "loading" || choices.status === "unavailable") {
    return unresolvedLabel(choices, value);
  }
  return mismatch ?? missingRecordLabel(value);
}

/**
 * Append the stored id when the options do not contain it.
 *
 * A stored value is never silently dropped: an empty select would render the
 * record as unset, which reads as "no default" rather than "a default points at
 * something I cannot see".
 */
function withStoredValue<TRecord>(
  options: SelectOption[],
  choices: ChoiceSet<TRecord>,
  storedValue: string,
  idOf: (record: TRecord) => string,
  describe?: (record: TRecord) => string,
): SelectOption[] {
  if (storedValue === "" || options.some((option) => option.value === storedValue)) {
    return options;
  }
  const record = choices.records.find((candidate) => idOf(candidate) === storedValue);
  const mismatch = record == null ? undefined : describe?.(record);
  return [
    ...options,
    {
      value: storedValue,
      label: storedLabel(choices, storedValue, mismatch),
      disabled: true,
    },
  ];
}

/**
 * Provider connections. Value is `provider_connection_id`; the label leads with
 * the configured display name and carries the provider type as secondary text.
 *
 * `provider_id` is shown but is never the value — a default references a
 * configured *instance*, not an adapter kind.
 */
export function providerOptions(
  providers: ChoiceSet<ProviderConnectionResponse>,
  storedValue: string,
): SelectOption[] {
  const options = providers.records.map((provider) => ({
    value: provider.provider_connection_id,
    label: `${provider.display_name} — ${provider.provider_id}`,
    // Visible but not choosable: a disabled record cannot be a new default.
    disabled: !provider.enabled,
  }));
  return withStoredValue(
    options,
    providers,
    storedValue,
    (record) => record.provider_connection_id,
  );
}

/**
 * Models, constrained to the chosen provider connection.
 *
 * `ModelConfiguration.provider_connection_id` is a persisted relationship, and
 * Phase 5.8 rejects a default whose model belongs to a different connection.
 * Filtering here means the operator cannot build that pairing in the first
 * place, rather than discovering it as a `422`.
 *
 * With no provider chosen there is no constraint to apply, so the list is empty
 * rather than "all models" — offering every model would invite the very pairing
 * the filter exists to prevent.
 */
export function modelOptions(
  models: ChoiceSet<ModelConfigurationResponse>,
  selectedProviderId: string,
  storedValue: string,
): SelectOption[] {
  const forProvider =
    selectedProviderId === ""
      ? []
      : models.records.filter(
          (model) => model.provider_connection_id === selectedProviderId,
        );

  const options = forProvider.map((model) => ({
    value: model.model_id,
    label: `${model.display_name} — ${model.provider_model_name}`,
    disabled: !model.enabled,
  }));

  if (storedValue === "" || options.some((option) => option.value === storedValue)) {
    return options;
  }

  /**
   * The stored model stays visible even when the filter excludes it, because
   * there are two different reasons and the operator needs to tell them apart:
   * the record is gone, or the record belongs to a different connection. The
   * second is a repairable mistake; the first is a dangling reference. Both are
   * shown, both are disabled, and neither is silently replaced.
   */
  return withStoredValue(
    options,
    models,
    storedValue,
    (record) => record.model_id,
    (record) =>
      `${record.display_name} (belongs to a different provider connection)`,
  );
}

/**
 * Runtime configurations. Value is `runtime_configuration_id`; the label leads
 * with the display name and carries `runtime_type` as secondary text.
 *
 * `runtime_type` is shown but is never the value, and the registry is never
 * consulted: a default names a configured instance, and 5.6/5.7 established that
 * the instance identity and its adapter kind are different things.
 */
export function runtimeOptions(
  runtimes: ChoiceSet<RuntimeConfigurationResponse>,
  storedValue: string,
): SelectOption[] {
  const options = runtimes.records.map((runtime) => ({
    value: runtime.runtime_configuration_id,
    label: `${runtime.display_name} — ${runtime.runtime_type}`,
    disabled: !runtime.enabled,
  }));
  return withStoredValue(
    options,
    runtimes,
    storedValue,
    (record) => record.runtime_configuration_id,
  );
}

/**
 * Human-readable name for the read-only display, falling back to the stored id.
 *
 * A default whose record cannot currently be found must still show the id it
 * holds, so the display never renders a blank where a reference exists.
 */
export function displayLabel<TRecord extends { display_name: string }>(
  records: readonly TRecord[],
  id: string,
  identityOf: (record: TRecord) => string,
): string {
  const match = records.find((record) => identityOf(record) === id);
  return match == null ? id : match.display_name;
}
