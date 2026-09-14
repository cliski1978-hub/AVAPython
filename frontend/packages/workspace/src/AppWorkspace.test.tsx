// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    getHealth: vi.fn().mockResolvedValue({
      status: "healthy",
      application: "AVA",
      contract_version: "v1",
    }),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

function chatTab() {
  return screen.getByRole("tab", { name: "Chat" });
}

function documentsTab() {
  return screen.getByRole("tab", { name: "Documents" });
}

describe("AppWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts in the chat workspace with the document workspace closed", () => {
    render(<AppWorkspace client={client} />);
    expect(chatTab().getAttribute("aria-selected")).toBe("true");
    expect(documentsTab().getAttribute("aria-selected")).toBe("false");
    expect(screen.getByText("No conversation selected.")).toBeTruthy();
    expect(screen.getByLabelText("Message")).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "Document content" }),
    ).toBeNull();
  });

  it("opens the document workspace and returns to chat", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: "Document content" }),
      ).toBeTruthy();
    });
    expect(documentsTab().getAttribute("aria-selected")).toBe("true");
    expect(chatTab().getAttribute("aria-selected")).toBe("false");

    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(chatTab().getAttribute("aria-selected")).toBe("true");
    });
  });

  it("preserves conversation state across workspace switches", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Hello preserved conversation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(
        screen.getAllByText("Hello preserved conversation").length,
      ).toBeGreaterThan(0);
    });

    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: "Document content" }),
      ).toBeTruthy();
    });

    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(
        screen.getAllByText("Hello preserved conversation").length,
      ).toBeGreaterThan(0);
    });
  });

  it("keeps the document editor mounted, preserving its session", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.click(documentsTab());
    const editorNode = await screen.findByRole("textbox", {
      name: "Document content",
    });
    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(chatTab().getAttribute("aria-selected")).toBe("true");
    });
    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(documentsTab().getAttribute("aria-selected")).toBe("true");
    });
    const editorNodeAfter = screen.getByRole("textbox", {
      name: "Document content",
    });
    expect(editorNodeAfter).toBe(editorNode);
  });
});