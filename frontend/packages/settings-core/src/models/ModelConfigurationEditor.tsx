import type { FormEvent } from "react";
import type { ApiClient } from "@ava/api-client";
import { createModelConfiguration, updateModelConfiguration } from "@ava/api-client";
import type {
  CreateModelConfigurationRequest,
  ModelConfigurationResponse,
  ModelHostingMode,
  UpdateModelConfigurationRequest,
} from "@ava/contracts";
import { Checkbox, Input, Select, defaultTheme, type SelectOption } from "@ava/ui-core";

import { SettingsModal } from "../modal/SettingsModal";
import {
  useSettingsForm,
  type SettingsFormErrors,
} from "../state/useSettingsForm";
import {
  capabilitiesFrom,
  capabilityToggles,
  emptyCapabilities,
  CAPABILITY_FIELDS,
  type CapabilityToggles,
} from "./modelCapabilities";

/**
 * Add/Edit form for one `ModelConfiguration`.
 *
 * The record is the whole domain: no runtime selection, no credential field, no
 * endpoint duplication (those belong to the provider connection), no
 * qualification state, and no context-limit field — Phase 5.4 deliberately left
 * capacity out because it is provider-reported discovery metadata, not
 * configuration.
 *
 * `provider_connection_id` is a real persisted relationship, so unlike the
 * provider *type* in 5.12 it is never free text: it is chosen from configured
 * connections. On create, a disabled connection is shown but not offered; on
 * edit the association is locked, because Phase 5.10 made it immutable and
 * silently reassigning a model to another deployment would change which
 * credential and endpoint reach it.
 */

const t = defaultTheme;

interface ModelFormValues {
  model_id: string;
  provider_connection_id: string;
  provider_model_name: string;
  display_name: string;
  hosting_mode: ModelHostingMode;
  capabilities: CapabilityToggles;
  enabled: boolean;
  context_window_tokens: string;
}

const emptyForm: ModelFormValues = {
  model_id: "",
  provider_connection_id: "",
  provider_model_name: "",
  display_name: "",
  hosting_mode: "local",
  capabilities: capabilityToggles(emptyCapabilities()),
  enabled: true,
  context_window_tokens: "",
};

function formFromRecord(record: ModelConfigurationResponse): ModelFormValues {
  return {
    model_id: record.model_id,
    provider_connection_id: record.provider_connection_id,
    provider_model_name: record.provider_model_name,
    display_name: record.display_name,
    hosting_mode: record.hosting_mode,
    capabilities: capabilityToggles(record.capabilities),
    enabled: record.enabled,
    context_window_tokens: record.context_window_tokens == null ? "" : String(record.context_window_tokens),
  };
}

/**
 * `ModelHostingMode` exactly as Phase 5.4 fixed it. Friendly labels for the
 * operator; the canonical values are what the form holds and sends.
 */
const HOSTING_MODES: readonly { value: ModelHostingMode; label: string }[] = [
  { value: "local", label: "Local" },
  { value: "company_hosted", label: "Company Hosted" },
  { value: "external", label: "External" },
];

/**
 * Client checks only for rules Phase 5.4 states as plain domain facts. The
 * three distinctness rules are included because the backend's message for them
 * ("model_id must be distinct from provider_model_name") does not say which
 * field to change. Everything else — duplicate ids, unknown connections,
 * capability or hosting-mode coercion — stays with the backend.
 */
function validateForm(
  values: ModelFormValues,
): SettingsFormErrors<ModelFormValues> {
  const errors: SettingsFormErrors<ModelFormValues> = {};

  const modelId = values.model_id.trim();
  const connectionId = values.provider_connection_id.trim();
  const providerModelName = values.provider_model_name.trim();

  if (modelId === "") {
    errors.model_id = "A stable model ID is required.";
  }
  if (connectionId === "") {
    errors.provider_connection_id = "Choose a provider connection.";
  }
  if (providerModelName === "") {
    errors.provider_model_name = "A provider model name is required.";
  }
  if (values.display_name.trim() === "") {
    errors.display_name = "A display name is required.";
  }
  if (values.context_window_tokens.trim() !== "" && (!/^\d+$/.test(values.context_window_tokens) || Number(values.context_window_tokens) <= 0)) {
    errors.context_window_tokens = "Enter a positive whole number of tokens, or leave it blank.";
  }
  if (modelId !== "" && modelId === connectionId) {
    errors.model_id = "The model ID must be distinct from the provider connection ID.";
  } else if (modelId !== "" && modelId === providerModelName) {
    errors.model_id = "The model ID must be distinct from the provider model name.";
  }
  if (connectionId !== "" && connectionId === providerModelName) {
    errors.provider_model_name =
      "The provider model name must be distinct from the provider connection ID.";
  }

  return errors;
}

