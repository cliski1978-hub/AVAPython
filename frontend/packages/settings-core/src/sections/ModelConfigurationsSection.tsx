import { useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { listModelConfigurations, listProviderConnections } from "@ava/api-client";
import type { ModelConfigurationResponse } from "@ava/contracts";
import { Button, defaultTheme } from "@ava/ui-core";

import { SettingsInventory, type SettingsInventoryEntry } from "../inventory/SettingsInventory";
import { ModelConfigurationEditor, type ProviderConnectionSummary } from "../models/ModelConfigurationEditor";
import { capabilitySummary } from "../models/modelCapabilities";
import { useSettingsResource } from "../state/useSettingsResource";
import {
  SettingsEmpty,
  SettingsError,
  SettingsLoading,
} from "../settings/SettingsSectionState";

const t = defaultTheme;

/**
 * Configured models, with add and edit.
 *
 * The inventory's source of truth is `/settings/models` — declared
 * configuration — and never `/models`, which is the available execution
 * catalog. The two are not merged: a configured model whose adapter is
 * unavailable still appears here, because the configuration exists regardless
 * of what is currently reachable.
 *
 * `provider_connection_id` is resolved to the connection's display name using
 * `/settings/providers` — the configured inventory, not provider discovery —
 * so a row reads the way an operator named it rather than as a bare id. That
 * list is loaded once here and handed to the editor, so opening Add Model never
 * issues a second provider request.
 *
 * If the provider list cannot be loaded, the inventory still renders (falling
 * back to the raw connection id) rather than failing the whole section: models
 * are readable and editable without it, and only creating one needs the
 * relationship.
 *
 * No delete, no remove, and no row-level enable/disable — the same boundaries
 * the provider section holds, and for the same reasons.
 */
export function ModelConfigurationsSection({ client }: { client: ApiClient }) {
  const { state, reload } = useSettingsResource(() =>
    listModelConfigurations(client),
  );
  const { state: providerState } = useSettingsResource(() =>
    listProviderConnections(client),
  );
  const [editing, setEditing] = useState<ModelConfigurationResponse | "new" | null>(
    null,
  );

  const close = () => setEditing(null);
  const saved = () => {
    setEditing(null);
    void reload();
  };

  if (state.status === "loading") {
    return <SettingsLoading label="Loading models…" />;
  }

  if (state.status === "error") {
    return (
      <SettingsError
        message={state.error}
        onRetry={reload}
        retryLabel="Retry loading models"
      />
    );
  }

  const connections: ProviderConnectionSummary[] =
    providerState.status === "ready"
      ? providerState.data.provider_connections.map((connection) => ({
          provider_connection_id: connection.provider_connection_id,
          display_name: connection.display_name,
          enabled: connection.enabled,
        }))
      : [];
  const displayNameById = new Map(
    connections.map((connection) => [
      connection.provider_connection_id,
      connection.display_name,
    ]),
  );

  const models = state.data.models;
  const byId = new Map(models.map((model) => [model.model_id, model]));

  const entries: SettingsInventoryEntry[] = models.map((model) => ({
    id: model.model_id,
    title: model.display_name,
    // Falls back to the id when the connection list is unavailable, so a row is
    // never rendered without a relationship.
    association:
      displayNameById.get(model.provider_connection_id) ??
      model.provider_connection_id,
    metadata: `${model.provider_model_name} · ${model.hosting_mode}`,
    details: capabilitySummary(model.capabilities),
    enabled: model.enabled,
  }));

  const addAction = (
    <Button
      variant="primary"
      size="sm"
      onClick={() => setEditing("new")}
      ariaLabel="Add Model"
    >
      Add Model
    </Button>
  );

  const editor =
    editing != null ? (
      <ModelConfigurationEditor
        client={client}
        record={editing === "new" ? null : editing}
        providerConnections={connections}
        providerConnectionsLoading={providerState.status === "loading"}
        onClose={close}
        onSaved={saved}
      />
    ) : null;

  if (entries.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
        <SettingsEmpty
          title="No models configured."
          description="Models bind a provider model name to a provider connection and declare how AVA may host it."
        >
          {addAction}
        </SettingsEmpty>
        {editor}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: t.spacing.md,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: t.font.sizeSm,
            fontWeight: t.font.weightSemibold,
            color: t.colors.foreground,
          }}
        >
          Configured models
        </h3>
        {addAction}
      </div>

      <SettingsInventory
        label="Configured models"
        entries={entries}
        renderActions={(entry) => {
          const model = byId.get(entry.id);
          return (
            <Button
              variant="secondary"
              size="sm"
              ariaLabel={`Edit ${model?.display_name ?? entry.id}`}
              onClick={() => model != null && setEditing(model)}
            >
              Edit
            </Button>
          );
        }}
      />

      {editor}
    </div>
  );
}
