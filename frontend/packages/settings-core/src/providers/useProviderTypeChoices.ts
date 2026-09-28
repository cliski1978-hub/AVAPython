import { useEffect, useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { getModelProviders } from "@ava/api-client";
import type { SelectOption } from "@ava/ui-core";

/**
 * Provider adapter types offered when creating a connection.
 *
 * Source: `GET /model-providers` (discovery). That endpoint reports the
 * provider adapters currently installed in AVA, which is exactly the set of
 * types a new connection is most likely to reference.
 *
 * It is *not* the source of truth for configured connections — those always
 * come from `GET /settings/providers` — and the two datasets are never merged.
 * Discovery reports availability, not configuration, so an adapter with zero
 * configured connections is a normal state, and a configured connection for an
 * adapter that is temporarily unavailable must still be creatable.
 *
 * For that reason the backend does not validate `provider_id` against the
 * installed set, and neither does this form: callers may pick a discovered
 * type or supply their own. When discovery fails or returns nothing, the form
 * falls back to a plain text input rather than presenting an empty select.
 *
 * `enabled` is false when the caller has no type to choose — editing a record
 * freezes its type — so opening Edit issues no discovery request at all.
 */
export function useProviderTypeChoices(
  client: ApiClient,
  enabled = true,
): {
  options: SelectOption[];
  available: boolean;
} {
  const [providerIds, setProviderIds] = useState<string[] | null>(null);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    void getModelProviders(client)
      .then((response) => {
        if (cancelled) {
          return;
        }
        const seen = new Set<string>();
        for (const provider of response.providers) {
          seen.add(provider.provider_id);
        }
        setProviderIds([...seen].sort());
      })
      .catch(() => {
        // The create form stays usable with manual entry; this is not an error
        // worth interrupting the user over.
        if (!cancelled) {
          setProviderIds([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, enabled]);

  const ids = providerIds ?? [];
  return {
    options: ids.map((providerId) => ({ value: providerId, label: providerId })),
    available: ids.length > 0,
  };
}
