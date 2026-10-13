import { describe, expect, it, vi } from "vitest";

import type { AttachmentResponse } from "@ava/contracts";

import { ApiClient, ApiError, AttachmentInputError, createAttachment, deleteConversationAttachment, getAttachment, getAttachmentContent, listAttachments, listConversationAttachments, uploadConversationAttachment } from "./index";

const response: AttachmentResponse = {
  attachment_id: "attachment-1",
  file_name: "report.pdf",
  media_type: "application/pdf",
  size_bytes: 4,
  owner_type: "document",
  owner_id: "doc-1",
  status: "available",
  created_at: "2026-09-20T00:00:00Z",
  contract_version: "v1" as const,
};

function makeClient(fetchImpl: typeof fetch): ApiClient {
  return new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl });
}

function jsonClient(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
  return { client: makeClient(fetchMock), fetchMock };
}

describe("createAttachment", () => {
  it("posts to /attachments and returns the parsed AttachmentResponse", async () => {
    const { client, fetchMock } = jsonClient(response);

    const result = await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "report.pdf",
      ownerType: "document",
      ownerId: "doc-1",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/attachments");
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(result).toEqual(response);
  });

  it("sends the file and owner pair as FormData fields when associated", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "report.pdf",
      ownerType: "document",
      ownerId: "doc-1",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("owner_type")).toBe("document");
    expect(form.get("owner_id")).toBe("doc-1");
    const file = form.get("file") as File;
    expect(file.name).toBe("report.pdf");
    expect(file.type).toBe("application/pdf");
    expect(file.size).toBe(4);
  });

  it("sends only the file field for an unassociated upload", async () => {
    const unassociated = { ...response, owner_type: null, owner_id: null };
    const { client, fetchMock } = jsonClient(unassociated);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "report.pdf",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(Array.from(form as unknown as Iterable<[string, File]>).map(([key]) => key)).toEqual(["file"]);
    expect(form.has("owner_type")).toBe(false);
    expect(form.has("owner_id")).toBe(false);
  });

  it("never sends server-owned fields", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "report.pdf",
      ownerType: "document",
      ownerId: "doc-1",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    const keys = Array.from(form as unknown as Iterable<[string, File]>).map(([key]) => key);
    expect(keys).toEqual(["file", "owner_type", "owner_id"]);
    for (const forbidden of ["attachment_id", "storage_key", "status", "size_bytes", "created_at"]) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it("does not set a multipart Content-Type; the runtime generates the boundary", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "report.pdf",
    });

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers["Accept"]).toBe("application/json");
  });

  it("uses a File input's own name when fileName is omitted", async () => {
    const { client, fetchMock } = jsonClient(response);
    const file = new File(["data"], "auto-named.pdf", { type: "application/pdf" });

    await createAttachment(client, { file, ownerType: "document", ownerId: "doc-1" });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((form.get("file") as File).name).toBe("auto-named.pdf");
  });

  it("requires an explicit file name for a File-less Blob", async () => {
    const { client, fetchMock } = jsonClient(response);

    await expect(
      createAttachment(client, { file: new Blob(["data"], { type: "application/pdf" }) }),
    ).rejects.toBeInstanceOf(AttachmentInputError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an ownerType-only pair before any network request", async () => {
    const { client, fetchMock } = jsonClient(response);

    await expect(
      createAttachment(client, {
        file: new Blob(["data"], { type: "application/pdf" }),
        fileName: "a.pdf",
        ownerType: "document",
      }),
    ).rejects.toBeInstanceOf(AttachmentInputError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an ownerId-only pair before any network request", async () => {
    const { client, fetchMock } = jsonClient(response);

    await expect(
      createAttachment(client, {
        file: new Blob(["data"], { type: "application/pdf" }),
        fileName: "a.pdf",
        ownerId: "doc-1",
      }),
    ).rejects.toBeInstanceOf(AttachmentInputError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("conversation attachments", () => {
  it("uses scoped conversation routes for list, upload and delete", async () => {
    const collection = { contract_version: "v1", owner_type: "conversation", owner_id: "conv/a", attachments: [response] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(collection), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(response), { status: 201 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = makeClient(fetchMock);

    expect(await listConversationAttachments(client, "conv/a")).toEqual(collection);
    expect(await uploadConversationAttachment(client, "conv/a", new File(["data"], "notes.md"))).toEqual(response);
    await deleteConversationAttachment(client, "conv/a", "attachment-1");

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/conversations/conv%2Fa/attachments",
      "http://localhost:8000/conversations/conv%2Fa/attachments",
      "http://localhost:8000/conversations/conv%2Fa/attachments/attachment-1",
    ]);
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[2][1]?.method).toBe("DELETE");
  });
});

describe("createAttachment filenames", () => {
  it("transmits a normal filename as multipart display metadata", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "normal.pdf",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((form.get("file") as File).name).toBe("normal.pdf");
  });

  it("passes a path-like name through unmodified as display metadata", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/pdf" }),
      fileName: "../../dangerous.pdf",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((form.get("file") as File).name).toBe("../../dangerous.pdf");
    expect((form.get("file") as File).name).not.toBe("dangerous.pdf");
  });

  it("preserves a unicode filename through multipart metadata", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["data"], { type: "application/octet-stream" }),
      fileName: "unicode-\u2713.txt",
    });

    const form = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((form.get("file") as File).name).toBe("unicode-\u2713.txt");
  });
});

