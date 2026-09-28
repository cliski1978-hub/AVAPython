import type { FormEvent } from "react";
import type { ApiClient } from "@ava/api-client";
import { setExecutionDefaults } from "@ava/api-client";
import type {
  ModelConfigurationResponse,
  ProviderConnectionResponse,
  RuntimeConfigurationResponse,
  SetApplicationExecutionDefaultsRequest,
} from "@ava/contracts";
import { Button, Select, defaultTheme, type SelectOption } from "@ava/ui-core";

import {
  modelOptions,
  providerOptions,
  runtimeOptions,
  type ChoiceSet,
} from "../defaults/defaultChoices";
import { SettingsModal } from "../modal/SettingsModal";
import { useSettingsForm, type SettingsFormErrors } from "../state/useSettingsForm";

/**
 * The one editor for the single `ApplicationExecutionDefaults` record.
 *
 * There is deliberately no create-versus-edit branch. Phase 5.8 made the
 * repository singular — `get` and `set`, no list, no delete — and 5.10 exposed
 * exactly one write, `setExecutionDefaults`. Configuring defaults for the first
 * time and changing them later are the same operation, so the modal takes the
 * current values when they exist and empty ones when they do not, and the
 * wording of the primary action is the only thing that differs.
 *
 * All three fields are closed selects over *configured* records. There is no
 * free-text escape, and the reason is the opposite of 5.14's: there, the
 * backend did not validate the value, so a custom entry was legitimate. Here
 * every field is a persisted reference that 5.8 validates for existence,
 * enabled state, and cross-domain compatibility, so a typed value could only
 * ever be a reference to nothing.
 *
 * Discovery is never consulted. `/model-providers`, `/models`, and `/runtimes`
 * report what is available; `/settings/*` reports what is configured, and a
 * default may only point at the latter. Whether the selected configuration can
 * actually be instantiated is 5.16's question, not this form's.
 */

const t = defaultTheme;

interface DefaultsFormValues {
  default_provider_connection_id: string;
  default_model_id: string;
  default_runtime_configuration_id: string;
}

const emptyForm: DefaultsFormValues = {
  default_provider_connection_id: "",
  default_model_id: "",
  default_runtime_configuration_id: "",
};

/**
 * Phase 5.8's three validation rules, checked client-side so the operator sees
 * the problem before a round trip.
 *
 * One message per field. A field can be wrong in more than one way — a model
 * that belongs to another connection is also, usually, disabled — and stacking
 * both messages in one control is noise. They are ordered by how fundamental the
 * problem is, matching the backend's own existence → enabled → compatibility
 * order, so the first message is the one worth fixing first.
 *
 * Nothing here checks discovery membership: 5.8 validates against configured
 * records, and a runtime whose adapter is not registered is still a valid
 * default.
 */
function validateForm(
  values: DefaultsFormValues,
  providers: ChoiceSet<ProviderConnectionResponse>,
  models: ChoiceSet<ModelConfigurationResponse>,
  runtimes: ChoiceSet<RuntimeConfigurationResponse>,
): SettingsFormErrors<DefaultsFormValues> {
  const errors: SettingsFormErrors<DefaultsFormValues> = {};

  const provider = providers.records.find(
    (record) =>
      record.provider_connection_id === values.default_provider_connection_id,
  );
  const model = models.records.find(
    (record) => record.model_id === values.default_model_id,
  );
  const runtime = runtimes.records.find(
    (record) =>
      record.runtime_configuration_id ===
      values.default_runtime_configuration_id,
  );

  if (values.default_provider_connection_id === "") {
    errors.default_provider_connection_id = "Select a provider connection.";
  } else if (provider == null) {
    errors.default_provider_connection_id =
      "This provider connection is not in the current configuration.";
  } else if (!provider.enabled) {
    errors.default_provider_connection_id =
      "Select an enabled provider connection.";
  }

  if (values.default_model_id === "") {
    errors.default_model_id = "Select a model for this provider connection.";
  } else if (model == null) {
    errors.default_model_id = "This model is not in the current configuration.";
  } else if (model.provider_connection_id !== values.default_provider_connection_id) {
    errors.default_model_id =
      "Select a model that belongs to this provider connection.";
  } else if (!model.enabled) {
    errors.default_model_id = "Select an enabled model for this provider connection.";
  }

  if (values.default_runtime_configuration_id === "") {
    errors.default_runtime_configuration_id = "Select a runtime configuration.";
  } else if (runtime == null) {
    errors.default_runtime_configuration_id =
      "This runtime configuration is not in the current configuration.";
  } else if (!runtime.enabled) {
    errors.default_runtime_configuration_id =
      "Select an enabled runtime configuration.";
  }

  return errors;
}

