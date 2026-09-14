// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { DocumentProvider } from "../state/DocumentProvider";
import { htmlContent } from "../model";
import { useDocuments } from "../state/DocumentProvider";
import { DocumentWorkspace } from "./DocumentWorkspace";

describe("DocumentWorkspace", () => {
  it("renders AVA document metadata, editor surface, and formatting controls", () => {
    render(<DocumentProvider><DocumentWorkspace /></DocumentProvider>);
    expect(screen.getAllByText("Untitled Document")).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Document content" })).toBeTruthy();
    for (const name of ["Bold", "Italic", "Heading 1", "Heading 2", "Bullet list", "Ordered list", "Undo", "Redo"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("reconstructs the editor from AVA state after unmounting", () => {
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
    render(<DocumentProvider><Fixture /></DocumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Unmount" }));
    fireEvent.click(screen.getByRole("button", { name: "Remount" }));
    expect(screen.getByRole("textbox", { name: "Document content" }).innerHTML).toContain("Preserved content");
  });

  it("allows a title to be cleared before a replacement is committed", () => {
    render(<DocumentProvider><DocumentWorkspace /></DocumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    const title = screen.getByRole("textbox", { name: "Document title" });
    fireEvent.change(title, { target: { value: "" } });
    expect((title as HTMLInputElement).value).toBe("");
    fireEvent.change(title, { target: { value: "New Name" } });
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    expect(screen.getByText("New Name")).toBeTruthy();
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
  });

  it("ends rename mode when navigating to another document or creating one", () => {
    render(<DocumentProvider><DocumentWorkspace /></DocumentProvider>);
    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.click(screen.getByRole("button", { name: "Untitled Document" }));
    expect(screen.queryByRole("textbox", { name: "Document title" })).toBeNull();
    expect(screen.getAllByText("Untitled Document")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    expect(screen.queryByRole("textbox", { name: "Document title" })).toBeNull();
    expect(screen.getAllByText("Untitled Document 3")).toHaveLength(2);
  });
});