describe("createAttachment Blob/File compatibility", () => {
  it("uploads arbitrary opaque binary data as a Blob", async () => {
    const bytes = Uint8Array.from({ length: 512 }, (_, index) => (index * 7) % 256);
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob([bytes]),
      fileName: "blob.bin",
    });

    const file = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((file.get("file") as Blob).size).toBe(bytes.byteLength);
  });

  it("uploads a zero-byte Blob", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob([]),
      fileName: "empty.bin",
    });

    const file = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((file.get("file") as Blob).size).toBe(0);
  });

  it("carries the Blob MIME type through multipart metadata", async () => {
    const { client, fetchMock } = jsonClient(response);

    await createAttachment(client, {
      file: new Blob(["<pdf>"], { type: "application/pdf" }),
      fileName: "document.pdf",
    });

    const file = fetchMock.mock.calls[0][1]?.body as FormData;
    expect((file.get("file") as Blob).type).toBe("application/pdf");
  });
});

describe("getAttachment", () => {
  it("requests the encoded attachment path with no body and parses the response", async () => {
    const { client, fetchMock } = jsonClient(response);

    const result = await getAttachment(client, "attachment-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/attachments/attachment-1");
    expect(fetchMock.mock.calls[0][1]).not.toHaveProperty("method");
    expect(fetchMock.mock.calls[0][1]).not.toHaveProperty("body");
    expect(result).toEqual(response);
  });

  it("encodes the attachment id in the URL path", async () => {
    const { client, fetchMock } = jsonClient(response);

    await getAttachment(client, "att/one with spaces");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8000/attachments/att%2Fone%20with%20spaces",
    );
  });

  it("propagates ApiError on 404 without conversion", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "attachment_not_found", message: "nope" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const error = (await getAttachment(makeClient(fetchMock), "missing").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.body).toEqual({ error_code: "attachment_not_found", message: "nope" });
  });
});

describe("listAttachments", () => {
  it("requests the owner-scoped GET with safe query encoding", async () => {
    const list = { contract_version: "v1" as const, owner_type: "document" as const, owner_id: "doc-1", attachments: [response] };
    const { client, fetchMock } = jsonClient(list);

    const result = await listAttachments(client, "document", "doc-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/attachments?owner_type=document&owner_id=doc-1");
    expect(result).toEqual(list);
  });

  it("preserves backend attachment order without sorting", async () => {
    const second = { ...response, attachment_id: "attachment-2" };
    const list = {
      contract_version: "v1" as const,
      owner_type: "document" as const,
      owner_id: "doc-1",
      attachments: [response, second],
    };
    const { client, fetchMock } = jsonClient(list);

    const result = await listAttachments(client, "document", "doc-1");

    expect(result.attachments.map((a) => a.attachment_id)).toEqual(["attachment-1", "attachment-2"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("encodes hostile owner ids (spaces, slashes, ?, &, unicode)", async () => {
    const { client, fetchMock } = jsonClient({ contract_version: "v1", owner_type: "document", owner_id: "", attachments: [] });

    await listAttachments(client, "document", "doc /1?x&y=\u2713");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url.startsWith("http://localhost:8000/attachments?")).toBe(true);
    expect(decodeURIComponent(url).replace(/\+/g, " ")).toBe(
      "http://localhost:8000/attachments?owner_type=document&owner_id=doc /1?x&y=\u2713",
    );
    expect(url).toContain("owner_id=doc+%2F1%3Fx%26y%3D%E2%9C%93");
  });

  it("propagates ApiError on backend failure instead of an empty list", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "internal_error", message: "boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const error = (await listAttachments(makeClient(fetchMock), "document", "doc-1").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("getAttachmentContent", () => {
  const bytes = Uint8Array.from({ length: 256 }, (_, index) => index);

  it("returns the exact binary body for a successful download", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob([bytes]), { status: 200 }));
    const client = makeClient(fetchMock);

    const result = await getAttachmentContent(client, "attachment-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/attachments/attachment-1/content");
    expect(result).toBeInstanceOf(Blob);
    expect(Array.from(new Uint8Array(await result.arrayBuffer()))).toEqual(Array.from(bytes));
  });

  it("returns an empty Blob for a zero-byte payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob([]), { status: 200 }));
    const client = makeClient(fetchMock);

    const result = await getAttachmentContent(client, "attachment-1");

    expect(result.size).toBe(0);
    expect(Array.from(new Uint8Array(await result.arrayBuffer()))).toEqual([]);
  });

  it("never decodes non-JSON binary content", async () => {
    const nonUtf8 = new Uint8Array([0xff, 0xfe, 0x00, 0x80, 0x89]);
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob([nonUtf8]), { status: 200 }));
    const client = makeClient(fetchMock);

    const result = await getAttachmentContent(client, "attachment-1");

    expect(Array.from(new Uint8Array(await result.arrayBuffer()))).toEqual(Array.from(nonUtf8));
  });

  it.each([404, 409, 500])("maps a %s error body to ApiError, not binary", async (status) => {
    const errorBody = { error_code: "attachment_not_found", category: "not_found", message: "nope", recoverable: false };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorBody), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = makeClient(fetchMock);

    const error = (await getAttachmentContent(client, "attachment-1").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(status);
    expect(error.body).toEqual(errorBody);
  });
});
