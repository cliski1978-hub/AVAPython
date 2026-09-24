// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiClient } from "@ava/api-client";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { DocumentProvider } from "../state/DocumentProvider";
import { htmlContent } from "../model";
import { useDocuments } from "../state/DocumentProvider";
import { DocumentWorkspace } from "./DocumentWorkspace";

let nextDocumentId = 2;
const client = new ApiClient({
  baseUrl: "http://localhost:8000",
  fetchImpl: async (_input, init) => {
    if (init?.method === "POST") {
      const request = JSON.parse(String(init.body)) as { title: string; content: string; content_format: "html" };
      const document_id = `document-${nextDocumentId++}`;
      return new Response(JSON.stringify({
        document_id, title: request.title, content: request.content, content_format: request.content_format,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
      }), { status: 201 });
    }
    if (init?.method === "PATCH") {
      const request = JSON.parse(String(init.body)) as { title?: string; content?: string; content_format?: "html" };
      return new Response(JSON.stringify({
        document_id: "document-1",
        title: request.title ?? "Untitled Document",
        content: request.content ?? "<p>Document</p>",
        content_format: request.content_format ?? "html",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T02:00:00Z",
        contract_version: "v1",
      }), { status: 200 });
    }
    return new Response(JSON.stringify({
      contract_version: "v1",
      documents: [{
        document_id: "document-1",
        title: "Untitled Document",
        content: "<p>Document</p>",
        content_format: "html",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        contract_version: "v1",
      }],
    }), { status: 200 });
  },
});

function listResponse(): Response {
  return new Response(JSON.stringify({
    contract_version: "v1",
    documents: [{
      document_id: "document-1", title: "Untitled Document", content: "<p>Document</p>", content_format: "html",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
    }],
  }), { status: 200 });
}

function createRequestCalls(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([_input, init]) => (init as RequestInit | undefined)?.method === "POST").length;
}

function patchRequestCalls(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([_input, init]) => (init as RequestInit | undefined)?.method === "PATCH").length;
}

function deleteRequestCalls(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([_input, init]) => (init as RequestInit | undefined)?.method === "DELETE").length;
}

function twoDocListResponse(): Response {
  return new Response(JSON.stringify({
    contract_version: "v1",
    documents: [
      {
        document_id: "document-1", title: "Document A", content: "<p>A</p>", content_format: "html",
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
      },
      {
        document_id: "document-2", title: "Document B", content: "<p>B</p>", content_format: "html",
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
      },
    ],
  }), { status: 200 });
}

function isDisabled(element: HTMLElement): boolean {
  return (element as HTMLButtonElement).disabled === true;
}

