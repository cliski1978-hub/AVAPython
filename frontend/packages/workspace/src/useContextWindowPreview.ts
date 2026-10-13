import { useEffect, useState } from "react";
import { previewContextWindow, type ApiClient, type ContextWindowPreview } from "@ava/api-client";

/** Backend-authoritative prospective context, scoped to the exact draft inputs. */
export function useContextWindowPreview(client: ApiClient, request: Parameters<typeof previewContextWindow>[1], refreshKey: string) {
  const [revision, setRevision] = useState(0);
  const key = JSON.stringify([request, refreshKey, revision]);
  const enabled = Boolean(request.prompt.trim());
  const [state, setState] = useState<{ client: ApiClient; key: string; preview: ContextWindowPreview | null; loading: boolean; error: boolean }>({ client, key: "", preview: null, loading: false, error: false });
  useEffect(() => {
    const refresh = () => setRevision(current => current + 1);
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ client, key, preview: null, loading: true, error: false });
    const timer = window.setTimeout(() => {
      void previewContextWindow(client, request).then(preview => {
        if (!cancelled) setState({ client, key, preview, loading: false, error: false });
      }).catch(() => {
        if (!cancelled) setState({ client, key, preview: null, loading: false, error: true });
      });
    }, 350);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [client, key, enabled]);
  return !enabled ? { preview: null, loading: false, error: false }
    : state.client === client && state.key === key ? state : { preview: null, loading: true, error: false };
}
