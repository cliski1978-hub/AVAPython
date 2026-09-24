import { describe, expect, it } from "vitest";

import { mapDocumentResponse, mapDocumentRevisionResponse } from "./documentMapper";

describe("mapDocumentResponse", () => {
  it("maps the backend-authoritative snapshot into a clean editor-neutral document", () => {
    const document = mapDocumentResponse({
      document_id: "document-backend-1",
      title: "Backend design notes",
      content: "<p>Canonical HTML</p>",
      content_format: "html",
      created_at: "2026-09-19T00:00:00Z",
      updated_at: "2026-09-19T01:00:00Z",
      contract_version: "v1",
    });

    expect(document).toEqual({
      id: "document-backend-1",
      title: "Backend design notes",
      content: { format: "html", value: "<p>Canonical HTML</p>" },
      createdAt: "2026-09-19T00:00:00Z",
      updatedAt: "2026-09-19T01:00:00Z",
      isDirty: false,
    });
  });
});

describe("mapDocumentRevisionResponse", () => {
  it("maps wire revision fields to frontend-domain naming without leaking transport metadata", () => {
    const revision = mapDocumentRevisionResponse({
      revision_id: "revision-2",
      document_id: "document-backend-1",
      revision_number: 2,
      title: "Backend design notes",
      content: "<p>Canonical HTML</p>",
      content_format: "html",
      created_at: "2026-09-19T02:00:00Z",
      contract_version: "v1",
    });

    expect(revision).toEqual({
      revisionId: "revision-2",
      documentId: "document-backend-1",
      revisionNumber: 2,
      title: "Backend design notes",
      content: { format: "html", value: "<p>Canonical HTML</p>" },
      createdAt: "2026-09-19T02:00:00Z",
    });
  });

  it("preserves the revision number exactly and keeps HTML byte-identical", () => {
    const revision = mapDocumentRevisionResponse({
      revision_id: "revision-1",
      document_id: "document-backend-1",
      revision_number: 1,
      title: "Original",
      content: "<p>  Kept &amp; intact  </p>",
      content_format: "html",
      created_at: "2026-09-19T00:00:00Z",
      contract_version: "v1",
    });

    expect(revision.revisionNumber).toBe(1);
    expect(revision.content).toEqual({ format: "html", value: "<p>  Kept &amp; intact  </p>" });
  });

  it("shapes the exact allowed domain fields with no snake_case or transport metadata", () => {
    const revision = mapDocumentRevisionResponse({
      revision_id: "revision-9",
      document_id: "document-backend-9",
      revision_number: 9,
      title: "T",
      content: "<p>T</p>",
      content_format: "html",
      created_at: "2026-09-19T09:00:00Z",
      contract_version: "v1",
    });

    expect(Object.keys(revision).sort()).toEqual([
      "content",
      "createdAt",
      "documentId",
      "revisionId",
      "revisionNumber",
      "title",
    ]);
    expect("contract_version" in revision).toBeFalsy();
    expect("content_format" in revision).toBeFalsy();
    expect("revision_id" in revision).toBeFalsy();
  });
});
