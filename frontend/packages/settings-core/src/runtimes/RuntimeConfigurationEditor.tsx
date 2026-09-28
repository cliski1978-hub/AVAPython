import { useState, type FormEvent } from "react";
import type { ApiClient } from "@ava/api-client";
import { createRuntimeConfiguration, updateRuntimeConfiguration } from "@ava/api-client";
import type {
  CreateRuntimeConfigurationRequest,
  RuntimeConfigurationResponse,
  UpdateRuntimeConfigurationRequest,
} from "@ava/contracts";
import { Checkbox, Input, Select, defaultTheme, type SelectOption } from "@ava/ui-core";

import { SettingsModal } from "../modal/SettingsModal";
import { useSettingsForm, type SettingsFormErrors } from "../state/useSettingsForm";

/**
 * Add/Edit form for one `RuntimeConfiguration`.
 *
 * The record is the whole domain. Phase 5.6 gave it exactly four fields and
 * deliberately no configuration bag, so there is no executable, host,
 * endpoint, workspace path, or per-adapter options field here — not because
 * they were forgotten, but because OpenHands' constructor inputs are
 * composition-owned policy objects rather than reusable instance settings.
 * Nothing model-, provider-, credential-, or authority-related appears either.
 *
 * Both immutable fields are rendered as read-only text inputs, never as
 * selects. That is stronger than 5.13's approach to an unknown stored value:
 * there, a closed select had to be taught to preserve a value it did not
 * recognise. Here, `runtime_type` cannot be changed at all, so there is no
 * control that *could* coerce it, and an unregistered type is displayed exactly
 * as stored because it is never round-tripped through a list of options.
 *
 * `runtime_type` is a required field on create and free text rather than a
 * closed select, because the backend does not validate it against installed
 * runtimes. Registered adapters are offered as a convenience; a type AVA has
 * never heard of is still accepted.
 */

const t = defaultTheme;

/** Escape hatch for a type that is not currently registered. */
const CUSTOM_RUNTIME_TYPE = "__custom__";

interface RuntimeFormValues {
  runtime_configuration_id: string;
  runtime_type: string;
  display_name: string;
  enabled: boolean;
}

const emptyForm: RuntimeFormValues = {
  runtime_configuration_id: "",
  runtime_type: "",
  display_name: "",
  enabled: true,
};

function formFromRecord(
  record: RuntimeConfigurationResponse,
): RuntimeFormValues {
  return {
    runtime_configuration_id: record.runtime_configuration_id,
    runtime_type: record.runtime_type,
    display_name: record.display_name,
    enabled: record.enabled,
  };
}

/**
 * Presence only. Phase 5.7 states the domain's rule as "non-blank", with no
 * distinctness constraint between identity and type (unlike 5.4's model
 * configuration), so none is invented here.
 *
 * Deliberately absent: any check of `runtime_type` against registered runtimes.
 * A value the registry has not reported is a legitimate thing to store — the
 * database has no vocabulary check and the service has no referential
 * validation — so rejecting it here would make the front end stricter than the
 * domain, which is the specific error this phase must not make.
 */
function validateForm(
  values: RuntimeFormValues,
): SettingsFormErrors<RuntimeFormValues> {
  const errors: SettingsFormErrors<RuntimeFormValues> = {};

  if (values.runtime_configuration_id.trim() === "") {
    errors.runtime_configuration_id = "A stable runtime configuration ID is required.";
  }
  if (values.runtime_type.trim() === "") {
    errors.runtime_type = "A runtime type is required.";
  }
  if (values.display_name.trim() === "") {
    errors.display_name = "A display name is required.";
  }

  return errors;
}

export interface RuntimeConfigurationEditorProps {
  client: ApiClient;
  /** The record being edited, or `null` when adding a new runtime. */
  record: RuntimeConfigurationResponse | null;
  /** Currently registered runtime types, from `GET /runtimes`. */
  knownRuntimeTypes: SelectOption[];
  /** False when discovery answered with nothing, or could not be reached. */
  discoveryAvailable: boolean;
  onClose: () => void;
  /** Called after a successful write so the section can refresh. */
  onSaved: () => void;
}

