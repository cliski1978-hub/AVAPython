import { describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  createDocument,
  getDocument,
  getDocumentRevision,
  listDocumentRevisions,
  listDocuments,
  updateDocument,
} from "./index";

const document = {
  document_id: "document-1",
  title: "Design notes",
  content: "<p>Durable content</p>",
  content_format: "html" as const,
  created_at: "2026-09-19T00:00:00Z",
  updated_at: "2026-09-19T01:00:00Z",
  contract_version: "v1" as const,
};

function clientWith(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }),
  );
  return {
    client: new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock }),
    fetchMock,
  };
}

describe("document transport", () => {
  it("requests GET /documents and returns the backend response unchanged", async () => {
    const response = { documents: [document], contract_version: "v1" as const };
    const { client, fetchMock } = clientWith(response);

    await expect(listDocuments(client)).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/documents", expect.any(Object));
  });

  it("requests GET /documents/{document_id} and returns the backend response unchanged", async () => {
    const { client, fetchMock } = clientWith(document);

    await expect(getDocument(client, "document-1")).resolves.toEqual(document);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/documents/document-1", expect.any(Object));
  });

  it("posts the exact create payload without client-owned identity fields", async () => {
    const { client, fetchMock } = clientWith(document);
    const request = { title: "Design notes", content: "<p>Durable content</p>", content_format: "html" as const };

    await expect(createDocument(client, request)).resolves.toEqual(document);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/documents");
    expect(init).toMatchObject({ method: "POST", body: JSON.stringify(request) });
  });

  it("patches the exact update payload and returns the backend response unchanged", async () => {
    const updated = { ...document, content: "<p>Updated</p>", updated_at: "2026-09-19T02:00:00Z" };
    const { client, fetchMock } = clientWith(updated);
    const request = { content: "<p>Updated</p>", content_format: "html" as const };

    await expect(updateDocument(client, "document-1", request)).resolves.toEqual(updated);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/documents/document-1");
    expect(init).toMatchObject({ method: "PATCH", body: JSON.stringify(request) });
  });
});

describe("document revision transport", () => {
  const revision = {
    revision_id: "revision-2",
    document_id: "document-1",
    revision_number: 2,
    title: "Design notes",
    content: "<p>Reverted content</p>",
    content_format: "html" as const,
    created_at: "2026-09-19T02:00:00Z",
    contract_version: "v1" as const,
  };
  const history = {
    document_id: "document-1",
    revisions: [
      { ...revision, revision_id: "revision-1", revision_number: 1, content: "<p>First version</p>" },
      revision,
    ],
    contract_version: "v1" as const,
  };

  it("requests GET /documents/{document_id}/revisions with no body and preserves backend ordering", async () => {
    const { client, fetchMock } = clientWith(history);

    const result = await listDocumentRevisions(client, "document-1");
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/documents/document-1/revisions");
    expect(init).not.toHaveProperty("method");
    expect(init).not.toHaveProperty("body");
    expect(result).toEqual(history);
    expect(result.revisions.map((r) => r.revision_number)).toEqual([1, 2]);
  });

  it("requests GET /documents/{document_id}/revisions/{revision_id} and returns the revision unchanged", async () => {
    const { client, fetchMock } = clientWith(revision);

    const result = await getDocumentRevision(client, "document-1", "revision-2");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/documents/document-1/revisions/revision-2");
    expect(init.body).toBeUndefined();
    expect(result).toEqual(revision);
  });

  it("encodes document and revision ids in the URL path", async () => {
    const { client, fetchMock } = clientWith(revision);

    await getDocumentRevision(client, "doc with spaces", "rev/a b");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8000/documents/doc%20with%20spaces/revisions/rev%2Fa%20b",
    );
  });

  it("rejects on a backend error instead of returning a fallback history", async () => {
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Response(JSON.stringify({ error_code: "document_not_found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    await expect(listDocumentRevisions(client, "missing")).rejects.toBeInstanceOf(ApiError);
    await expect(getDocumentRevision(client, "document-1", "missing")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
