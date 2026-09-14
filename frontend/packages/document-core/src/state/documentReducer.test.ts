import { describe, expect, it } from "vitest";
import { createAvaDocument, htmlContent } from "../model";
import { documentReducer, getActiveDocument } from "./documentReducer";

describe("documentReducer", () => {
  const document = createAvaDocument(htmlContent("<p>Initial</p>"), "2026-01-01T00:00:00.000Z");
  const state = { documents: [document], activeDocumentId: document.id };
  it("updates content immutably and marks the AVA document dirty", () => {
    const next = documentReducer(state, { type: "updateContent", documentId: document.id, content: htmlContent("<p>Changed</p>"), updatedAt: "2026-01-02T00:00:00.000Z" });
    expect(getActiveDocument(next)?.content.value).toBe("<p>Changed</p>");
    expect(getActiveDocument(next)?.isDirty).toBe(true);
    expect(next.documents).not.toBe(state.documents);
    expect(state.documents[0].content.value).toBe("<p>Initial</p>");
  });
  it("safely ignores unknown document IDs", () => {
    expect(documentReducer(state, { type: "setActiveDocument", documentId: "missing" })).toBe(state);
  });
});