export function RuntimeConfigurationEditor({
  client,
  record,
  knownRuntimeTypes,
  discoveryAvailable,
  onClose,
  onSaved,
}: RuntimeConfigurationEditorProps) {
  const editing = record != null;
  const [customChosen, setCustomChosen] = useState(false);

  const { values, errors, set, submitError, busy, save, requestClose } =
    useSettingsForm<RuntimeFormValues>({
      initial: record != null ? formFromRecord(record) : emptyForm,
      validate: validateForm,
      fallbackMessage: "AVA could not save this runtime. Try again.",
      onSaved,
      onClose,
      perform: async (values) => {
        if (record != null) {
          // `runtime_configuration_id` is a path parameter, not a body field:
          // the request can only ever address the record the dialog was opened
          // for. `runtime_type` is echoed unchanged — the contract permits
          // omitting it or resending the current value, and echoing makes the
          // preserved type explicit rather than implied by its absence.
          const request: UpdateRuntimeConfigurationRequest = {
            runtime_type: record.runtime_type,
            display_name: values.display_name.trim(),
            enabled: values.enabled,
          };
          await updateRuntimeConfiguration(
            client,
            record.runtime_configuration_id,
            request,
          );
          return;
        }

        const request: CreateRuntimeConfigurationRequest = {
          runtime_configuration_id: values.runtime_configuration_id.trim(),
          runtime_type: values.runtime_type.trim(),
          display_name: values.display_name.trim(),
          enabled: values.enabled,
        };
        await createRuntimeConfiguration(client, request);
      },
    });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void save();
  };

  /**
   * Whether the custom-type field is showing.
   *
   * Two ways to get here, and both must be handled:
   *
   * 1. The operator chose "Other runtime type…" from the select. The choice has
   *    to be remembered separately from the value, because choosing it clears
   *    the value — so inferring the mode from the value alone would make the
   *    field disappear the moment it was asked for.
   * 2. Discovery answered *after* the operator had already typed into the plain
   *    text field, switching the control from an `Input` to a `Select`. The
   *    typed value is not among the options, so it must stay visible and
   *    editable rather than being hidden behind a select showing nothing.
   *
   * The second clause also makes the first self-healing: if a custom type later
   * turns out to be a registered one, the field collapses into the select.
   */
  const customRuntimeType =
    !editing &&
    (customChosen ||
      (discoveryAvailable &&
        values.runtime_type !== "" &&
        !knownRuntimeTypes.some(
          (option) => option.value === values.runtime_type,
        )));

  const runtimeTypeSelectOptions: SelectOption[] = [
    ...knownRuntimeTypes,
    { value: CUSTOM_RUNTIME_TYPE, label: "Other runtime type…" },
  ];

  return (
    <SettingsModal
      open
      title={editing ? "Edit Runtime" : "Add Runtime"}
      primaryAction={editing ? "Save changes" : "Create runtime"}
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
          label="Runtime configuration ID"
          value={values.runtime_configuration_id}
          onChange={(value) => set("runtime_configuration_id", value)}
          readOnly={editing}
          placeholder="native-primary"
          error={errors.runtime_configuration_id}
          helpText={
            editing
              ? "Stable configured identity; cannot be changed."
              : "Stable identity AVA uses for this configured runtime — a short key, not a label. Selectors show the display name. Two runtimes may share a type, since this identifies an instance rather than the adapter kind."
          }
        />

        {editing ? (
          <Input
            label="Runtime type"
            value={values.runtime_type}
            readOnly
            helpText="Runtime type is immutable; delete and recreate the runtime to change it. A type AVA does not currently have registered is still shown exactly as stored."
          />
        ) : discoveryAvailable ? (
          <Select
            label="Runtime type"
            value={
              customRuntimeType ? CUSTOM_RUNTIME_TYPE : values.runtime_type
            }
            onChange={(value) => {
              if (value === CUSTOM_RUNTIME_TYPE) {
                setCustomChosen(true);
                set("runtime_type", "");
                return;
              }
              setCustomChosen(false);
              set("runtime_type", value);
            }}
            options={runtimeTypeSelectOptions}
            placeholder="Choose a runtime type…"
            error={customRuntimeType ? undefined : errors.runtime_type}
            helpText="Runtime types AVA currently has registered. Pick “Other runtime type…” to name one that is not registered — AVA does not require the adapter to be installed."
          />
        ) : (
          <Input
            label="Runtime type"
            value={values.runtime_type}
            onChange={(value) => set("runtime_type", value)}
            placeholder="native"
            error={errors.runtime_type}
            helpText="Runtime adapter type, stored exactly as entered. Registered types could not be listed, so enter one manually."
          />
        )}

        {customRuntimeType && (
          <Input
            label="Runtime type (custom)"
            value={values.runtime_type}
            onChange={(value) => set("runtime_type", value)}
            placeholder="langgraph"
            error={errors.runtime_type}
            helpText="Any adapter kind. AVA stores it without checking it against installed runtimes, so this may be configured before the adapter exists."
          />
        )}

        <Input
          label="Display name"
          value={values.display_name}
          onChange={(value) => set("display_name", value)}
          placeholder="AVA Native Runtime"
          error={errors.display_name}
          helpText="How this runtime appears in Settings and later selectors. This will be what an operator picks from, not the ID."
        />

        <Checkbox
          label="Enabled"
          checked={values.enabled}
          onChange={(checked) => set("enabled", checked)}
          helpText="Whether this runtime configuration is available for selection. It is not an access or authorization setting, and it is not the same as whether the adapter is installed."
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
