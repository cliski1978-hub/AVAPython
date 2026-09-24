// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { htmlContent } from "../model";
import { useDocuments } from "./DocumentProvider";
import { DocumentProvider } from "./DocumentProvider";

const backendDocument = {
  document_id: "document-backend-1",
  title: "Backend document",
  content: "<p>Backend HTML</p>",
  content_format: "html" as const,
  created_at: "2026-09-19T00:00:00Z",
  updated_at: "2026-09-19T01:00:00Z",
  contract_version: "v1" as const,
};

function hydrateWith(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  return {
    client: new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock }),
    fetchMock,
  };
}

describe("DocumentProvider hydration", () => {
  it("reports hydration in progress until the backend list settles", async () => {
    let resolveHydration: ((response: Response) => void) | undefined;
    const hydration = new Promise<Response>((resolve) => { resolveHydration = resolve; });
    const fetchMock = vi.fn().mockReturnValue(hydration);
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    expect(value?.state.loading).toBe(true);
    resolveHydration?.(new Response(JSON.stringify({ contract_version: "v1", documents: [] }), { status: 200 }));
    await waitFor(() => expect(value?.state.loading).toBe(false));
    expect(value?.state.error).toBeNull();
  });

  it("replaces local startup authority with clean backend documents and selects the first", async () => {
    const { client, fetchMock } = hydrateWith({ contract_version: "v1", documents: [backendDocument] });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/documents", expect.any(Object));
    expect(value?.state.documents).toEqual([{
      id: "document-backend-1", title: "Backend document",
      content: { format: "html", value: "<p>Backend HTML</p>" },
      createdAt: "2026-09-19T00:00:00Z", updatedAt: "2026-09-19T01:00:00Z", isDirty: false,
    }]);
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
    expect(value?.activeDocument?.isDirty).toBe(false);
  });

  it("keeps an empty durable collection empty without creating a document", async () => {
    const { client, fetchMock } = hydrateWith({ contract_version: "v1", documents: [] });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(value?.state).toMatchObject({ documents: [], activeDocumentId: null, error: null });
  });

  it("records hydration failure without inventing local persisted-looking state", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("documents unavailable"));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    expect(value?.state.documents).toEqual([]);
    expect(value?.state.activeDocumentId).toBeNull();
    expect(value?.state.error?.message).toBe("documents unavailable");
  });

  it("creates once through the backend, inserts its authoritative response, and selects it", async () => {
    const created = {
      ...backendDocument,
      document_id: "document-backend-2",
      title: "Untitled Document",
      content: "<p></p>",
      created_at: "2026-09-19T02:00:00Z",
      updated_at: "2026-09-19T02:00:00Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(created), { status: 201 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    const randomUuid = vi.spyOn(crypto, "randomUUID");
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.createDocument();
    await waitFor(() => expect(value?.state.activeDocumentId).toBe("document-backend-2"));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/documents");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ title: "Untitled Document", content: "<p></p>", content_format: "html" }),
    });
    expect(randomUuid).not.toHaveBeenCalled();
    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1", "document-backend-2"]);
    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-2", title: "Untitled Document", isDirty: false,
      createdAt: "2026-09-19T02:00:00Z", updatedAt: "2026-09-19T02:00:00Z",
    });
    randomUuid.mockRestore();
  });

  it("keeps current documents and selection when backend creation fails", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockRejectedValueOnce(new Error("creation unavailable"));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.createDocument();
    await waitFor(() => expect(value?.state.error?.message).toBe("creation unavailable"));

    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1"]);
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
    expect(value?.state.error?.message).toBe("creation unavailable");
    expect(value?.state.isCreating).toBe(false);
  });

  it("persists a rename through the existing document path, then save persists title and content", async () => {
    const renamed = {
      ...backendDocument,
      title: "My Document (normalized)",
      updated_at: "2026-09-19T02:30:00Z",
    };
    const saved = {
      ...backendDocument,
      title: "My Document (normalized)",
      content: "<p>Saved HTML</p>",
      created_at: "2026-09-19T02:00:00Z",
      updated_at: "2026-09-19T03:00:00Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.renameDocument("document-backend-1", "My Document");
    await waitFor(() => expect(value?.state.documents[0].title).toBe("My Document (normalized)"));

    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/documents/document-backend-1");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ title: "My Document" }),
    });
    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-1", title: "My Document (normalized)",
      content: { value: "<p>Backend HTML</p>" }, isDirty: false,
    });

    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Saved HTML</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    await value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.updatedAt).toBe("2026-09-19T03:00:00Z"));

    expect(fetchMock.mock.calls[2][1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ title: "My Document (normalized)", content: "<p>Saved HTML</p>", content_format: "html" }),
    });
    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-1", title: "My Document (normalized)", content: { value: "<p>Saved HTML</p>" },
      updatedAt: "2026-09-19T03:00:00Z", isDirty: false,
    });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
    expect(value?.state.isSaving).toBe(false);
  });

  it("keeps local edits dirty and selected when backend save fails", async () => {
    const renamed = { ...backendDocument, title: "Unsaved title", updated_at: "2026-09-19T02:30:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }))
      .mockRejectedValueOnce(new Error("save unavailable"));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.renameDocument("document-backend-1", "Unsaved title");
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Unsaved HTML</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    await value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.state.error?.message).toBe("save unavailable"));

    expect(value?.activeDocument).toMatchObject({ title: "Unsaved title", content: { value: "<p>Unsaved HTML</p>" }, isDirty: true });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
  });

  it("does not replace newer edits when an earlier save response arrives", async () => {
    let resolveSave: ((response: Response) => void) | undefined;
    const saveResponse = new Promise<Response>((resolve) => { resolveSave = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockReturnValueOnce(saveResponse);
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Snapshot A</p>"));
    await waitFor(() => expect(value?.activeDocument?.content.value).toBe("<p>Snapshot A</p>"));
    const saving = value?.saveDocument("document-backend-1");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Newer B</p>"));
    await waitFor(() => expect(value?.activeDocument?.content.value).toBe("<p>Newer B</p>"));
    resolveSave?.(new Response(JSON.stringify({
      ...backendDocument, content: "<p>Snapshot A</p>", updated_at: "2026-09-19T03:00:00Z",
    }), { status: 200 }));
    await saving;

    expect(value?.activeDocument).toMatchObject({ content: { value: "<p>Newer B</p>" }, isDirty: true });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
  });

  it("selects complete hydrated snapshots locally without fetching and preserves dirty edits", async () => {
    const secondDocument = {
      ...backendDocument,
      document_id: "document-backend-2",
      title: "Second backend document",
      content: "<p>Second canonical HTML</p>",
    };
    const { client, fetchMock } = hydrateWith({
      contract_version: "v1",
      documents: [backendDocument, secondDocument],
    });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.selectDocument("document-backend-2");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-2"));

    expect(value?.activeDocument?.content).toEqual({ format: "html", value: "<p>Second canonical HTML</p>" });
    expect(fetchMock).toHaveBeenCalledOnce();

    value?.updateDocumentContent("document-backend-2", htmlContent("<p>Unsaved second document</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    value?.selectDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-1"));
    value?.selectDocument("document-backend-2");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-2"));

    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-2",
      content: { value: "<p>Unsaved second document</p>" },
      isDirty: true,
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("marks creation in progress and ignores duplicate create commands", async () => {
    let resolveCreate: ((response: Response) => void) | undefined;
    const creation = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockReturnValueOnce(creation);
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    const first = value?.createDocument();
    const duplicate = value?.createDocument();
    await waitFor(() => expect(value?.state.isCreating).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveCreate?.(new Response(JSON.stringify({
      ...backendDocument, document_id: "document-backend-2", title: "Untitled Document", content: "<p></p>",
    }), { status: 201 }));
    await Promise.all([first, duplicate]);
    await waitFor(() => expect(value?.state.isCreating).toBe(false));
    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1", "document-backend-2"]);
  });

  it("marks save in progress and ignores duplicate save commands", async () => {
    let resolveSave: ((response: Response) => void) | undefined;
    const save = new Promise<Response>((resolve) => { resolveSave = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockReturnValueOnce(save);
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Save once</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    const first = value?.saveDocument("document-backend-1");
    const duplicate = value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.state.isSaving).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveSave?.(new Response(JSON.stringify({ ...backendDocument, content: "<p>Save once</p>", updated_at: "2026-09-19T05:00:00Z" }), { status: 200 }));
    await Promise.all([first, duplicate]);
    await waitFor(() => expect(value?.state.isSaving).toBe(false));
    expect(value?.activeDocument).toMatchObject({ isDirty: false, updatedAt: "2026-09-19T05:00:00Z" });
  });

  it("clears a save error after a later save succeeds", async () => {
    const saved = { ...backendDocument, content: "<p>Recovered</p>", updated_at: "2026-09-19T06:00:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockRejectedValueOnce(new Error("temporary save failure"))
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Recovered</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    await value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.state.error?.message).toBe("temporary save failure"));
    await value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(false));

    expect(value?.state.error).toBeNull();
    expect(value?.state.isSaving).toBe(false);
  });
});

describe("DocumentProvider revision loading", () => {
  const revisionBody = (revisionId: string, revisionNumber: number, content: string, createdAt: string) => ({
    revision_id: revisionId,
    document_id: "document-backend-1",
    revision_number: revisionNumber,
    title: "Backend document",
    content,
    content_format: "html" as const,
    created_at: createdAt,
    contract_version: "v1" as const,
  });
  const history = {
    document_id: "document-backend-1",
    revisions: [
      revisionBody("revision-1", 1, "<p>Version one</p>", "2026-09-19T00:00:00Z"),
      revisionBody("revision-2", 2, "<p>Version two</p>", "2026-09-19T01:00:00Z"),
    ],
    contract_version: "v1" as const,
  };

  it("loads revisions once through the shared client, preserving backend order and mapping names", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(history), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    const revisions = await value!.loadRevisions("document-backend-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/documents/document-backend-1/revisions");
    expect(revisions).toEqual([
      { revisionId: "revision-1", documentId: "document-backend-1", revisionNumber: 1, title: "Backend document", content: { format: "html", value: "<p>Version one</p>" }, createdAt: "2026-09-19T00:00:00Z" },
      { revisionId: "revision-2", documentId: "document-backend-1", revisionNumber: 2, title: "Backend document", content: { format: "html", value: "<p>Version two</p>" }, createdAt: "2026-09-19T01:00:00Z" },
    ]);
  });

  it("returns an empty history for a known document without inventing an initial revision", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ document_id: "document-backend-1", revisions: [], contract_version: "v1" }), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    await expect(value!.loadRevisions("document-backend-1")).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("rejects on failure without fabricating history or polluting provider error state", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockRejectedValueOnce(new Error("revisions unavailable"));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));

    await expect(value!.loadRevisions("document-backend-1")).rejects.toThrow("revisions unavailable");
    expect(value?.state.error).toBeNull();
    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1"]);
  });

  it("leaves current document state untouched when revisions are loaded", async () => {
    const renamed = { ...backendDocument, title: "Dirty title", updated_at: "2026-09-19T02:30:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(history), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.renameDocument("document-backend-1", "Dirty title");
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Dirty content</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));

    const stateBefore = value?.state;
    const revisions = await value!.loadRevisions("document-backend-1");

    expect(revisions).toHaveLength(2);
    expect(value?.state).toBe(stateBefore);
    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-1", title: "Dirty title",
      content: { value: "<p>Dirty content</p>" }, isDirty: true,
    });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
  });

  it("never fetches revision history on hydration, selection, create, or save", async () => {
    const created = {
      ...backendDocument,
      document_id: "document-backend-2",
      title: "Untitled Document",
      content: "<p></p>",
      created_at: "2026-09-19T02:00:00Z",
      updated_at: "2026-09-19T02:00:00Z",
    };
    const saved = { ...backendDocument, content: "<p>Dirty then saved</p>", updated_at: "2026-09-19T03:00:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(created), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(saved), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(history), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.selectDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-1"));
    await value?.createDocument();
    await waitFor(() => expect(value?.state.activeDocumentId).toBe("document-backend-2"));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>Dirty then saved</p>"));
    await waitFor(() => expect(value?.state.documents.find((document) => document.id === "document-backend-1")?.isDirty).toBe(true));
    await value?.saveDocument("document-backend-1");
    await waitFor(() => expect(value?.state.isSaving).toBe(false));
    expect(value?.state.documents.find((document) => document.id === "document-backend-1"))
      .toMatchObject({ content: { value: "<p>Dirty then saved</p>" }, isDirty: false });

    const revisionCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/revisions"));
    expect(revisionCalls).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await value!.loadRevisions("document-backend-1");
    expect(fetchMock.mock.calls[3][0]).toBe("http://localhost:8000/documents/document-backend-1/revisions");
  });
});

