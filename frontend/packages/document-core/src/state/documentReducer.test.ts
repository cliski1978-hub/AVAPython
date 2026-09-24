import { describe, expect, it } from "vitest";
import { createAvaDocument, htmlContent } from "../model";
import { documentReducer, getActiveDocument, type DocumentState } from "./documentReducer";

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

describe("documentReducer operation state (Step 4.12.F)", () => {
  const loaded = createAvaDocument(htmlContent("<p>Loaded</p>"), "2026-01-01T00:00:00.000Z");
  const created = createAvaDocument(htmlContent("<p></p>"), "2026-01-02T00:00:00.000Z");
  const empty: DocumentState = {
    documents: [], activeDocumentId: null, loading: true, isCreating: false, isSaving: false, error: null,
  };

  describe("hydration lifecycle", () => {
    it("settles loading, populates backend documents, selects the first, and clears stale errors", () => {
      const base = { ...empty, error: new Error("stale prior error") };
      const next = documentReducer(base, { type: "hydrate", documents: [loaded] });
      expect(next.loading).toBe(false);
      expect(next.documents).toEqual([loaded]);
      expect(next.activeDocumentId).toBe(loaded.id);
      expect(next.error).toBeNull();
    });

    it("records a truthful hydration failure without inventing documents", () => {
      const next = documentReducer(empty, { type: "hydrateFailure", error: new Error("list unavailable") });
      expect(next.loading).toBe(false);
      expect(next.documents).toEqual([]);
      expect(next.activeDocumentId).toBeNull();
      expect(next.error?.message).toBe("list unavailable");
    });
  });

  describe("creation lifecycle", () => {
    it("marks creation in flight without touching existing state", () => {
      const base = { ...empty, loading: false };
      const next = documentReducer(base, { type: "createStart" });
      expect(next.isCreating).toBe(true);
      expect(next.loading).toBe(false);
      expect(next.documents).toEqual([]);
    });

    it("confirms the authoritative document, settles creation, selects it, and clears stale errors", () => {
      const base = { ...empty, loading: false, error: new Error("stale error") };
      const next = documentReducer(base, { type: "create", document: created });
      expect(next.isCreating).toBe(false);
      expect(next.documents).toEqual([created]);
      expect(next.activeDocumentId).toBe(created.id);
      expect(next.error).toBeNull();
    });

    it("settles a failed creation with the error and inserts nothing", () => {
      const base = { ...empty, loading: false, documents: [loaded], activeDocumentId: loaded.id };
      const next = documentReducer(base, { type: "createFailure", error: new Error("creation unavailable") });
      expect(next.isCreating).toBe(false);
      expect(next.error?.message).toBe("creation unavailable");
      expect(next.documents).toEqual([loaded]);
      expect(next.activeDocumentId).toBe(loaded.id);
    });
  });

  describe("save lifecycle", () => {
    const withLoaded: DocumentState = {
      documents: [loaded], activeDocumentId: loaded.id, loading: false, isCreating: false, isSaving: false, error: null,
    };

    it("marks the save in flight", () => {
      const next = documentReducer(withLoaded, { type: "saveStart" });
      expect(next.isSaving).toBe(true);
    });

    it("reconciles the authoritative clean response, settling the save and clearing errors", () => {
      const saved = { ...loaded, title: "Saved", updatedAt: "2026-01-03T00:00:00.000Z" };
      const base = { ...withLoaded, isSaving: true, error: new Error("stale error") };
      const next = documentReducer(base, { type: "reconcile", documentId: loaded.id, document: saved });
      expect(next.isSaving).toBe(false);
      expect(next.error).toBeNull();
      expect(next.documents.find((item) => item.id === loaded.id)).toEqual(saved);
    });

    it("settles a no-op completion without disturbing the document collection", () => {
      const base = { ...withLoaded, isSaving: true, error: new Error("stale error") };
      const next = documentReducer(base, { type: "saveComplete" });
      expect(next.isSaving).toBe(false);
      expect(next.error).toBeNull();
      expect(next.documents).toEqual(withLoaded.documents);
    });

    it("settles a failed save with the error, keeping local edits intact and dirty", () => {
      const dirty = { ...loaded, title: "Dirty", isDirty: true };
      const base = { documents: [dirty], activeDocumentId: dirty.id, loading: false, isCreating: false, isSaving: true, error: null };
      const next = documentReducer(base, { type: "saveFailure", error: new Error("save unavailable") });
      expect(next.isSaving).toBe(false);
      expect(next.error?.message).toBe("save unavailable");
      expect(next.documents).toEqual([dirty]);
      expect(next.documents[0].isDirty).toBe(true);
    });
  });

  describe("cross-operation error recovery", () => {
    it("clears a stale save error when a later create confirms successfully", () => {
      const base: DocumentState = {
        documents: [loaded], activeDocumentId: loaded.id, loading: false, isCreating: false, isSaving: false, error: null,
      };
      const failed = documentReducer(base, { type: "saveFailure", error: new Error("save unavailable") });
      expect(failed.error?.message).toBe("save unavailable");
      const started = documentReducer(failed, { type: "createStart" });
      expect(started.error?.message).toBe("save unavailable");
      const next = documentReducer(started, { type: "create", document: created });
      expect(next.error).toBeNull();
      expect(next.isCreating).toBe(false);
      expect(next.isSaving).toBe(false);
    });

    it("clears a stale create error when a later save reconciles successfully", () => {
      const base: DocumentState = {
        documents: [loaded], activeDocumentId: loaded.id, loading: false, isCreating: false, isSaving: false, error: null,
      };
      const failed = documentReducer(base, { type: "createFailure", error: new Error("creation unavailable") });
      expect(failed.error?.message).toBe("creation unavailable");
      const saved = { ...loaded, title: "Recovered", updatedAt: "2026-01-03T00:00:00.000Z" };
      const next = documentReducer(failed, { type: "reconcile", documentId: loaded.id, document: saved });
      expect(next.error).toBeNull();
      expect(next.isSaving).toBe(false);
    });
  });

  describe("operation-state isolation", () => {
    it("settling a save leaves hydration, creation, and selection state untouched", () => {
      const base: DocumentState = {
        documents: [loaded], activeDocumentId: loaded.id, loading: false, isCreating: false, isSaving: true, error: null,
      };
      const next = documentReducer(base, { type: "saveComplete" });
      expect(next.isSaving).toBe(false);
      expect(next.loading).toBe(false);
      expect(next.isCreating).toBe(false);
      expect(next.documents).toEqual([loaded]);
      expect(next.activeDocumentId).toBe(loaded.id);
    });

    it("hydration leaves an in-flight creation flag untouched", () => {
      const started = documentReducer(empty, { type: "createStart" });
      expect(started.isCreating).toBe(true);
      const next = documentReducer(started, { type: "hydrate", documents: [loaded] });
      expect(next.isCreating).toBe(true);
      expect(next.loading).toBe(false);
      expect(next.documents).toEqual([loaded]);
    });
  });
});

