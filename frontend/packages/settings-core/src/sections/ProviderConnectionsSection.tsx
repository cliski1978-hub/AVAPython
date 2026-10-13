import { useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { listProviderConnections } from "@ava/api-client";
import type { ProviderConnectionResponse } from "@ava/contracts";
import { Button, defaultTheme } from "@ava/ui-core";

import { SettingsInventory, type SettingsInventoryEntry } from "../inventory/SettingsInventory";
import { ProviderConnectionEditor } from "../providers/ProviderConnectionEditor";
import { useSettingsResource } from "../state/useSettingsResource";
import {
  SettingsEmpty,
  SettingsError,
  SettingsLoading,
} from "../settings/SettingsSectionState";

const t = defaultTheme;

/**
 * Configured provider connections, with add and edit.
 *
 * Source of truth is `/settings/providers` — configured records — never
 * `/model-providers`, which is discovery and reports what is currently
 * available. The two are not interchangeable and are not merged. Discovery
 * appears only as the list of adapter types offered by the create form.
 *
 * `credential_reference` is displayed as opaque configuration metadata. It
 * names where AVA resolves a secret; it is not a secret, and the backend never
 * returns resolved material.
 *
 * There is no delete or remove action: removal is outside this phase's scope
 * and outside the domain surface agreed for it. Disabling is a field of the
 * edit form rather than a row-level mutation, so a row and its form cannot
 * disagree about what a status change means. Disabled connections stay visible
 * and stay editable.
 *
 * Only the modal's open/closed target lives here as local state; the form's own
 * state belongs to the editor, which unmounts with the dialog.
 */
export function ProviderConnectionsSection({ client }: { client: ApiClient }) {
  const { state, reload } = useSettingsResource(() =>
    listProviderConnections(client),
  );
  const [editing, setEditing] = useState<ProviderConnectionResponse | "new" | null>(
    null,
  );

  const close = () => setEditing(null);
  const saved = () => {
    setEditing(null);
    void reload();
  };

  if (state.status === "loading") {
    return <SettingsLoading label="Loading provider connections…" />;
  }

  if (state.status === "error") {
    return (
      <SettingsError
        message={state.error}
        onRetry={reload}
        retryLabel="Retry loading providers"
      />
    );
  }

  const connections = state.data.provider_connections;
  const byId = new Map(
    connections.map((connection) => [connection.provider_connection_id, connection]),
  );

  const entries: SettingsInventoryEntry[] = connections.map((connection) => ({
    id: connection.provider_connection_id,
    title: connection.display_name,
    association: connection.provider_id,
    metadata:
      [connection.endpoint, connection.credential_reference]
        .filter((part) => part != null && part !== "")
        .join(" · ") || undefined,
    enabled: connection.enabled,
  }));

  const addAction = (
    <Button
      variant="primary"
      size="sm"
      onClick={() => setEditing("new")}
      ariaLabel="Add Provider"
    >
      Add Provider
    </Button>
  );

  if (entries.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
        <SettingsEmpty
          title="No provider connections configured."
          description="Provider connections tell AVA which provider to reach and which credential to resolve."
        >
          {addAction}
        </SettingsEmpty>
        {editing != null && (
          <ProviderConnectionEditor
            client={client}
            record={editing === "new" ? null : editing}
            onClose={close}
            onSaved={saved}
          />
        )}
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
          className="text-foreground"
          style={{
            margin: 0,
            fontSize: t.font.sizeSm,
            fontWeight: t.font.weightSemibold,
          }}
        >
          Configured provider connections
        </h3>
        {addAction}
      </div>

      <SettingsInventory
        label="Configured provider connections"
        entries={entries}
        renderActions={(entry) => {
          const record = byId.get(entry.id);
          return (
            <Button
              variant="secondary"
              size="sm"
              ariaLabel={`Edit ${record?.display_name ?? entry.id}`}
              onClick={() => record != null && setEditing(record)}
            >
              Edit
            </Button>
          );
        }}
      />

      {editing != null && (
        <ProviderConnectionEditor
          client={client}
          record={editing === "new" ? null : editing}
          onClose={close}
          onSaved={saved}
        />
      )}
    </div>
  );
}
