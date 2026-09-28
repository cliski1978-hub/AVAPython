import { useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { listRuntimeConfigurations } from "@ava/api-client";
import type { RuntimeConfigurationResponse } from "@ava/contracts";
import { Button, defaultTheme } from "@ava/ui-core";

import { SettingsInventory, type SettingsInventoryEntry } from "../inventory/SettingsInventory";
import { RuntimeConfigurationEditor } from "../runtimes/RuntimeConfigurationEditor";
import { useRuntimeTypeChoices } from "../runtimes/useRuntimeTypeChoices";
import { useSettingsResource } from "../state/useSettingsResource";
import {
  SettingsEmpty,
  SettingsError,
  SettingsLoading,
} from "../settings/SettingsSectionState";

const t = defaultTheme;

/**
 * Configured runtime instances, with add and edit.
 *
 * Source of truth is `/settings/runtimes` — configured records — and never
 * `/runtimes`, which is discovery. The two are not merged, and neither
 * direction is a precondition for the other: an installed runtime with no
 * configuration is valid, and a configured runtime whose adapter is not
 * currently registered is also valid configuration that must stay visible and
 * manageable. Nothing here filters, flags as broken, or refuses a save based
 * on discovery.
 *
 * `runtime_type` is the immutable adapter association and is shown as the
 * association line; the registry-derived availability note is kept on the
 * separate `details` line so it is never mistaken for the record's own
 * `enabled` state.
 *
 * Discovery is loaded once here and handed to the editor, so opening Add
 * Runtime issues no second request and the type list is already on screen.
 *
 * No delete, no remove, and no row-level enable/disable — the same boundaries
 * the provider and model sections hold, and for the same reasons.
 */
export function RuntimeConfigurationsSection({ client }: { client: ApiClient }) {
  const { state, reload } = useSettingsResource(() =>
    listRuntimeConfigurations(client),
  );
  const {
    options: runtimeTypeOptions,
    available: discoveryAvailable,
    registeredTypes,
    loading: discoveryLoading,
    unavailable: discoveryUnavailable,
  } = useRuntimeTypeChoices(client);
  const [editing, setEditing] = useState<RuntimeConfigurationResponse | "new" | null>(
    null,
  );

  const close = () => setEditing(null);
  const saved = () => {
    setEditing(null);
    void reload();
  };

  if (state.status === "loading") {
    return <SettingsLoading label="Loading runtimes…" />;
  }

  if (state.status === "error") {
    return (
      <SettingsError
        message={state.error}
        onRetry={reload}
        retryLabel="Retry loading runtimes"
      />
    );
  }

  const registered = new Set(registeredTypes);

  const entries: SettingsInventoryEntry[] = state.data.runtimes.map((runtime) => {
    /**
     * Whether the adapter kind is currently in AVA's registry.
     *
     * Phrased as "registered" rather than "available" on purpose. Discovery
     * answers one narrow question — is this key in `RuntimeRegistry` — and the
     * registry key is a lookup for an already-constructed port, not a
     * guarantee that a configured instance is usable: nothing here supplies or
     * checks an endpoint, a credential, or the composition-owned policy objects
     * an adapter needs. A matching entry therefore does not promise the runtime
     * will work, and a missing one does not mean the record is invalid. It is
     * a registry fact, labelled as one, and it never gates a save.
     *
     * The line is omitted whenever the answer is unknown — still loading, or
     * discovery unreachable — rather than guessed. A failed lookup and an empty
     * registry both yield an empty list, and only the second may be reported as
     * "not registered"; otherwise a transient discovery error would assert
     * something false about every configured runtime on the screen.
     */
    const known = registered.has(runtime.runtime_type);
    return {
      id: runtime.runtime_configuration_id,
      title: runtime.display_name,
      association: runtime.runtime_type,
      details:
        discoveryLoading || discoveryUnavailable
          ? undefined
          : known
            ? "Registered runtime"
            : "Not currently registered",
      enabled: runtime.enabled,
    };
  });

  const addAction = (
    <Button
      variant="primary"
      size="sm"
      onClick={() => setEditing("new")}
      ariaLabel="Add Runtime"
    >
      Add Runtime
    </Button>
  );

  const byId = new Map(
    state.data.runtimes.map((runtime) => [runtime.runtime_configuration_id, runtime]),
  );

  const editor =
    editing != null ? (
      <RuntimeConfigurationEditor
        client={client}
        record={editing === "new" ? null : editing}
        knownRuntimeTypes={runtimeTypeOptions}
        discoveryAvailable={discoveryAvailable}
        onClose={close}
        onSaved={saved}
      />
    ) : null;

  if (entries.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
        <SettingsEmpty
          title="No runtimes configured."
          description="Runtimes record which runtime adapter kind AVA should use. A configured runtime stays listed even if its adapter is not installed."
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
          Configured runtimes
        </h3>
        {addAction}
      </div>

      <SettingsInventory
        label="Configured runtimes"
        entries={entries}
        renderActions={(entry) => {
          const runtime = byId.get(entry.id);
          return (
            <Button
              variant="secondary"
              size="sm"
              ariaLabel={`Edit ${runtime?.display_name ?? entry.id}`}
              onClick={() => runtime != null && setEditing(runtime)}
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
