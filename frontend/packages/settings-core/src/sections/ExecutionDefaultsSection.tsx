import { useState } from "react";
import type { ApiClient } from "@ava/api-client";
import {
  getExecutionDefaults,
  listModelConfigurations,
  listProviderConnections,
  listRuntimeConfigurations,
} from "@ava/api-client";
import type {
  ModelConfigurationResponse,
  ProviderConnectionResponse,
  RuntimeConfigurationResponse,
} from "@ava/contracts";
import { Button, defaultTheme } from "@ava/ui-core";
import type { CSSProperties } from "react";

import {
  displayLabel,
  toChoiceSet,
  type ChoiceSet,
} from "../defaults/defaultChoices";
import { ExecutionDefaultsEditor } from "../defaults/ExecutionDefaultsEditor";
import { useSettingsResource } from "../state/useSettingsResource";
import {
  SettingsEmpty,
  SettingsError,
  SettingsLoading,
} from "../settings/SettingsSectionState";

/**
 * Application execution defaults: one record, edited in a modal.
 *
 * Source of truth is `/settings/defaults`. This is a single record, not a list,
 * so it does not use the inventory pattern: there is exactly one set of
 * defaults, and the Phase 5.8 repository has no list, no create, and no delete.
 * That is also why the actions are "Configure Defaults" and "Edit Defaults"
 * rather than "Add Default" — there is no such thing as adding a second one.
 *
 * `configured: false` is normal first-run state, not a failure and not an
 * error. Phase 5.10 made that explicit by answering `200` with the flag rather
 * than `404`, so this section branches on the flag and renders an empty state
 * with ordinary wording.
 *
 * The three inventories are loaded here rather than in the editor, for two
 * reasons. The read-only display resolves stored ids to display names, so it
 * needs the same data; and the editor therefore opens with its selectors already
 * populated instead of flashing three spinners.
 *
 * Each inventory is independent. One failing does not blank the others, and — the
 * part that matters — a failure is never presented as an empty inventory, since
 * "AVA could not load your runtimes" and "you have no runtimes" call for
 * different responses.
 *
 * These values are persisted configuration only. Nothing here changes how a run
 * executes; Phase 5.16 makes them authoritative.
 */

const t = defaultTheme;

type DefaultsRecord = {
  default_provider_connection_id: string;
  default_model_id: string;
  default_runtime_configuration_id: string;
};

function DefaultRow({
  label,
  value,
  secondary,
}: {
  label: string;
  value: string;
  secondary?: string;
}) {
  const rowStyle: CSSProperties = {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: t.spacing.md,
    padding: `${t.spacing.md}px ${t.spacing.lg}px`,
    borderRadius: t.radius.lg,
    boxSizing: "border-box",
  };

  return (
    <div className="border border-border bg-card text-card-foreground dark:bg-black dark:text-white" style={rowStyle} data-testid="settings-default-row">
      <span
        className="text-card-foreground dark:text-white"
        style={{
          fontSize: t.font.sizeSm,
          fontWeight: t.font.weightSemibold,
        }}
      >
        {label}
      </span>
      <span
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 2,
          minWidth: 0,
        }}
      >
        <span
          className="text-card-foreground dark:text-white"
          style={{
            fontSize: t.font.sizeSm,
            textAlign: "right",
          }}
          data-testid="settings-default-value"
        >
          {value}
        </span>
        {/* The id is only worth a second line when the label resolved to
            something else. If the record could not be found, the value *is* the
            id, and printing it twice would read as two different things. */}
        {secondary != null && secondary !== value && (
          <span
            className="text-muted-foreground dark:text-white/80"
            style={{
              fontSize: t.font.sizeXs,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
            data-testid="settings-default-secondary"
          >
            {secondary}
          </span>
        )}
      </span>
    </div>
  );
}

function defaultsAction(label: string, onClick: () => void) {
  return (
    <Button variant="primary" size="sm" onClick={onClick} ariaLabel={label}>
      {label}
    </Button>
  );
}

