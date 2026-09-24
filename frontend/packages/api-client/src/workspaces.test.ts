import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, getWorkspaces } from "./index";

describe("getWorkspaces", () => {
  it("requests GET /workspaces and deserializes the typed response", async () => {
    const body = {
      contract_version: "v1",
      workspaces: [
        { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
        { workspace_id: "workspace-b", display_name: "Workspace B", kind: "ephemeral" },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    const workspaces = await getWorkspaces(client);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/workspaces",
      expect.any(Object),
    );
    expect(workspaces).toEqual(body);
    expect(workspaces.workspaces[0].workspace_id).toBe("workspace-a");
    expect(workspaces.workspaces[1].kind).toBe("ephemeral");
  });

  it("deserializes an empty workspace discovery response", async () => {
    const body = { contract_version: "v1", workspaces: [] };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    const workspaces = await getWorkspaces(client);

    expect(workspaces.workspaces).toEqual([]);
  });

  it("throws ApiError on a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "internal_error" }), { status: 500 }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    await expect(getWorkspaces(client)).rejects.toBeInstanceOf(ApiError);
  });
});