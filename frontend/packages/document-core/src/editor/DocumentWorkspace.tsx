import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Button, Divider, Input, defaultTheme } from "@ava/ui-core";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { useDocuments } from "../state/DocumentProvider";
import { createTiptapEditorAdapter } from "./TiptapEditorAdapter";
import "./document-editor.css";

/**
 * Shared AVA rich-text editor workspace built on Tiptap.
 *
 * All Tiptap-specific API usage lives in this file. Application shells and the
 * broader AVA package set never touch Tiptap commands or types; they render
 * this component. Tiptap is an editor implementation, not part of AVA's
 * document architecture.
 */

interface ToolbarState {
  bold: boolean;
  italic: boolean;
  heading1: boolean;
  heading2: boolean;
  bulletList: boolean;
  orderedList: boolean;
  canUndo: boolean;
  canRedo: boolean;
}

const EMPTY_TOOLBAR: ToolbarState = {
  bold: false,
  italic: false,
  heading1: false,
  heading2: false,
  bulletList: false,
  orderedList: false,
  canUndo: false,
  canRedo: false,
};

const t = defaultTheme;

const surfaceVars = {
  "--ava-bg": t.colors.background,
  "--ava-surface": t.colors.surface,
  "--ava-border": t.colors.border,
  "--ava-foreground": t.colors.foreground,
  "--ava-muted": t.colors.mutedText,
  "--ava-focus": t.colors.focusRing,
  "--ava-primary": t.colors.primary,
  "--ava-font": t.font.family,
} as unknown as CSSProperties;

const surfaceStyle: CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
  minWidth: 0,
  background: t.colors.background,
  color: t.colors.foreground,
  ...surfaceVars,
};

