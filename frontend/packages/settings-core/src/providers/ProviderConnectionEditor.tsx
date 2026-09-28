import { useState, type FormEvent } from "react";
import type { ApiClient } from "@ava/api-client";
import { createProviderConnection, updateProviderConnection } from "@ava/api-client";
import type {
  CreateProviderConnectionRequest,
  ProviderConnectionResponse,
  UpdateProviderConnectionRequest,
} from "@ava/contracts";
import { Checkbox, Input, Select, defaultTheme, type SelectOption } from "@ava/ui-core";

import { SettingsModal } from "../modal/SettingsModal";
import {
  useSettingsForm,
  type SettingsFormErrors,
} from "../state/useSettingsForm";
import { useProviderTypeChoices } from "./useProviderTypeChoices";

/**
 * Add/Edit form for one `ProviderConnection`.
 *
 * Values, errors, and the busy lifecycle live in the shared `useSettingsForm`
 * hook, called here — so this component's state is local to the dialog and the
 * whole surface shares one submit pattern. The editor unmounts on close and the
 * Settings surface unmounts on navigation, so no draft is ever global,
 * persisted, or readable from another surface.
 *
 * The record is the whole domain: no secret, model, runtime, or default field
 * appears here. `credential_reference` is opaque metadata that names where AVA
 * resolves a credential; AVA never accepts, returns, or displays the resolved
 * value, so there is deliberately no API-key/password control and no
 * connectivity-test button (Phase 5.10 established that resolving a
 * credential from the environment does not prove provider reachability).
 */

const t = defaultTheme;

/** Escape hatch for a type that is not in the discovered list. */
const CUSTOM_PROVIDER_TYPE = "__custom__";

interface ProviderFormValues {
  provider_connection_id: string;
  provider_id: string;
  display_name: string;
  endpoint: string;
  enabled: boolean;
  credential_reference: string;
}

const emptyForm: ProviderFormValues = {
  provider_connection_id: "",
  provider_id: "",
  display_name: "",
  endpoint: "",
  enabled: true,
  credential_reference: "",
};

function formFromRecord(record: ProviderConnectionResponse): ProviderFormValues {
  return {
    provider_connection_id: record.provider_connection_id,
    provider_id: record.provider_id,
    display_name: record.display_name,
    endpoint: record.endpoint ?? "",
    enabled: record.enabled,
    credential_reference: record.credential_reference ?? "",
  };
}

/**
 * Optional fields are sent as `null`, never `""`. The domain treats a
 * non-blank string as a present value, so an empty string would arrive as a
 * real (and meaningless) endpoint rather than as "unset".
 */
function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Client checks only for rules the domain states plainly. Everything else —
 * credential-reference syntax, duplicate identity, immutability — stays with
 * the backend and surfaces through the modal's error slot.
 */
function validateForm(
  values: ProviderFormValues,
): SettingsFormErrors<ProviderFormValues> {
  const errors: SettingsFormErrors<ProviderFormValues> = {};

  if (values.provider_connection_id.trim() === "") {
    errors.provider_connection_id = "A stable connection ID is required.";
  } else if (values.provider_connection_id.trim() === values.provider_id.trim()) {
    errors.provider_connection_id =
      "The connection ID must be distinct from the provider type.";
  }

  if (values.provider_id.trim() === "") {
    errors.provider_id = "Choose or enter a provider type.";
  }

  if (values.display_name.trim() === "") {
    errors.display_name = "A display name is required.";
  }

  return errors;
}

export interface ProviderConnectionEditorProps {
  client: ApiClient;
  /** The record being edited, or `null` when adding a new connection. */
  record: ProviderConnectionResponse | null;
  onClose: () => void;
  /** Called after a successful write so the section can refresh. */
  onSaved: () => void;
}

