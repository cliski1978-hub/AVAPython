import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";
import { getToolFeatures, updateToolFeatures } from "./tool-features";

describe("tool feature settings transport", () => {
  it("uses the shared client and preserves versioned update payload", async () => {
    const payload = { framework_enabled: false, enabled_tool_ids: [], expected_version: 3 };
    const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ configuration: payload })));
    const client = new ApiClient({ baseUrl: "http://test", fetchImpl: fetcher });
    await getToolFeatures(client);
    await updateToolFeatures(client, payload);
    expect(fetcher.mock.calls[0][0]).toBe("http://test/settings/tool-features");
    const init = fetcher.mock.calls[1][1];
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual(payload);
  });
  it("surfaces administrative denial as ApiError", async () => {
    const client = new ApiClient({ baseUrl: "http://test", fetchImpl: vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error_code: "feature_administration_required", message: "Unavailable" }), { status: 403 },
    )) });
    await expect(updateToolFeatures(client, { framework_enabled: true, enabled_tool_ids: [], expected_version: 0 })).rejects.toBeInstanceOf(ApiError);
  });
});