describe("DocumentWorkspace", () => {
  it("renders AVA document metadata, editor surface, and formatting controls", async () => {
    render(<DocumentProvider client={client}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });
    expect(screen.getAllByText("Untitled Document")).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Document content" })).toBeTruthy();
    for (const name of ["Bold", "Italic", "Heading 1", "Heading 2", "Bullet list", "Ordered list", "Undo", "Redo"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("reconstructs the editor from AVA state after unmounting", async () => {
    function Fixture() {
      const { activeDocument, updateDocumentContent } = useDocuments();
      const [mounted, setMounted] = useState(true);
      return <>
        <button onClick={() => activeDocument && updateDocumentContent(activeDocument.id, htmlContent("<p>Preserved content</p>"))}>Change</button>
        <button onClick={() => setMounted(false)}>Unmount</button>
        <button onClick={() => setMounted(true)}>Remount</button>
        {mounted && <DocumentWorkspace />}
      </>;
    }
    render(<DocumentProvider client={client}><Fixture /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Unmount" }));
    fireEvent.click(screen.getByRole("button", { name: "Remount" }));
    expect(screen.getByRole("textbox", { name: "Document content" }).innerHTML).toContain("Preserved content");
  });

  it("allows a title to be cleared before a replacement is committed", async () => {
    render(<DocumentProvider client={client}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    const title = screen.getByRole("textbox", { name: "Document title" });
    fireEvent.change(title, { target: { value: "" } });
    expect((title as HTMLInputElement).value).toBe("");
    fireEvent.change(title, { target: { value: "New Name" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(screen.getByText("New Name")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());
    expect(isDisabled(screen.getByRole("button", { name: "Save document" }))).toBe(true);
  });

  it("ends rename mode when navigating to another document or creating one", async () => {
    render(<DocumentProvider client={client}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });
    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    await screen.findAllByText("Untitled Document 2");
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.click(screen.getByRole("button", { name: "Untitled Document" }));
    expect(screen.queryByRole("textbox", { name: "Document title" })).toBeNull();
    expect(screen.getAllByText("Untitled Document")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    await screen.findAllByText("Untitled Document 3");
    expect(screen.queryByRole("textbox", { name: "Document title" })).toBeNull();
    expect(screen.getAllByText("Untitled Document 3")).toHaveLength(2);
  });

  it("disables New Document while creation is pending and issues a single create request", async () => {
    let resolveCreate: ((response: Response) => void) | undefined;
    const creation = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listResponse())
      .mockReturnValueOnce(creation);
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    const createButton = () => screen.getByRole("button", { name: "New Document" });
    fireEvent.click(createButton());
    await waitFor(() => expect(isDisabled(createButton())).toBe(true));
    fireEvent.click(createButton());
    expect(createRequestCalls(fetchMock)).toBe(1);

    resolveCreate?.(new Response(JSON.stringify({
      document_id: "document-2", title: "Untitled Document", content: "<p></p>", content_format: "html",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
    }), { status: 201 }));
    await waitFor(() => expect(isDisabled(createButton())).toBe(false));
    expect(createRequestCalls(fetchMock)).toBe(1);
  });

  it("keeps a rename dirty white-on-blue while its persistence is pending, then reconciles clean", async () => {
    let resolveRename: ((response: Response) => void) | undefined;
    const pendingRename = new Promise<Response>((resolve) => { resolveRename = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listResponse())
      .mockReturnValueOnce(pendingRename);
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Document title" }), { target: { value: "Dirty Title" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(screen.getByText("Unsaved changes")).toBeTruthy());
    await waitFor(() => expect(patchRequestCalls(fetchMock)).toBe(1));

    const saveButton = () => screen.getByRole("button", { name: "Save document" });
    expect(isDisabled(saveButton())).toBe(false);
    expect(saveButton().style.color).toBe("rgb(255, 255, 255)");
    expect(screen.getByRole("button", { name: "Close document" }).style.color).toBe("rgb(255, 255, 255)");

    resolveRename?.(new Response(JSON.stringify({
      document_id: "document-1", title: "Dirty Title", content: "<p>Document</p>", content_format: "html",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T02:00:00Z", contract_version: "v1",
    }), { status: 200 }));
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());
    expect(isDisabled(saveButton())).toBe(true);
    expect(patchRequestCalls(fetchMock)).toBe(1);
  });

  it("renders each document title in the sidebar and marks the selected one", async () => {
    render(<DocumentProvider client={client}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    const items = document.querySelectorAll(".ava-doc-nav-item");
    expect(items.length).toBe(1);
    expect(items[0].textContent).toBe("Untitled Document");
    expect(items[0].getAttribute("aria-current")).toBe("page");

    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    await screen.findAllByText("Untitled Document 2");
    const after = Array.from(document.querySelectorAll(".ava-doc-nav-item"));
    expect(after.map((item) => item.textContent)).toEqual([
      "Untitled Document",
      "Untitled Document 2",
    ]);
    expect(after[1].getAttribute("aria-current")).toBe("page");
    expect(after[0].getAttribute("aria-current")).toBeNull();

    fireEvent.click(after[0] as HTMLButtonElement);
    expect(after[0].getAttribute("aria-current")).toBe("page");
    expect(after[1].getAttribute("aria-current")).toBeNull();
  });

  it("shows the dirty marker in the sidebar for a rename that has not persisted", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listResponse())
      .mockRejectedValueOnce(new Error("offline"));
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Document title" }), { target: { value: "Draft Notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(screen.getByText("Unsaved changes")).toBeTruthy());

    const item = Array.from(document.querySelectorAll(".ava-doc-nav-item"))
      .find((element) => (element.textContent ?? "").includes("Draft Notes"));
    expect(item).toBeDefined();
    expect(item!.textContent).toBe("Draft Notes \u2022");
    expect(item!.getAttribute("aria-current")).toBe("page");
  });

  it("persists a completed rename with a title-only update, leaving content intact", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(listResponse())
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
        document_id: "document-1", title: "New Name", content: "<p>Document</p>", content_format: "html",
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T02:00:00Z", contract_version: "v1",
      }), { status: 200 })));
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Document title" }), { target: { value: "New Name" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());

    expect(screen.getByRole("textbox", { name: "Document content" }).innerHTML).toContain("Document");
    expect(Array.from(document.querySelectorAll(".ava-doc-nav-item")).map((item) => item.textContent))
      .toEqual(["New Name"]);
    const patchBody = JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body as string));
    expect(patchBody).toEqual({ title: "New Name" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "New Name" }).getAttribute("aria-current")).toBe("page");
  });

  it("Close closes only the editor and leaves every document in the sidebar", async () => {
    const fetchMock = vi.fn().mockResolvedValue(twoDocListResponse());
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    expect(Array.from(document.querySelectorAll(".ava-doc-nav-item")).map((item) => item.textContent))
      .toEqual(["Document A", "Document B"]);

    fireEvent.click(screen.getByRole("button", { name: "Close document" }));

    expect(await screen.findByText("No document open")).toBeTruthy();
    const items = Array.from(document.querySelectorAll(".ava-doc-nav-item"));
    expect(items.map((item) => item.textContent)).toEqual(["Document A", "Document B"]);
    expect(items.every((item) => item.getAttribute("aria-current") == null)).toBe(true);
    expect(deleteRequestCalls(fetchMock)).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reopens a closed document immediately without rehydration or refresh", async () => {
    const fetchMock = vi.fn().mockResolvedValue(twoDocListResponse());
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    fireEvent.click(screen.getByRole("button", { name: "Close document" }));
    await screen.findByText("No document open");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const reopened = Array.from(document.querySelectorAll(".ava-doc-nav-item"))
      .find((item) => item.textContent === "Document A");
    fireEvent.click(reopened as HTMLButtonElement);

    expect(await screen.findByRole("textbox", { name: "Document content" })).toBeTruthy();
    expect(screen.queryByText("No document open")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the dirty-close confirmation and preserves the list after closing", async () => {
    const confirmSpy = vi.fn();
    window.confirm = confirmSpy;
    const fetchMock = vi.fn().mockImplementation(
      (_input, init) => (init as RequestInit | undefined)?.method === "PATCH"
        ? Promise.reject(new Error("offline"))
        : Promise.resolve(twoDocListResponse()),
    );
    const controlled = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    render(<DocumentProvider client={controlled}><DocumentWorkspace /></DocumentProvider>);
    await screen.findByRole("textbox", { name: "Document content" });

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Document title" }), { target: { value: "Dirty A" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(screen.getByText("Unsaved changes")).toBeTruthy());

    confirmSpy.mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "Close document" }));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(screen.getByText("Dirty A")).toBeTruthy();
    expect(screen.getByText("Unsaved changes")).toBeTruthy();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Close document" }));
    expect(await screen.findByText("No document open")).toBeTruthy();
    expect(Array.from(document.querySelectorAll(".ava-doc-nav-item")).map((item) => item.textContent))
      .toEqual(["Dirty A \u2022", "Document B"]);
  });
});