export interface ModelConfigurationEditorProps {
  client: ApiClient;
  /** The record being edited, or `null` when adding a new model. */
  record: ModelConfigurationResponse | null;
  /**
   * Configured provider connections, already loaded by the section. Passed in
   * rather than fetched so the modal never issues a second list request.
   */
  providerConnections: ProviderConnectionSummary[];
  /** Whether that list has arrived yet, for gating the select. */
  providerConnectionsLoading: boolean;
  onClose: () => void;
  onSaved: () => void;
}

/** The slice of a connection this form needs. */
export interface ProviderConnectionSummary {
  provider_connection_id: string;
  display_name: string;
  enabled: boolean;
}

export function ModelConfigurationEditor({
  client,
  record,
  providerConnections,
  providerConnectionsLoading,
  onClose,
  onSaved,
}: ModelConfigurationEditorProps) {
  const editing = record != null;

  const { values, errors, set, submitError, busy, save, requestClose } =
    useSettingsForm<ModelFormValues>({
      initial: record != null ? formFromRecord(record) : emptyForm,
      validate: validateForm,
      fallbackMessage: "AVA could not save this model. Try again.",
      onSaved,
      onClose,
      perform: async (values) => {
        // Editing keeps the record's own contract version rather than
        // asserting this build's; creating uses the version this contract
        // package declares.
        const version = record?.capabilities.contract_version;

        if (record != null) {
          const request: UpdateModelConfigurationRequest = {
            // `provider_connection_id` is echoed unchanged. The contract permits
            // omitting it or resending the current value; echoing makes the
            // preserved association explicit in the payload.
            provider_connection_id: record.provider_connection_id,
            provider_model_name: values.provider_model_name.trim(),
            display_name: values.display_name.trim(),
            hosting_mode: values.hosting_mode,
            capabilities: capabilitiesFrom(values.capabilities, version),
            enabled: values.enabled,
            context_window_tokens: values.context_window_tokens.trim() ? Number(values.context_window_tokens) : null,
          };
          await updateModelConfiguration(client, record.model_id, request);
          return;
        }

        const request: CreateModelConfigurationRequest = {
          model_id: values.model_id.trim(),
          provider_connection_id: values.provider_connection_id.trim(),
          provider_model_name: values.provider_model_name.trim(),
          display_name: values.display_name.trim(),
          hosting_mode: values.hosting_mode,
          capabilities: capabilitiesFrom(values.capabilities, version),
          enabled: values.enabled,
          context_window_tokens: values.context_window_tokens.trim() ? Number(values.context_window_tokens) : null,
        };
        await createModelConfiguration(client, request);
      },
    });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void save();
  };

  const selectable = providerConnections.filter(
    (connection) => connection.enabled,
  );
  const linkedConnection = editing
    ? providerConnections.find(
        (connection) =>
          connection.provider_connection_id === record?.provider_connection_id,
      )
    : undefined;

  /**
   * Disabled connections stay in the list so the configured inventory is fully
   * visible, but they are not offered for a new model. Marking them disabled
   * rather than removing them is the point: an operator can see that a
   * connection exists and why it cannot be chosen, instead of wondering where
   * it went.
   */
  const connectionOptions: SelectOption[] = providerConnections.map(
    (connection) => ({
      value: connection.provider_connection_id,
      label: connection.enabled
        ? connection.display_name
        : `${connection.display_name} (disabled)`,
      disabled: !connection.enabled,
    }),
  );

  /**
   * Only creation is blocked by having no selectable connection. A model whose
   * connection was disabled *after* it was configured must stay editable —
   * refusing the dialog would make an existing relationship unmanageable, and
   * the operator would be pushed to recreate a working configuration.
   */
  const noSelectableConnections =
    !editing && !providerConnectionsLoading && selectable.length === 0;

  /**
   * The three canonical modes, plus the record's own value if it is somehow not
   * one of them. A closed select silently coerces an unrecognised value to the
   * first option, which would quietly rewrite a stored hosting mode on the next
   * save. Showing the unknown value instead means the round-trip preserves it
   * and the operator can see that it is not a mode this build offers.
   */
  const knownHostingMode = HOSTING_MODES.some(
    (mode) => mode.value === values.hosting_mode,
  );
  const hostingModeOptions = [
    ...HOSTING_MODES.map((mode) => ({ value: mode.value, label: mode.label })),
    ...(knownHostingMode
      ? []
      : [
          {
            value: values.hosting_mode,
            label: `${values.hosting_mode} (not offered by this build)`,
          },
        ]),
  ];

  return (
    <SettingsModal
      open
      title={editing ? "Edit Model" : "Add Model"}
      primaryAction={editing ? "Save changes" : "Create model"}
      onPrimaryAction={() => void save()}
      // Nothing can be created against a connection that does not exist, so the
      // action is disabled rather than letting the request fail. Editing is
      // never gated this way.
      primaryDisabled={busy || noSelectableConnections}
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
        <Input
          label="Model ID"
          value={values.model_id}
          onChange={(value) => set("model_id", value)}
          readOnly={editing}
          placeholder="acme-large"
          error={errors.model_id}
          helpText={
            editing
              ? "Stable configured identity; cannot be changed."
              : "Stable identity AVA uses for this model — a short key, not a label. Selectors show the display name."
          }
        />

        {editing ? (
          <Input
            label="Provider connection"
            value={linkedConnection?.display_name ?? record?.provider_connection_id ?? ""}
            readOnly
            helpText={`Locked to ${record?.provider_connection_id}. A model's provider association is immutable; recreate the model to move it.`}
          />
        ) : (
          <Select
            label="Provider connection"
            value={values.provider_connection_id}
            onChange={(value) => set("provider_connection_id", value)}
            options={connectionOptions}
            disabled={providerConnectionsLoading}
            placeholder={
              providerConnectionsLoading
                ? "Loading provider connections…"
                : "Choose a provider connection…"
            }
            error={errors.provider_connection_id}
            helpText={
              noSelectableConnections
                ? "No enabled provider connection is configured. Add one under Settings → Providers first."
                : "Configured provider connections. Disabled connections cannot be used for a new model."
            }
          />
        )}

        <Input
          label="Provider model name"
          value={values.provider_model_name}
          onChange={(value) => set("provider_model_name", value)}
          placeholder="Qwen2.5-Coder-7B-Instruct"
          error={errors.provider_model_name}
          helpText="The name this provider knows the model by, stored exactly as entered. AVA does not require a particular format."
        />

        <Input
          label="Display name"
          value={values.display_name}
          onChange={(value) => set("display_name", value)}
          placeholder="Acme Large (EU)"
          error={errors.display_name}
          helpText="How this model appears in Settings and later selectors."
        />

        <Input
          label="Context window size (tokens)"
          type="number"
          value={values.context_window_tokens}
          onChange={(value) => set("context_window_tokens", value)}
          error={errors.context_window_tokens}
          helpText="Optional AVA context window for this model. Leave blank to use the provider-reported limit when available."
        />

        <Select
          label="Hosting mode"
          value={values.hosting_mode}
          onChange={(value) => set("hosting_mode", value as ModelHostingMode)}
          options={hostingModeOptions}
          error={errors.hosting_mode}
          helpText="Where inference for this model runs. This is placement metadata, not a permission."
        />

        <fieldset
          style={{
            border: `${t.border.width}px solid ${t.colors.border}`,
            borderRadius: t.radius.md,
            padding: t.spacing.md,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: t.spacing.md,
          }}
        >
          <legend
            style={{
              fontSize: t.font.sizeXs,
              fontWeight: t.font.weightSemibold,
              color: t.colors.mutedText,
              padding: `0 ${t.spacing.xs}px`,
            }}
          >
            Declared capabilities
          </legend>
          <p
            style={{
              margin: 0,
              fontSize: t.font.sizeXs,
              color: t.colors.mutedText,
              lineHeight: 1.5,
            }}
          >
            What this model is declared to support. Every capability is off by
            default, and declaring one grants no permission and is not a
            measured qualification.
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: t.spacing.md,
            }}
          >
            {CAPABILITY_FIELDS.map((field) => (
              <Checkbox
                key={field.key}
                label={field.label}
                checked={values.capabilities[field.key]}
                onChange={(checked) =>
                  set("capabilities", { ...values.capabilities, [field.key]: checked })
                }
              />
            ))}
          </div>
        </fieldset>

        <Checkbox
          label="Enabled"
          checked={values.enabled}
          onChange={(checked) => set("enabled", checked)}
          helpText="Whether this model is available for selection. It is not an access or authorization setting."
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