export function ExecutionDefaultsSection({ client }: { client: ApiClient }) {
  const { state, reload } = useSettingsResource(() => getExecutionDefaults(client));
  const providerResource = useSettingsResource(() => listProviderConnections(client));
  const modelResource = useSettingsResource(() => listModelConfigurations(client));
  const runtimeResource = useSettingsResource(() =>
    listRuntimeConfigurations(client),
  );
  const [editing, setEditing] = useState(false);

  const close = () => setEditing(false);
  const saved = () => {
    setEditing(false);
    // Only the defaults record is re-read. The three inventories are
    // unchanged by a defaults write, and re-fetching them would make the
    // display flicker for no reason.
    void reload();
  };

  const providers: ChoiceSet<ProviderConnectionResponse> = toChoiceSet(
    providerResource.state,
    (data) => data.provider_connections,
  );
  const models: ChoiceSet<ModelConfigurationResponse> = toChoiceSet(
    modelResource.state,
    (data) => data.models,
  );
  const runtimes: ChoiceSet<RuntimeConfigurationResponse> = toChoiceSet(
    runtimeResource.state,
    (data) => data.runtimes,
  );

  if (state.status === "loading") {
    return <SettingsLoading label="Loading execution defaults…" />;
  }

  if (state.status === "error") {
    return (
      <SettingsError
        message={state.error}
        onRetry={reload}
        retryLabel="Retry loading defaults"
      />
    );
  }

  // Unconfigured is a normal state, not an error and not a missing resource.
  // The flag and the record are checked together: the contract sends both, and
  // a `configured: true` with a null record would be a backend inconsistency
  // rather than a state the UI should render as configured.
  const defaults: DefaultsRecord | null =
    state.data.configured && state.data.defaults != null
      ? state.data.defaults
      : null;

  const editor = editing ? (
    <ExecutionDefaultsEditor
      client={client}
      record={defaults}
      providers={providers}
      models={models}
      runtimes={runtimes}
      onClose={close}
      onSaved={saved}
      onRetrySource={(source) => {
        if (source === "providers") void providerResource.reload();
        if (source === "models") void modelResource.reload();
        if (source === "runtimes") void runtimeResource.reload();
      }}
    />
  ) : null;

  if (defaults == null) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
        <SettingsEmpty
          title="Execution defaults are not configured."
          description="Defaults choose which provider connection, model, and runtime AVA uses when nothing else is selected."
        >
          {defaultsAction("Configure Defaults", () => setEditing(true))}
        </SettingsEmpty>
        {editor}
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: t.spacing.lg,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: t.spacing.md,
        }}
      >
        <h3
          className="text-foreground"
          style={{
            margin: 0,
            fontSize: t.font.sizeSm,
            fontWeight: t.font.weightSemibold,
          }}
        >
          Application execution defaults
        </h3>
        {defaultsAction("Edit Defaults", () => setEditing(true))}
      </div>

      <div
        role="group"
        aria-label="Application execution defaults"
        data-testid="settings-defaults"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: t.spacing.sm,
        }}
      >
        {/*
          Labels resolve to the configured display name, with the raw id kept
          as secondary text so the reference is always readable. When a
          referenced record cannot currently be found the id stands alone rather
          than rendering blank: the reference exists, and hiding it would make
          stored configuration look unset.
        */}
        <DefaultRow
          label="Provider connection"
          value={displayLabel(
            providers.records,
            defaults.default_provider_connection_id,
            (record) => record.provider_connection_id,
          )}
          secondary={defaults.default_provider_connection_id}
        />
        <DefaultRow
          label="Model"
          value={displayLabel(
            models.records,
            defaults.default_model_id,
            (record) => record.model_id,
          )}
          secondary={defaults.default_model_id}
        />
        <DefaultRow
          label="Runtime"
          value={displayLabel(
            runtimes.records,
            defaults.default_runtime_configuration_id,
            (record) => record.runtime_configuration_id,
          )}
          secondary={defaults.default_runtime_configuration_id}
        />
      </div>

      {editor}
    </div>
  );
}