export interface ExecutionDefaultsEditorProps {
  client: ApiClient;
  /** The stored record, or `null` when defaults have never been configured. */
  record: {
    default_provider_connection_id: string;
    default_model_id: string;
    default_runtime_configuration_id: string;
  } | null;
  providers: ChoiceSet<ProviderConnectionResponse>;
  models: ChoiceSet<ModelConfigurationResponse>;
  runtimes: ChoiceSet<RuntimeConfigurationResponse>;
  onClose: () => void;
  onSaved: () => void;
  /** Re-runs one failed inventory request. */
  onRetrySource: (source: "providers" | "models" | "runtimes") => void;
}

export function ExecutionDefaultsEditor({
  client,
  record,
  providers,
  models,
  runtimes,
  onClose,
  onSaved,
  onRetrySource,
}: ExecutionDefaultsEditorProps) {
  const configuring = record == null;

  const { values, errors, set, submitError, busy, save, requestClose } =
    useSettingsForm<DefaultsFormValues>({
      initial: record ?? emptyForm,
      validate: (values) => validateForm(values, providers, models, runtimes),
      fallbackMessage: "AVA could not save these defaults. Try again.",
      onSaved,
      onClose,
      perform: async (values) => {
        const request: SetApplicationExecutionDefaultsRequest = {
          default_provider_connection_id:
            values.default_provider_connection_id,
          default_model_id: values.default_model_id,
          default_runtime_configuration_id:
            values.default_runtime_configuration_id,
        };
        await setExecutionDefaults(client, request);
      },
    });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void save();
  };

  const providerChoices: SelectOption[] = providerOptions(
    providers,
    values.default_provider_connection_id,
  );
  const modelChoices: SelectOption[] = modelOptions(
    models,
    values.default_provider_connection_id,
    values.default_model_id,
  );
  const runtimeChoices: SelectOption[] = runtimeOptions(
    runtimes,
    values.default_runtime_configuration_id,
  );

  /**
   * A save would be a guess while any source is still loading or unreachable:
   * "this runtime does not exist" and "AVA could not ask" must not produce the
   * same submit. The operator gets a retry on the specific field instead.
   */
  const anySourceBlocking =
    providers.blocking || models.blocking || runtimes.blocking;

  /**
   * Changing the provider re-evaluates the model, and a model that belonged to
   * the previous connection is cleared rather than kept.
   *
   * Preserving it would leave an invalid pairing on screen for the operator to
   * discover, and auto-selecting the first matching model would choose something
   * they did not ask for. Clearing forces an explicit choice, which is the only
   * option that cannot be wrong about intent. The stored value is not discarded
   * from the form's *initial* state by this — it is only replaced once the
   * operator acts, so opening the dialog alone still repairs nothing.
   */
  const onProviderChange = (value: string) => {
    set("default_provider_connection_id", value);
    if (values.default_model_id === "") {
      return;
    }
    const model = models.records.find(
      (record) => record.model_id === values.default_model_id,
    );
    if (model == null || model.provider_connection_id !== value) {
      set("default_model_id", "");
    }
  };

  return (
    <SettingsModal
      open
      title={configuring ? "Configure Defaults" : "Edit Defaults"}
      primaryAction="Save defaults"
      onPrimaryAction={() => void save()}
      primaryDisabled={busy || anySourceBlocking}
      secondaryAction="Cancel"
      onSecondaryAction={requestClose}
      error={submitError}
      primaryBusy={busy}
      onClose={requestClose}
    >
      <form
        noValidate
        onSubmit={onSubmit}
        style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}
      >
        <ChoiceSelect
          label="Default provider connection"
          value={values.default_provider_connection_id}
          onChange={onProviderChange}
          options={providerChoices}
          choices={providers}
          error={errors.default_provider_connection_id}
          busy={busy}
          retryLabel="Retry loading provider connections"
          onRetry={() => onRetrySource("providers")}
          emptyText="No provider connections are configured."
          unavailableText="Provider connections could not be loaded."
          busyText="Loading provider connections…"
          helpText={
            configuring
              ? "Which configured provider connection a default run uses. The provider type is shown for context and is not what gets stored."
              : undefined
          }
        />

        <ChoiceSelect
          label="Default model"
          value={values.default_model_id}
          onChange={(value) => set("default_model_id", value)}
          options={modelChoices}
          choices={models}
          error={errors.default_model_id}
          busy={busy}
          retryLabel="Retry loading model configurations"
          onRetry={() => onRetrySource("models")}
          emptyText="No model configurations are configured."
          unavailableText="Model configurations could not be loaded."
          busyText="Loading model configurations…"
          noProviderText="Choose a provider connection to see its models."
          helpText="Only models configured against the selected provider connection can be chosen."
        />

        <ChoiceSelect
          label="Default runtime"
          value={values.default_runtime_configuration_id}
          onChange={(value) => set("default_runtime_configuration_id", value)}
          options={runtimeChoices}
          choices={runtimes}
          error={errors.default_runtime_configuration_id}
          busy={busy}
          retryLabel="Retry loading runtime configurations"
          onRetry={() => onRetrySource("runtimes")}
          emptyText="No runtime configurations are configured."
          unavailableText="Runtime configurations could not be loaded."
          busyText="Loading runtime configurations…"
          helpText="Which configured runtime a default run uses. Whether its adapter is currently registered is not checked here."
        />

        {/* The modal's primary button is rendered in the dialog footer, outside
            this form, so the form needs a submit button of its own for the
            browser's implicit submission (Enter in a text field). It is hidden
            and aria-hidden: it is never focused — `Modal` filters aria-hidden
            elements out of its focus trap — and it is not announced. jsdom does
            not implement implicit submission, so this path is not asserted in
            tests; the click path below is. */}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
    </SettingsModal>
  );
}