export function ProviderConnectionEditor({
  client,
  record,
  onClose,
  onSaved,
}: ProviderConnectionEditorProps) {
  const editing = record != null;
  const [customChosen, setCustomChosen] = useState(false);
  const { options: providerTypeOptions, available: discoveryAvailable } =
    useProviderTypeChoices(client, !editing);

  const { values, errors, set, submitError, busy, save, requestClose } =
    useSettingsForm<ProviderFormValues>({
      initial: record != null ? formFromRecord(record) : emptyForm,
      validate: validateForm,
      fallbackMessage: "AVA could not save this provider. Try again.",
      onSaved,
      onClose,
      perform: async (values) => {
        if (record != null) {
          // `provider_connection_id` is a path parameter, not a body field: the
          // request can only ever address the record the dialog was opened for.
          // `provider_id` is echoed unchanged — the contract permits either
          // omitting it or resending the current value, and echoing makes the
          // preserved type explicit in the payload.
          const request: UpdateProviderConnectionRequest = {
            provider_id: record.provider_id,
            display_name: values.display_name.trim(),
            endpoint: blankToNull(values.endpoint),
            enabled: values.enabled,
            credential_reference: blankToNull(values.credential_reference),
          };
          await updateProviderConnection(
            client,
            record.provider_connection_id,
            request,
          );
          return;
        }

        const request: CreateProviderConnectionRequest = {
          provider_connection_id: values.provider_connection_id.trim(),
          provider_id: values.provider_id.trim(),
          display_name: values.display_name.trim(),
          endpoint: blankToNull(values.endpoint),
          enabled: values.enabled,
          credential_reference: blankToNull(values.credential_reference),
        };
        await createProviderConnection(client, request);
      },
    });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void save();
  };

  /**
   * Whether the custom-type field is showing.
   *
   * The "chosen" flag is needed as well as the value test: choosing
   * "Other provider type…" clears the value, so inferring the mode from the
   * value alone would hide the field the moment it was asked for and make the
   * escape hatch unreachable. The value test additionally covers discovery
   * answering after the operator had already typed into the plain text field,
   * and collapses the field away again if the type turns out to be discovered.
   */
  const useCustomProviderType =
    !editing &&
    (customChosen ||
      (discoveryAvailable &&
        values.provider_id !== "" &&
        !providerTypeOptions.some((option) => option.value === values.provider_id)));

  const providerTypeSelectOptions: SelectOption[] = [
    ...providerTypeOptions,
    { value: CUSTOM_PROVIDER_TYPE, label: "Other provider type…" },
  ];

  return (
    <SettingsModal
      open
      title={editing ? "Edit Provider" : "Add Provider"}
      primaryAction={editing ? "Save changes" : "Create provider"}
      onPrimaryAction={() => void save()}
      primaryDisabled={busy}
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
          label="Connection ID"
          value={values.provider_connection_id}
          onChange={(value) => set("provider_connection_id", value)}
          readOnly={editing}
          placeholder="acme-production"
          error={errors.provider_connection_id}
          helpText={
            editing
              ? "Stable configured identity; cannot be changed."
              : "Stable identity AVA uses for this connection — a short key, not a label. Selectors show the display name."
          }
        />

        {editing ? (
          <Input
            label="Provider type"
            value={values.provider_id}
            readOnly
            helpText="Provider type is immutable; recreate the connection to change it."
          />
        ) : discoveryAvailable ? (
          <Select
            label="Provider type"
            value={useCustomProviderType ? CUSTOM_PROVIDER_TYPE : values.provider_id}
            onChange={(value) => {
              if (value === CUSTOM_PROVIDER_TYPE) {
                setCustomChosen(true);
                set("provider_id", "");
                return;
              }
              setCustomChosen(false);
              set("provider_id", value);
            }}
            options={providerTypeSelectOptions}
            placeholder="Choose a provider type…"
            error={useCustomProviderType ? undefined : errors.provider_id}
            helpText="Provider types currently installed in AVA. Pick “Other provider type…” to name one that is not installed."
          />
        ) : (
          <Input
            label="Provider type"
            value={values.provider_id}
            onChange={(value) => set("provider_id", value)}
            placeholder="acme"
            error={errors.provider_id}
            helpText="Provider adapter type. Installed types could not be listed, so enter one manually."
          />
        )}

        {useCustomProviderType && (
          <Input
            label="Provider type (custom)"
            value={values.provider_id}
            onChange={(value) => set("provider_id", value)}
            placeholder="acme"
            error={errors.provider_id}
            helpText="Must differ from the connection ID."
          />
        )}

        <Input
          label="Display name"
          value={values.display_name}
          onChange={(value) => set("display_name", value)}
          placeholder="Acme (production)"
          error={errors.display_name}
          helpText="How this connection appears in Settings and later selectors."
        />

        <Input
          label="Endpoint"
          value={values.endpoint}
          onChange={(value) => set("endpoint", value)}
          placeholder="Optional"
          helpText="Optional. Stored exactly as entered — AVA does not require a URL here because provider schemes may differ."
        />

        <Checkbox
          label="Enabled"
          checked={values.enabled}
          onChange={(checked) => set("enabled", checked)}
          helpText="Whether this connection is available for selection. It is not an access or authorization setting."
        />

        <Input
          label="Credential reference"
          value={values.credential_reference}
          onChange={(value) => set("credential_reference", value)}
          placeholder="env:OPENAI_API_KEY"
          helpText="Optional reference to a credential, e.g. env:OPENAI_API_KEY. This names where AVA resolves the secret — it is not the secret, and no secret is ever entered or stored here."
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
