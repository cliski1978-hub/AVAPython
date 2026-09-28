import { describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  createProviderConnection,
  getExecutionDefaults,
  getProviderConnection,
  listModelConfigurations,
  listProviderConnections,
  listRuntimeConfigurations,
  setExecutionDefaults,
  updateRuntimeConfiguration,
} from "./index";

function clientReturning(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  return {
    fetchMock,
    client: new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock }),
  };
}

const connection = {
  provider_connection_id: "conn-1",
  provider_id: "openai-compatible",
  display_name: "Primary gateway",
  endpoint: "https://gateway.internal/v1",
  enabled: true,
  credential_reference: "env:OPENAI_API_KEY",
  contract_version: "v1",
} as const;

describe("settings transport wrappers", () => {
  it("lists provider connections from the settings boundary", async () => {
    const { fetchMock, client } = clientReturning({
      provider_connections: [connection],
      contract_version: "v1",
    });
    const result = await listProviderConnections(client);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/settings/providers", expect.anything());
    expect(result.provider_connections[0]?.provider_connection_id).toBe("conn-1");
  });

  it("returns a credential reference but never a secret", async () => {
    const { client } = clientReturning(connection);
    const result = await getProviderConnection(client, "conn-1");
    expect(result.credential_reference).toBe("env:OPENAI_API_KEY");
    expect(JSON.stringify(result)).not.toMatch(/api_key|secret_value|password/);
  });

  it("encodes provider connection ids in the path", async () => {
    const { fetchMock, client } = clientReturning(connection);
    await getProviderConnection(client, "conn 1/../x");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/settings/providers/conn%201%2F..%2Fx");
  });

  it("posts a new provider connection to the settings path", async () => {
    const { fetchMock, client } = clientReturning(connection, 201);
    await createProviderConnection(client, {
      provider_connection_id: "conn-1",
      provider_id: "openai-compatible",
      display_name: "Primary gateway",
    });
    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("http://localhost:8000/settings/providers");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toMatchObject({ provider_connection_id: "conn-1" });
  });

  it("reads model and runtime configuration from their own settings paths", async () => {
    const { fetchMock, client } = clientReturning({ models: [], contract_version: "v1" });
    await listModelConfigurations(client);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/settings/models");

    const runtimes = clientReturning({ runtimes: [], contract_version: "v1" });
    await listRuntimeConfigurations(runtimes.client);
    expect(runtimes.fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/settings/runtimes");
  });

  it("reports unconfigured defaults as a state rather than an error", async () => {
    const { client } = clientReturning({ configured: false, defaults: null, contract_version: "v1" });
    const result = await getExecutionDefaults(client);
    expect(result.configured).toBe(false);
    expect(result.defaults).toBeNull();
  });

  it("puts defaults and updates with the expected method", async () => {
    const defaults = clientReturning({
      configured: true,
      defaults: {
        default_provider_connection_id: "conn-1",
        default_model_id: "model-1",
        default_runtime_configuration_id: "runtime-native",
        contract_version: "v1",
      },
      contract_version: "v1",
    });
    await setExecutionDefaults(defaults.client, {
      default_provider_connection_id: "conn-1",
      default_model_id: "model-1",
      default_runtime_configuration_id: "runtime-native",
    });
    expect(defaults.fetchMock.mock.calls[0]?.[1]?.method).toBe("PUT");

    const runtime = clientReturning({
      runtime_configuration_id: "runtime-native",
      runtime_type: "native",
      display_name: "Native",
      enabled: false,
      contract_version: "v1",
    });
    const updated = await updateRuntimeConfiguration(runtime.client, "runtime-native", {
      display_name: "Native",
      enabled: false,
    });
    expect(runtime.fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/settings/runtimes/runtime-native");
    expect(updated.enabled).toBe(false);
  });
});