interface ChoiceSelectProps<TRecord> {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  choices: ChoiceSet<TRecord>;
  error?: string;
  busy: boolean;
  retryLabel: string;
  onRetry: () => void;
  emptyText: string;
  unavailableText: string;
  busyText: string;
  /** Shown instead of an empty list when a prerequisite selection is missing. */
  noProviderText?: string;
  helpText?: string;
}

/**
 * One closed select plus the state it cannot show on its own.
 *
 * `Select` already renders a label, help text, an error, and a disabled state.
 * What it cannot express is *why* it is empty, which for this form is the whole
 * point: an empty list means "nothing is configured" only when that is actually
 * what happened. So the unavailable and empty cases each state themselves here,
 * and the unavailable one carries a retry rather than leaving the operator to
 * reload the page.
 */
function ChoiceSelect<TRecord>({
  label,
  value,
  onChange,
  options,
  choices,
  error,
  busy,
  retryLabel,
  onRetry,
  emptyText,
  unavailableText,
  busyText,
  noProviderText,
  helpText,
}: ChoiceSelectProps<TRecord>) {
  const unavailable = choices.status === "unavailable";
  const loading = choices.status === "loading";

  /**
   * One explanation, chosen from the most specific true statement available.
   *
   * The order matters. An empty *source* and an empty *filtered* list are
   * different facts that look identical in the DOM, and they call for different
   * responses: "configure a model" versus "pick a provider first". So
   * `empty` is tested before the filter case — if there are no models at all,
   * no provider choice would reveal any, and telling the operator to choose one
   * would send them down a dead end.
   */
  const note =
    loading
      ? busyText
      : choices.status === "empty"
        ? emptyText
        : options.length === 0 && value === "" && noProviderText != null
          ? noProviderText
          : undefined;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.xs }}>
      <Select
        label={label}
        value={value}
        onChange={onChange}
        options={options}
        placeholder={`Choose ${label.toLowerCase().replace(/^default /, "")}…`}
        disabled={busy || unavailable || loading}
        error={error ?? (unavailable ? unavailableText : undefined)}
        helpText={note ?? helpText}
      />
      {unavailable && (
        <div>
          <Button variant="secondary" size="sm" onClick={onRetry} disabled={busy}>
            {retryLabel}
          </Button>
        </div>
      )}
    </div>
  );
}