describe("documentReducer close — clears only the open editor view", () => {
  const makeDoc = (id: string, title: string, content: string) =>
    ({ ...createAvaDocument(htmlContent(content), "2026-01-01T00:00:00.000Z"), id, title });
  const docA = makeDoc("doc-a", "Document A", "<p>A</p>");
  const docB = makeDoc("doc-b", "Document B", "<p>B</p>");
  const base: DocumentState = {
    documents: [docA, docB], activeDocumentId: "doc-a",
    loading: false, isCreating: false, isSaving: false, error: null,
  };

  it("clears only the active selection and keeps both documents in the list", () => {
    const next = documentReducer(base, { type: "close", documentId: "doc-a" });
    expect(next.activeDocumentId).toBeNull();
    expect(next.documents).toEqual([docA, docB]);
    expect(getActiveDocument(next)).toBeNull();
  });

  it("does not delete the closed document record or its dirty state", () => {
    const dirty = { ...base, documents: [{ ...docA, isDirty: true }, docB] };
    const next = documentReducer(dirty, { type: "close", documentId: "doc-a" });
    expect(next.documents[0]).toEqual({ ...docA, isDirty: true });
  });

  it("leaves the other document untouched when the active one is closed", () => {
    const next = documentReducer(base, { type: "close", documentId: "doc-a" });
    expect(next.documents.find((item) => item.id === "doc-b")).toEqual(docB);
  });

  it("is a no-op when closing a document that is not active", () => {
    expect(documentReducer(base, { type: "close", documentId: "doc-b" })).toBe(base);
  });

  it("is a no-op for an unknown document id", () => {
    expect(documentReducer(base, { type: "close", documentId: "missing" })).toBe(base);
  });

  it("allows the closed document to be reopened immediately without rehydration", () => {
    const closed = documentReducer(base, { type: "close", documentId: "doc-a" });
    expect(closed.activeDocumentId).toBeNull();
    const reopened = documentReducer(closed, { type: "setActiveDocument", documentId: "doc-a" });
    expect(reopened.activeDocumentId).toBe("doc-a");
    expect(reopened.documents[0].id).toBe("doc-a");
    expect(reopened.documents[0].content.value).toBe("<p>A</p>");
  });

  it("preserves other selections after a fresh hydrate following close", () => {
    const closed = documentReducer(base, { type: "close", documentId: "doc-a" });
    const refreshed = documentReducer(closed, { type: "hydrate", documents: [docA, docB] });
    expect(refreshed.documents).toEqual([docA, docB]);
    expect(refreshed.activeDocumentId).toBe("doc-a");
  });
});
