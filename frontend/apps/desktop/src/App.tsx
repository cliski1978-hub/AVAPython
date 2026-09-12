import { ApiClient, getHealth } from "@ava/api-client";
import { useEffect, useState } from "react";

const DEFAULT_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type AppStatus = "checking" | "healthy" | "unhealthy" | "unavailable";

const client = new ApiClient({ baseUrl: DEFAULT_BASE_URL });

export function App() {
  const [status, setStatus] = useState<AppStatus>("checking");

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const health = await getHealth(client);
        if (!cancelled && health.status === "healthy") {
          setStatus("healthy");
        } else if (!cancelled) {
          setStatus("unhealthy");
        }
      } catch {
        if (!cancelled) {
          setStatus("unavailable");
        }
      }
    }

    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  const statusText =
    status === "checking"
      ? "Checking..."
      : status === "healthy"
        ? "Healthy"
        : status === "unhealthy"
          ? "Unhealthy"
          : "Unavailable";

  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        fontFamily: "sans-serif",
        gap: "8px",
      }}
    >
      <h1 style={{ margin: 0 }}>AVA</h1>
      <p style={{ margin: 0 }}>Application Status: {statusText}</p>
    </main>
  );
}