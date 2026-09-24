// @vitest-environment jsdom
/**
 * LIVE Step 32 end-to-end: real Web application → real @ava/api-client →
 * real HTTP POST /runs → backend RunRequest.workspace_id → WorkspaceResolver →
 * RuntimeWorkspaceBinding → runtime.
 *
 * Opt-in: skipped unless AVA_LIVE_BACKEND_URL is set (e.g. to the dev/test
 * harness on 127.0.0.1:8765). This file intentionally does NOT mock
 * @ava/api-client; it exercises the production UI and client against a real
 * running backend.
 */
import { ApiClient } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

const env =
  (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env ?? {};
const liveBackendUrl = env.AVA_LIVE_BACKEND_URL;
const liveWorkspaceId = env.AVA_LIVE_WORKSPACE_ID ?? "ephemeral-validation-live";

// jsdom's AbortController produces a jsdom AbortSignal, which Node's fetch
// (undici) rejects with "Expected signal ... to be an instance of AbortSignal".
// This only affects the test sandbox, not browsers. Keep real HTTP by dropping
// the signal; ApiClient timeout still completes the request on success.
const nodeFetch: typeof fetch = (input, init) =>
  fetch(input, { ...init, signal: undefined });

function liveClient(baseUrl: string): ApiClient {
  return new ApiClient({ baseUrl, fetchImpl: nodeFetch });
}

describe.skipIf(!liveBackendUrl)("AppWorkspace live backend", () => {
  it("discovers the approved ephemeral workspace in the real selector", async () => {
    const client = liveClient(liveBackendUrl as string);
    render(<AppWorkspace client={client} />);

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Validation Ephemeral (live)" })).toBeTruthy();
    });
    expect(screen.getByRole("option", { name: "None" })).toBeTruthy();
  });

  it("selects the workspace and submits a real run that carries workspace_id", async () => {
    const client = liveClient(liveBackendUrl as string);
    render(<AppWorkspace client={client} />);

    const select = (await screen.findByLabelText("Select workspace")) as HTMLSelectElement;
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: "Validation Ephemeral (live)" }),
      ).toBeTruthy();
    });
    fireEvent.change(select, { target: { value: liveWorkspaceId } });
    expect(select.value).toBe(liveWorkspaceId);

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "hello live backend" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(
        screen.getAllByText(/hello live backend/).length,
      ).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(
        screen.queryAllByText(new RegExp(`${liveWorkspaceId}/ephemeral`)).length,
      ).toBeGreaterThan(0);
    }, { timeout: 10000 });
    expect(select.value).toBe(liveWorkspaceId);
  });

  it("keeps workspace independent from the OpenHands Local profile", async () => {
    const client = liveClient(liveBackendUrl as string);
    render(<AppWorkspace client={client} />);

    const profileSelect = (await screen.findByLabelText(
      "Select execution profile",
    )) as HTMLSelectElement;
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Validation Ephemeral (live)" })).toBeTruthy();
    });
    fireEvent.change(profileSelect, { target: { value: "openhands-local" } });
    expect(profileSelect.value).toBe("openhands-local");

    const select = (screen.getByLabelText("Select workspace") as HTMLSelectElement);
    expect(select.value).toBe("");
    // Selecting the profile did not select a workspace (no auto-grant).
    expect(screen.getByRole("option", { name: "None" })).toBeTruthy();

    fireEvent.change(select, { target: { value: liveWorkspaceId } });
    expect(select.value).toBe(liveWorkspaceId);

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "openhands profile with workspace" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(
        screen.getAllByText(/openhands profile with workspace/).length,
      ).toBeGreaterThan(0);
    });
  });

  it("keeps Auto routing independent of the selected workspace", async () => {
    const client = liveClient(liveBackendUrl as string);
    render(<AppWorkspace client={client} />);

    const select = (await screen.findByLabelText("Select workspace")) as HTMLSelectElement;
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Validation Ephemeral (live)" })).toBeTruthy();
    });
    fireEvent.change(select, { target: { value: liveWorkspaceId } });

    fireEvent.change(screen.getByLabelText("Select execution profile"), {
      target: { value: "auto" },
    });
    expect(select.value).toBe(liveWorkspaceId);
  });
});