describe("DocumentProvider close — clears the editor without touching the durable list", () => {
  const docA = { ...backendDocument, document_id: "document-backend-1", title: "Document A" };
  const docB = { ...backendDocument, document_id: "document-backend-2", title: "Document B" };

  it("clears selection, keeps both documents, and issues no delete/remove request", async () => {
    const { client, fetchMock } = hydrateWith({ contract_version: "v1", documents: [docA, docB] });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    expect(value?.activeDocument?.id).toBe("document-backend-1");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    value?.closeDocument("document-backend-1");
    await waitFor(() => expect(value?.state.activeDocumentId).toBeNull());

    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1", "document-backend-2"]);
    expect(value?.activeDocument).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    value?.selectDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-1"));
    expect(value?.activeDocument?.title).toBe("Document A");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("issues only GET requests across close and reopen", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValue(new Response(JSON.stringify({ contract_version: "v1", documents: [docA, docB] }), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.closeDocument("document-backend-1");
    await waitFor(() => expect(value?.state.activeDocumentId).toBeNull());
    value?.selectDocument("document-backend-1");
    await waitFor(() => expect(value?.activeDocument?.id).toBe("document-backend-1"));

    const methods = fetchMock.mock.calls.map(([_url, init]) => (init as RequestInit | undefined)?.method ?? "GET");
    expect(methods).toEqual(["GET"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("closing a non-active document is a no-op", async () => {
    const { client, fetchMock } = hydrateWith({ contract_version: "v1", documents: [docA, docB] });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.closeDocument("document-backend-2");
    await waitFor(() => expect(value?.state.activeDocumentId).toBe("document-backend-1"));
    expect(value?.state.documents.map((document) => document.id)).toEqual(["document-backend-1", "document-backend-2"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refresh consistency: list after close matches the list after rehydration", async () => {
    const body = { contract_version: "v1", documents: [docA, docB] };
    const fetchMock = vi.fn()
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status: 200 })));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    const { unmount } = render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    const before = value?.state.documents.map((document) => document.id);
    value?.closeDocument("document-backend-1");
    await waitFor(() => expect(value?.state.activeDocumentId).toBeNull());
    const afterClose = value?.state.documents.map((document) => document.id);

    expect(afterClose).toEqual(before);

    unmount();
    let refreshed: ReturnType<typeof useDocuments> | undefined;
    function RefreshCapture() { refreshed = useDocuments(); return null; }
    render(<DocumentProvider client={client}><RefreshCapture /></DocumentProvider>);
    await waitFor(() => expect(refreshed?.state.loading).toBe(false));
    expect(refreshed?.state.documents.map((document) => document.id)).toEqual(before);
  });
});

describe("DocumentProvider rename — persists at completion without navigation", () => {
  const renamedTitle = "Design Notes";
  const renamed = { ...backendDocument, title: renamedTitle, updated_at: "2026-09-19T03:00:00Z" };

  it("persists the rename immediately, keeping the same document id and content", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.renameDocument("document-backend-1", renamedTitle);
    await waitFor(() => expect(value?.activeDocument?.title).toBe(renamedTitle));

    expect(value?.activeDocument).toMatchObject({
      id: "document-backend-1", title: renamedTitle, content: { value: "<p>Backend HTML</p>" }, isDirty: false,
    });
    expect(value?.state.documents).toHaveLength(1);
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/documents/document-backend-1");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ title: renamedTitle }),
    });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
  });

  it("survives immediate rehydration with the new title", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let first: ReturnType<typeof useDocuments> | undefined;
    function FirstCapture() { first = useDocuments(); return null; }
    const { unmount } = render(<DocumentProvider client={client}><FirstCapture /></DocumentProvider>);
    await waitFor(() => expect(first?.state.loading).toBe(false));
    await first?.renameDocument("document-backend-1", renamedTitle);
    await waitFor(() => expect(first?.activeDocument?.title).toBe(renamedTitle));
    unmount();

    let second: ReturnType<typeof useDocuments> | undefined;
    function SecondCapture() { second = useDocuments(); return null; }
    const rehydratingClient = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: vi.fn().mockResolvedValue(new Response(JSON.stringify({ contract_version: "v1", documents: [renamed] }), { status: 200 })),
    });
    render(<DocumentProvider client={rehydratingClient}><SecondCapture /></DocumentProvider>);
    await waitFor(() => expect(second?.state.loading).toBe(false));
    expect(second?.activeDocument?.id).toBe("document-backend-1");
    expect(second?.activeDocument?.title).toBe(renamedTitle);
    expect(second?.activeDocument?.content.value).toBe("<p>Backend HTML</p>");
  });

  it("does not falsely present a failed rename as durably saved", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockRejectedValueOnce(new Error("rename unavailable"));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    await value?.renameDocument("document-backend-1", "Optimistic Title");
    await waitFor(() => expect(value?.state.error?.message).toBe("rename unavailable"));

    expect(value?.activeDocument).toMatchObject({ title: "Optimistic Title", isDirty: true });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
    expect(value?.state.documents).toHaveLength(1);
  });

  it("keeps pending content edits dirty while a rename is persisted", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ contract_version: "v1", documents: [backendDocument] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(renamed), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    let value: ReturnType<typeof useDocuments> | undefined;
    function Capture() { value = useDocuments(); return null; }

    render(<DocumentProvider client={client}><Capture /></DocumentProvider>);
    await waitFor(() => expect(value?.state.loading).toBe(false));
    value?.updateDocumentContent("document-backend-1", htmlContent("<p>WIP</p>"));
    await waitFor(() => expect(value?.activeDocument?.isDirty).toBe(true));
    await value?.renameDocument("document-backend-1", renamedTitle);
    await waitFor(() => expect(value?.activeDocument?.title).toBe(renamedTitle));

    expect(value?.activeDocument).toMatchObject({ title: renamedTitle, content: { value: "<p>WIP</p>" }, isDirty: true });
    expect(value?.state.activeDocumentId).toBe("document-backend-1");
  });
});
