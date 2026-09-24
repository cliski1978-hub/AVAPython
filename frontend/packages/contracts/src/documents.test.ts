import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type {
  CreateDocumentRequest,
  DocumentListResponse,
  DocumentResponse,
  DocumentRevisionListResponse,
  DocumentRevisionResponse,
  UpdateDocumentRequest,
} from "./index";

describe("document contracts", () => {
  it("exports backend-shaped document snapshots", () => {
    const document: DocumentResponse = {
      document_id: "document-1",
      title: "Design notes",
      content: "<p>Durable content</p>",
      content_format: "html",
      created_at: "2026-09-19T00:00:00Z",
      updated_at: "2026-09-19T01:00:00Z",
      contract_version: CONTRACT_VERSION,
    };
    const list: DocumentListResponse = {
      documents: [document],
      contract_version: CONTRACT_VERSION,
    };

    expect(list.documents[0]).toEqual(document);
  });

  it("keeps durable identity and timestamps out of document write requests", () => {
    const create: CreateDocumentRequest = {
      title: "Design notes",
      content: "<p>Durable content</p>",
      content_format: "html",
    };
    const update: UpdateDocumentRequest = { content: "<p>Updated</p>" };

    expect(Object.keys(create).sort()).toEqual(["content", "content_format", "title"]);
    expect(update).toEqual({ content: "<p>Updated</p>" });
  });
});

describe("document revision contracts", () => {
  const revision: DocumentRevisionResponse = {
    revision_id: "revision-2",
    document_id: "document-1",
    revision_number: 2,
    title: "Design notes",
    content: "<p>Reverted content</p>",
    content_format: "html",
    created_at: "2026-09-19T02:00:00Z",
    contract_version: CONTRACT_VERSION,
  };

  it("shapes a DocumentRevisionResponse exactly like the backend wire contract", () => {
    expect(revision).toEqual({
      revision_id: "revision-2",
      document_id: "document-1",
      revision_number: 2,
      title: "Design notes",
      content: "<p>Reverted content</p>",
      content_format: "html",
      created_at: "2026-09-19T02:00:00Z",
      contract_version: CONTRACT_VERSION,
    });
  });

  it("shapes a DocumentRevisionListResponse with ordered revisions and document id", () => {
    const list: DocumentRevisionListResponse = {
      document_id: "document-1",
      revisions: [revision],
      contract_version: CONTRACT_VERSION,
    };

    expect(list.document_id).toBe("document-1");
    expect(list.revisions).toEqual([revision]);
    expect(list.contract_version).toBe(CONTRACT_VERSION);
  });

  it("keeps revision_number numeric and independent of contract_version", () => {
    expect(typeof revision.revision_number).toBe("number");
    expect(revision.revision_number).toBe(2);
    expect(revision.contract_version).toBe(CONTRACT_VERSION);
    expect(revision.contract_version).not.toBe(String(revision.revision_number));
  });

  it("uses backend field names without forbidden revision metadata", () => {
    const fields = Object.keys(revision).sort();
    expect(fields).toEqual([
      "content",
      "content_format",
      "contract_version",
      "created_at",
      "document_id",
      "revision_id",
      "revision_number",
      "title",
    ]);
    expect("author" in revision).toBeFalsy();
    expect("source" in revision).toBeFalsy();
    expect("parent_revision" in revision).toBeFalsy();
    expect("document_updated_at" in revision).toBeFalsy();
  });
});
