import { describe, expect, it } from "vitest";
import { createAvaDocument, htmlContent } from "../model";
import { documentReducer, getActiveDocument } from "./documentReducer";

describe("document operations", () => {
  const a = createAvaDocument(htmlContent("<p>A</p>"), "2026-01-01T00:00:00.000Z");
  const b = createAvaDocument(htmlContent("<p>B</p>"), "2026-01-01T00:00:00.000Z");

  it("creates, selects, and isolates multiple documents", () => {
    const initial = { documents: [a], activeDocumentId: a.id };
    const created = documentReducer(initial, { type: "create", document: b });
    const editedA = documentReducer(created, { type: "updateContent", documentId: a.id, content: htmlContent("<p>AAA</p>"), updatedAt: "2026-01-02T00:00:00.000Z" });
    expect(getActiveDocument(editedA)?.id).toBe(b.id);
    expect(editedA.documents.find((item) => item.id === a.id)?.content.value).toBe("<p>AAA</p>");
    expect(editedA.documents.find((item) => item.id === b.id)?.content.value).toBe("<p>B</p>");
  });

  it("renames without changing identity and saves only the target document", () => {
    const state = { documents: [a, b], activeDocumentId: a.id };
    const renamed = documentReducer(state, { type: "rename", documentId: a.id, title: "Design Notes", updatedAt: "2026-01-02T00:00:00.000Z" });
    const saved = documentReducer(renamed, { type: "markClean", documentId: a.id, updatedAt: "2026-01-03T00:00:00.000Z" });
    expect(saved.documents[0]).toMatchObject({ id: a.id, title: "Design Notes", isDirty: false });
    expect(saved.documents[1]).toBe(b);
  });

  it("reassigns active state and supports zero documents when closing", () => {
    const state = { documents: [a, b], activeDocumentId: a.id };
    const next = documentReducer(state, { type: "close", documentId: a.id });
    expect(next.activeDocumentId).toBe(b.id);
    expect(documentReducer(next, { type: "close", documentId: b.id })).toEqual({ documents: [], activeDocumentId: null });
  });
});
