// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ConversationList, type Conversation, type ConversationFolder } from "@ava/agent-ui";

const folder = (id: string, name: string): ConversationFolder => ({
  id, name, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
});
const conversation = (id: string, title: string, folderId: string | null, projectId: string | null = null): Conversation => ({
  id, title, folderId, projectId, messages: [{ id: `${id}-message`, role: "assistant", content: "saved transcript" }],
  run: { runId: `${id}-run`, backendStatus: "running", uiPhase: "running", runError: null, pendingMessageId: null, runEpoch: "epoch" },
});
const noop = () => undefined;
function setRect(element: Element, left: number, top: number, width: number, height: number) {
  element.getBoundingClientRect = () => ({
    x: left, y: top, left, top, right: left + width, bottom: top + height,
    width, height, toJSON: () => ({}),
  }) as DOMRect;
}
function setFolderDragRects(container: HTMLElement, conversationId: string, folderId: string) {
  setRect(container.querySelector(`[data-conversation-row="${conversationId}"]`)!, 0, 0, 120, 32);
  setRect(container.querySelector(`[data-folder-drop-target="${folderId}"]`)!, 180, 80, 220, 80);
  setRect(container.querySelector('[data-folder-drop-target="ungrouped"]')!, 180, 180, 220, 80);
}
beforeAll(() => {
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    isPrimary: boolean;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.isPrimary = init.isPrimary ?? true;
    }
  }
  Object.defineProperty(window, "PointerEvent", { configurable: true, value: TestPointerEvent });
});
afterEach(async () => {
  // dnd-kit intentionally removes pointer-sensor click guards on a short timer
  // after cancellation so the post-drag click cannot activate the source.
  await new Promise((resolve) => setTimeout(resolve, 55));
});
describe("conversation folder sidebar", () => {
  it("renders backend-ordered folders, their conversations, and Ungrouped", () => {
    const { container } = render(
      <ConversationList
        conversations={[conversation("c1", "Inside", "f1"), conversation("c2", "Loose", null)]}
        folders={[folder("f1", "Zulu"), folder("f2", "Alpha")]}
        activeConversationId="c1" onNewChat={noop} onSelect={noop}
      />,
    );
    expect(container.querySelector('[data-conversation-folder="f1"]')).not.toBeNull();
    expect(container.querySelector('[data-conversation-folder="f2"]')).not.toBeNull();
    expect(screen.getByText("Inside")).toBeTruthy();
    expect(screen.getByText("Loose")).toBeTruthy();
    expect(container.querySelector('[data-ungrouped-conversations]')).not.toBeNull();
    expect(container.querySelector('[data-conversation-folder="f1"]')!.compareDocumentPosition(
      container.querySelector('[data-conversation-folder="f2"]')!,
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("creates and renames folders, keeping the editor open with safe errors on failure", async () => {
    const create = vi.fn().mockRejectedValueOnce(new Error("private server detail")).mockResolvedValueOnce(undefined);
    const rename = vi.fn().mockRejectedValueOnce(new Error("private server detail"));
    render(<ConversationList conversations={[conversation("c1", "Keep conversation", "f1")]} folders={[folder("f1", "Engineering")]} activeConversationId="c1"
      onNewChat={noop} onSelect={noop} onCreateFolder={create} onRenameFolder={rename} />);
    fireEvent.click(screen.getByRole("button", { name: "New Folder" }));
    const createDialog = screen.getByRole("dialog");
    fireEvent.change(within(createDialog).getByLabelText("Folder name"), { target: { value: "  " } });
    expect(within(createDialog).getByRole("button", { name: "Create folder" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(within(createDialog).getByLabelText("Folder name"), { target: { value: " New Folder " } });
    fireEvent.click(within(createDialog).getByRole("button", { name: "Create folder" }));
    expect((await within(createDialog).findByRole("alert")).textContent).toContain("Unable to create folder");
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Keep conversation")).toBeTruthy();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Create folder" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Keep conversation" }).getAttribute("aria-current")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Folder actions for Engineering" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const renameDialog = screen.getByRole("dialog");
    fireEvent.change(within(renameDialog).getByLabelText("Folder name"), { target: { value: "Renamed" } });
    fireEvent.click(within(renameDialog).getByRole("button", { name: "Save folder" }));
    expect((await within(renameDialog).findByRole("alert")).textContent).toContain("Unable to rename folder");
    expect((within(renameDialog).getByLabelText("Folder name") as HTMLInputElement).value).toBe("Renamed");
    expect(screen.getByText("Keep conversation")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Keep conversation" }).getAttribute("aria-current")).toBe("true");
  });

  it("confirms folder deletion and keeps conversations available under Ungrouped", async () => {
    function Sidebar() {
      const [folders, setFolders] = useState([folder("f1", "Engineering")]);
      const [conversations, setConversations] = useState([
        conversation("c1", "One", "f1"), conversation("c2", "Two", "f1"),
      ]);
      return <ConversationList conversations={conversations} folders={folders} activeConversationId="c1"
        onNewChat={noop} onSelect={noop} onCreateFolder={async () => undefined} onDeleteFolder={async () => {
          setFolders([]);
          setConversations((current) => current.map((item) => ({ ...item, folderId: null })));
        }} />;
    }
    render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Folder actions for Engineering" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/conversations will not be deleted/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete folder" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("One")).toBeTruthy();
    expect(screen.getByText("Two")).toBeTruthy();
    expect(screen.getByRole("button", { name: "One" }).getAttribute("aria-current")).toBe("true");
    expect(screen.queryByText("saved transcript")).toBeNull(); // sidebar does not own or reload transcripts
    expect(Array.from(document.querySelector('[data-ungrouped-conversations]')?.querySelectorAll("[data-conversation-row]") ?? [])).toHaveLength(2);
  });

  it("keeps folder and assignments visible after a generic delete failure", async () => {
    render(<ConversationList conversations={[conversation("c1", "One", "f1")]} folders={[folder("f1", "Engineering")]}
      activeConversationId="c1" onNewChat={noop} onSelect={noop}
      onDeleteFolder={async () => { throw new Error("raw backend details"); }} />);
    fireEvent.click(screen.getByRole("button", { name: "Folder actions for Engineering" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete folder" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Unable to delete folder");
    expect((await screen.findByText("Engineering")).textContent).toContain("Engineering");
    expect(screen.getByText("One")).toBeTruthy();
    expect(screen.queryByText("raw backend details")).toBeNull();
  });

  it("moves and unassigns conversations from their action menu without changing selection", async () => {
    const onMove = vi.fn().mockRejectedValueOnce(new Error("server detail")).mockResolvedValue(undefined);
    const selected = vi.fn();
    const { rerender } = render(<ConversationList conversations={[conversation("c1", "Selected", "f1")]}
      folders={[folder("f1", "Engineering"), folder("f2", "Personal")]} activeConversationId="c1"
      onNewChat={noop} onSelect={selected} onMoveConversation={onMove} />);
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to folder" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to Personal" }));
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("c1", "f2"));
    expect(screen.getByText("Selected")).toBeTruthy();
    expect(selected).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("Unable to move this conversation");

    rerender(<ConversationList conversations={[conversation("c1", "Selected", "f2")]}
      folders={[folder("f1", "Engineering"), folder("f2", "Personal")]} activeConversationId="c1"
      onNewChat={noop} onSelect={selected} onMoveConversation={onMove} />);
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to folder" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move to Ungrouped" }));
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("c1", null));
    expect(selected).not.toHaveBeenCalled();
  });

  it("registers conversation IDs and Folder/Ungrouped targets with dnd-kit", () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const selected = vi.fn();
    const { container } = render(<ConversationList
      conversations={[conversation("project-chat", "Project conversation", null, "project-a")]}
      folders={[folder("folder-x", "Same name"), folder("folder-y", "Same name")]}
      activeConversationId="project-chat" onNewChat={noop} onSelect={selected} onMoveConversation={onMove}
    />);
    const row = container.querySelector('[data-conversation-row="project-chat"]')!;
    expect(row.querySelector('[data-draggable-conversation="project-chat"]')).not.toBeNull();
    expect(row.querySelector('[aria-roledescription="draggable"]')).not.toBeNull();
    expect(container.querySelector('[data-folder-drop-target="folder-x"]')).not.toBeNull();
    expect(container.querySelector('[data-folder-drop-target="folder-y"]')).not.toBeNull();
    expect(container.querySelector('[data-folder-drop-target="ungrouped"]')).not.toBeNull();
    expect(onMove).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Project conversation" }).getAttribute("aria-current")).toBe("true");
    expect(selected).not.toHaveBeenCalled();
  });

  it("moves a conversation to a Folder through the dnd-kit pointer sensor", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<ConversationList
      conversations={[conversation("pointer-chat", "Pointer chat", null)]}
      folders={[folder("pointer-folder-a", "Work"), folder("pointer-folder-b", "Work")]}
      activeConversationId="pointer-chat" onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    setFolderDragRects(container, "pointer-chat", "pointer-folder-b");
    const source = screen.getByRole("button", { name: "Pointer chat" });
    fireEvent.pointerDown(source, { pointerId: 1, isPrimary: true, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(document, { pointerId: 1, isPrimary: true, clientX: 210, clientY: 110 });
    fireEvent.pointerMove(document, { pointerId: 1, isPrimary: true, clientX: 210, clientY: 110 });
    expect(container.querySelector('[data-conversation-row="pointer-chat"]')?.getAttribute("data-dragging-conversation")).toBe("");
    expect(container.querySelector('[data-folder-drop-target="pointer-folder-b"]')?.getAttribute("data-drop-target-active")).toBe("");
    fireEvent.pointerUp(document, { pointerId: 1, isPrimary: true, clientX: 210, clientY: 110 });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("pointer-chat", "pointer-folder-b"));
  });

  it("moves a conversation to a Folder through the dnd-kit keyboard sensor", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<ConversationList
      conversations={[conversation("keyboard-chat", "Keyboard chat", null)]}
      folders={[folder("keyboard-folder", "Work")]}
      activeConversationId="keyboard-chat" onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    setFolderDragRects(container, "keyboard-chat", "keyboard-folder");
    const source = screen.getByRole("button", { name: "Keyboard chat" });
    source.focus();
    fireEvent.keyDown(source, { key: " ", code: "Space" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    fireEvent.keyDown(source, { key: "ArrowDown", code: "ArrowDown" });
    expect(container.querySelector('[data-folder-drop-target="keyboard-folder"]')?.getAttribute("data-drop-target-active")).toBe("");
    fireEvent.keyDown(source, { key: " ", code: "Space" });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("keyboard-chat", "keyboard-folder"));
  });

  it("moves a conversation to Ungrouped through the dnd-kit pointer sensor", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<ConversationList
      conversations={[conversation("ungroup-chat", "Filed chat", "ungroup-folder")]}
      folders={[folder("ungroup-folder", "Work")]}
      activeConversationId="ungroup-chat" onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    setFolderDragRects(container, "ungroup-chat", "ungroup-folder");
    const source = screen.getByRole("button", { name: "Filed chat" });
    fireEvent.pointerDown(source, { pointerId: 2, isPrimary: true, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(document, { pointerId: 2, isPrimary: true, clientX: 210, clientY: 210 });
    fireEvent.pointerMove(document, { pointerId: 2, isPrimary: true, clientX: 210, clientY: 210 });
    expect(container.querySelector('[data-folder-drop-target="ungrouped"]')?.getAttribute("data-drop-target-active")).toBe("");
    fireEvent.pointerUp(document, { pointerId: 2, isPrimary: true, clientX: 210, clientY: 210 });
    await waitFor(() => expect(onMove).toHaveBeenCalledWith("ungroup-chat", null));
  });

  it("does not mutate on same-Folder drops, pointer cancellation, or drops outside targets", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container, rerender } = render(<ConversationList
      conversations={[conversation("safe-chat", "Safe chat", "safe-folder")]}
      folders={[folder("safe-folder", "Work")]}
      activeConversationId="safe-chat" onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    setFolderDragRects(container, "safe-chat", "safe-folder");
    const source = screen.getByRole("button", { name: "Safe chat" });
    fireEvent.pointerDown(source, { pointerId: 3, isPrimary: true, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(document, { pointerId: 3, isPrimary: true, clientX: 210, clientY: 110 });
    fireEvent.pointerMove(document, { pointerId: 3, isPrimary: true, clientX: 210, clientY: 110 });
    fireEvent.pointerUp(document, { pointerId: 3, isPrimary: true, clientX: 210, clientY: 110 });
    expect(onMove).not.toHaveBeenCalled();

    rerender(<ConversationList conversations={[conversation("safe-chat", "Safe chat", null)]}
      folders={[folder("safe-folder", "Work")]} activeConversationId="safe-chat"
      onNewChat={noop} onSelect={noop} onMoveConversation={onMove} />);
    setFolderDragRects(container, "safe-chat", "safe-folder");
    const ungroupedSource = screen.getByRole("button", { name: "Safe chat" });
    fireEvent.pointerDown(ungroupedSource, { pointerId: 4, isPrimary: true, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(document, { pointerId: 4, isPrimary: true, clientX: 210, clientY: 110 });
    fireEvent.pointerMove(document, { pointerId: 4, isPrimary: true, clientX: 210, clientY: 110 });
    fireEvent.pointerCancel(document, { pointerId: 4, isPrimary: true, clientX: 210, clientY: 110 });
    expect(onMove).not.toHaveBeenCalled();
    expect(container.querySelector('[data-conversation-row="safe-chat"]')?.hasAttribute("data-dragging-conversation")).toBe(false);

    fireEvent.pointerDown(ungroupedSource, { pointerId: 5, isPrimary: true, button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(document, { pointerId: 5, isPrimary: true, clientX: 10, clientY: 910 });
    fireEvent.pointerMove(document, { pointerId: 5, isPrimary: true, clientX: 10, clientY: 910 });
    fireEvent.pointerUp(document, { pointerId: 5, isPrimary: true, clientX: 10, clientY: 910 });
    expect(onMove).not.toHaveBeenCalled();
  });

  it("cancels keyboard dragging with Escape without changing Folder membership", async () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<ConversationList
      conversations={[conversation("escape-chat", "Escape chat", null)]}
      folders={[folder("escape-folder", "Work")]}
      activeConversationId="escape-chat" onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    const source = screen.getByRole("button", { name: "Escape chat" });
    source.focus();
    fireEvent.keyDown(source, { key: " ", code: "Space" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    fireEvent.keyDown(source, { key: "Escape", code: "Escape" });
    expect(onMove).not.toHaveBeenCalled();
    expect(container.querySelector('[data-conversation-row="escape-chat"]')?.hasAttribute("data-dragging-conversation")).toBe(false);
  });

  it("disables dnd-kit dragging while folders load or search results are shown", () => {
    const onMove = vi.fn().mockResolvedValue(undefined);
    const { container, rerender } = render(<ConversationList
      conversations={[conversation("c1", "Already filed", "f1")]}
      folders={[folder("f1", "Engineering")]} activeConversationId="c1"
      onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
    />);
    rerender(<ConversationList conversations={[conversation("c1", "Already filed", "f1")]}
      folders={[folder("f1", "Engineering")]} foldersLoading activeConversationId="c1"
      onNewChat={noop} onSelect={noop} onMoveConversation={onMove} />);
    expect(container.querySelector('[data-conversation-row="c1"] [data-draggable-conversation]')).toBeNull();
    rerender(<ConversationList conversations={[conversation("c1", "Already filed", "f1")]}
      folders={[folder("f1", "Engineering")]} activeConversationId="c1" searchQuery="Already"
      onNewChat={noop} onSelect={noop} onMoveConversation={onMove} />);
    expect(container.querySelector('[data-conversation-row="c1"] [data-draggable-conversation]')).toBeNull();
  });

  it("creates a chat through the Folder action and keeps keyboard menu access after failure", async () => {
    const createInFolder = vi.fn().mockRejectedValueOnce(new Error("failed")).mockResolvedValueOnce(undefined);
    render(<ConversationList conversations={[]} folders={[folder("folder-id", "Research")]} activeConversationId={null}
      onNewChat={noop} onSelect={noop} onNewChatInFolder={createInFolder} />);
    fireEvent.click(screen.getByRole("button", { name: "Folder actions for Research" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "New Chat" }));
    expect(createInFolder).toHaveBeenCalledWith("folder-id");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Folder actions for Research" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "New Chat" }));
    await waitFor(() => expect(createInFolder).toHaveBeenCalledTimes(2));
  });

  it("collapses a selected folder without changing selection", () => {
    const select = vi.fn();
    render(<ConversationList conversations={[conversation("c1", "Selected", "f1")]}
      folders={[folder("f1", "Engineering")]} activeConversationId="c1" onNewChat={noop} onSelect={select} />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse Engineering" }));
    expect(screen.queryByText("Selected")).toBeNull();
    expect(screen.getByRole("button", { name: "Expand Engineering" }).getAttribute("aria-expanded")).toBe("false");
    expect(select).not.toHaveBeenCalled();
  });

  it("groups only server-provided search matches and keeps conversation rename/delete actions in folders", () => {
    const rename = vi.fn();
    const remove = vi.fn();
    const { container } = render(<ConversationList
      conversations={[conversation("c1", "Matched title", "f1")]}
      folders={[folder("f1", "Engineering"), folder("f2", "Empty folder")]}
      activeConversationId="c1" onNewChat={noop} onSelect={noop} onRename={rename} onDelete={remove}
      searchQuery="Matched" onSearchChange={noop}
    />);
    expect(screen.getByText("Matched title")).toBeTruthy();
    expect(container.querySelector('[data-conversation-search-results] [data-conversation-row="c1"]')).not.toBeNull();
    expect(container.querySelector('[data-conversation-folder="f1"]')).toBeNull();
    expect(container.querySelector('[data-conversation-folder="f2"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Matched title" }));
    expect(screen.getByRole("menuitem", { name: "Rename" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "Delete" })).toBeTruthy();
  });
});