export function DocumentWorkspace() {
  const { state, activeDocument, reloadDocuments, updateDocumentContent, createDocument, selectDocument, renameDocument, saveDocument, closeDocument } = useDocuments();
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const activeDocumentRef = useRef(activeDocument);
  activeDocumentRef.current = activeDocument;
  const editor = useEditor({
    extensions: [StarterKit.configure({ heading: { levels: [1, 2, 3] } })],
    content: activeDocument?.content.value ?? "",
    autofocus: false,
    editorProps: {
      attributes: {
        class: "ava-doc-editor",
        role: "textbox",
        "aria-label": "Document content",
        spellcheck: "true",
      },
    },
  });

  const adapter = useMemo(
    () => editor == null ? null : createTiptapEditorAdapter(editor),
    [editor],
  );

  useEffect(() => {
    if (editor == null || adapter == null) return;
    const onUpdate = () => {
      const document = activeDocumentRef.current;
      if (document != null) updateDocumentContent(document.id, adapter.getContent());
    };
    editor.on("update", onUpdate);
    return () => {
      editor.off("update", onUpdate);
    };
  }, [adapter, editor, updateDocumentContent]);

  useEffect(() => {
    if (adapter == null || activeDocument == null) return;
    if (adapter.getContent().value !== activeDocument.content.value) {
      adapter.setContent(activeDocument.content);
    }
  }, [activeDocument, adapter]);

  const [toolbar, setToolbar] = useState<ToolbarState>(EMPTY_TOOLBAR);

  useEffect(() => {
    if (editor == null) return;
    const update = () =>
      setToolbar({
        bold: editor.isActive("bold"),
        italic: editor.isActive("italic"),
        heading1: editor.isActive("heading", { level: 1 }),
        heading2: editor.isActive("heading", { level: 2 }),
        bulletList: editor.isActive("bulletList"),
        orderedList: editor.isActive("orderedList"),
        canUndo: editor.can().undo(),
        canRedo: editor.can().redo(),
      });
    update();
    editor.on("transaction", update);
    return () => {
      editor.off("transaction", update);
    };
  }, [editor]);

  if (editor == null) {
    return (
      <div style={surfaceStyle}>
        <div className="ava-doc-scroll">
          <div className="ava-doc-page" />
        </div>
      </div>
    );
  }

  const run = (fn: () => void) => {
    fn();
  };

  const closeActiveDocument = () => {
    if (activeDocument == null) return;
    if (!activeDocument.isDirty || window.confirm("This document has unsaved changes. Close it anyway?")) {
      closeDocument(activeDocument.id);
    }
  };

  const beginRename = () => {
    setRenameDraft(activeDocument?.title ?? "");
    setRenaming(true);
  };

  const commitRename = () => {
    if (activeDocument != null && renameDraft.trim()) {
      void renameDocument(activeDocument.id, renameDraft);
    }
    setRenaming(false);
  };

  const abandonRename = () => {
    setRenaming(false);
    setRenameDraft("");
  };

  const createFromNavigation = () => {
    abandonRename();
    createDocument();
  };

  const selectFromNavigation = (documentId: string) => {
    abandonRename();
    selectDocument(documentId);
  };

  return (
    <div style={{ ...surfaceStyle, flexDirection: "row" }}>
      <nav className="ava-doc-nav" aria-label="Documents">
        <div className="ava-doc-nav-header"><strong>Documents</strong><Button variant="primary" ariaLabel="New Document" disabled={state.isCreating || state.loading === true || state.loadError != null} onClick={createFromNavigation}>New</Button></div>
        {state.documents.map((document) => (
          <button
            className="ava-doc-nav-item"
            key={document.id}
            aria-current={document.id === activeDocument?.id ? "page" : undefined}
            onClick={() => selectFromNavigation(document.id)}
          >
            {document.title}{document.isDirty ? " •" : ""}
          </button>
        ))}
      </nav>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
      {activeDocument == null && state.loading === true ? (
        <div className="ava-doc-empty" role="status" data-documents-loading="">
          <strong>Loading documents…</strong>
        </div>
      ) : activeDocument == null && state.loadError != null ? (
        <div className="ava-doc-empty" role="alert" aria-label="Documents could not be loaded." data-documents-load-error="">
          <strong>Documents could not be loaded.</strong>
          <span>Check the backend connection and retry.</span>
          <Button variant="primary" onClick={() => void reloadDocuments()}>Retry loading documents</Button>
        </div>
      ) : activeDocument == null ? (
        <div className="ava-doc-empty"><strong>No document open</strong><span>Create a document to start writing.</span><Button variant="primary" ariaLabel="New Document" disabled={state.isCreating} onClick={createDocument}>New Document</Button></div>
      ) : <>
      <div className="ava-doc-header" aria-label="Document details">
        {renaming ? (
          <form className="ava-doc-title-form" onSubmit={(event) => { event.preventDefault(); commitRename(); }}>
            <Input ariaLabel="Document title" value={renameDraft} onChange={setRenameDraft} />
            <Button type="submit" ariaLabel="Finish renaming">Done</Button>
          </form>
        ) : <strong>{activeDocument.title}</strong>}
        {activeDocument.isDirty && <span>Unsaved changes</span>}
        <div className="ava-doc-actions">
          <Button ariaLabel="Rename document" disabled={renaming} onClick={beginRename}>Rename</Button>
          <Button variant="primary" ariaLabel="Save document" disabled={!activeDocument.isDirty} onClick={() => saveDocument(activeDocument.id)}>Save</Button>
          <Button variant="danger" ariaLabel="Close document" onClick={closeActiveDocument}>Close</Button>
        </div>
      </div>
      <div
        className="ava-doc-toolbar"
        role="toolbar"
        aria-label="Document formatting"
        style={{ fontFamily: t.font.family }}
      >
        <Button
          variant={toolbar.bold ? "secondary" : "ghost"}
          ariaPressed={toolbar.bold}
          ariaLabel="Bold"
          title="Bold"
          onClick={() => run(() => editor.chain().focus().toggleBold().run())}
        >
          B
        </Button>
        <Button
          variant={toolbar.italic ? "secondary" : "ghost"}
          ariaPressed={toolbar.italic}
          ariaLabel="Italic"
          title="Italic"
          onClick={() =>
            run(() => editor.chain().focus().toggleItalic().run())
          }
        >
          I
        </Button>
        <Divider orientation="vertical" spacing={4} />
        <Button
          variant={toolbar.heading1 ? "secondary" : "ghost"}
          ariaPressed={toolbar.heading1}
          ariaLabel="Heading 1"
          title="Heading 1"
          onClick={() =>
            run(() => editor.chain().focus().toggleHeading({ level: 1 }).run())
          }
        >
          H1
        </Button>
        <Button
          variant={toolbar.heading2 ? "secondary" : "ghost"}
          ariaPressed={toolbar.heading2}
          ariaLabel="Heading 2"
          title="Heading 2"
          onClick={() =>
            run(() => editor.chain().focus().toggleHeading({ level: 2 }).run())
          }
        >
          H2
        </Button>
        <Divider orientation="vertical" spacing={4} />
        <Button
          variant={toolbar.bulletList ? "secondary" : "ghost"}
          ariaPressed={toolbar.bulletList}
          ariaLabel="Bullet list"
          title="Bullet list"
          onClick={() =>
            run(() => editor.chain().focus().toggleBulletList().run())
          }
        >
          {"\u2022"}
        </Button>
        <Button
          variant={toolbar.orderedList ? "secondary" : "ghost"}
          ariaPressed={toolbar.orderedList}
          ariaLabel="Ordered list"
          title="Ordered list"
          onClick={() =>
            run(() => editor.chain().focus().toggleOrderedList().run())
          }
        >
          1.
        </Button>
        <Divider orientation="vertical" spacing={4} />
        <Button
          variant="default"
          ariaLabel="Undo"
          title="Undo"
          disabled={!toolbar.canUndo}
          onClick={() => run(() => editor.chain().focus().undo().run())}
        >
          Undo
        </Button>
        <Button
          variant="default"
          ariaLabel="Redo"
          title="Redo"
          disabled={!toolbar.canRedo}
          onClick={() => run(() => editor.chain().focus().redo().run())}
        >
          Redo
        </Button>
      </div>
      <div className="ava-doc-scroll">
        <div className="ava-doc-page">
          <EditorContent editor={editor} />
        </div>
      </div>
      </>}
      </div>
    </div>
  );
}
