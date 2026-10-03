// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConversationList, type Conversation, type ConversationFolder } from "@ava/agent-ui";

const folder: ConversationFolder = {
  id: "folder-x", name: "Folder X", created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
};
const project = {
  id: "project-p", name: "Project P", description: null, instructions: null,
  is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  contract_version: "v1" as const,
};
const conversation = (
  id: string,
  title: string,
  options: Partial<Pick<Conversation, "isArchived" | "isPinned" | "folderId" | "projectId">> = {},
): Conversation => ({
  id, title, messages: [{ id: `${id}-message`, role: "assistant", content: `${title} transcript` }],
  isArchived: false, isPinned: false, folderId: null, projectId: null,
  run: { runId: `${id}-run`, backendStatus: "running", uiPhase: "running", runError: null, pendingMessageId: null, runEpoch: "epoch" },
  ...options,
});
const noop = () => undefined;

describe("conversation archive sidebar", () => {
  it("keeps archived Folder and Ungrouped conversations out of active lists and avoids Project duplicates", () => {
    const activeFolder = conversation("active-folder", "Active Folder", { folderId: folder.id, projectId: project.id });
    const archivedFolder = conversation("archived-folder", "Archived Folder", { isArchived: true, folderId: folder.id, projectId: project.id });
    const archivedOnlyFolder = conversation("archived-only", "Archived only", { isArchived: true, folderId: "folder-y" });
    const activeLoose = conversation("active-loose", "Active Loose");
    const archivedLoose = conversation("archived-loose", "Archived Loose", { isArchived: true });
    const { container } = render(<ConversationList
      conversations={[activeFolder, archivedFolder, archivedOnlyFolder, activeLoose, archivedLoose]}
      folders={[folder, { ...folder, id: "folder-y", name: "Folder Y" }]} projects={[project]} projectConversationIds={{ [project.id]: [activeFolder.id, archivedFolder.id] }}
      activeConversationId={activeFolder.id} onNewChat={noop} onSelect={noop} onExpandProject={noop}
    />);

    fireEvent.click(screen.getByRole("button", { name: "Expand Project P" }));
    expect(screen.getByText("Active Folder")).toBeTruthy();
    expect(screen.getByText("Active Loose")).toBeTruthy();
    expect(screen.queryByText("Archived Folder")).toBeNull();
    expect(screen.queryByText("Archived Loose")).toBeNull();
    expect(container.querySelectorAll('[data-conversation-row="active-folder"]')).toHaveLength(1);
    expect(within(container.querySelector(`[data-project-sidebar="${project.id}"]`)!).getByText("No conversations")).toBeTruthy();
    expect(container.querySelector('[data-folder-drop-target="folder-x"]')?.querySelectorAll("[data-conversation-row]")).toHaveLength(1);
    expect(within(container.querySelector('[data-folder-drop-target="folder-y"]')!).getByText("No conversations")).toBeTruthy();
    expect(container.querySelector('[data-folder-drop-target="ungrouped"]')?.querySelectorAll("[data-conversation-row]")).toHaveLength(1);
  });

  it("aggregates archived conversations regardless of Folder or Project, disables drag, and exposes Restore/Delete", () => {
    const archivedFolder = conversation("archived-folder", "Archived Folder", { isArchived: true, folderId: folder.id, projectId: project.id });
    const archivedLoose = conversation("archived-loose", "Archived Loose", { isArchived: true, isPinned: true });
    const onMove = vi.fn();
    render(<ConversationList conversations={[archivedFolder, archivedLoose]} folders={[folder]} projects={[project]}
      activeConversationId={null} onNewChat={noop} onSelect={noop} onMoveConversation={onMove}
      onSetConversationArchived={vi.fn()} onDelete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));

    expect(screen.getByText("Archived Folder")).toBeTruthy();
    expect(screen.getByText("Archived Loose")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New Folder" })).toBeNull();
    const rows = screen.getAllByRole("button", { name: /Archived (Folder|Loose)/ });
    for (const row of rows) expect(row.hasAttribute("data-draggable-conversation")).toBe(false);
    expect(onMove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Archived Folder" }));
    expect(screen.getByRole("menuitem", { name: "Restore" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Delete" })).toBeTruthy();
  });

  it("restores the same selected Project+Folder conversation to its active Folder without losing metadata", async () => {
    const original = conversation("selected", "Selected", { isArchived: true, isPinned: true, folderId: folder.id, projectId: project.id });
    function Sidebar() {
      const [item, setItem] = useState(original);
      const active = item.isArchived ? [] : [item];
      const archived = item.isArchived ? [item] : [];
      return <ConversationList conversations={[item]} activeConversations={active} archivedConversations={archived}
        folders={[folder]} activeConversationId={item.id} onNewChat={noop} onSelect={noop}
        onSetConversationArchived={async (_id, isArchived) => setItem((current) => ({ ...current, isArchived }))} />;
    }
    const { container } = render(<Sidebar />);
    expect(screen.queryByRole("button", { name: "Selected" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Restore" }));
    await waitFor(() => expect(container.querySelector('[data-folder-drop-target="folder-x"] [data-conversation-row="selected"]')).not.toBeNull());
    expect(screen.getByRole("button", { name: "Selected" }).getAttribute("aria-current")).toBe("true");
    expect(screen.queryByRole("region", { name: "Archived conversations" })).toBeNull();
    await waitFor(() => expect((document.activeElement as HTMLElement).dataset.conversationItem).toBe("selected"));
  });

  it("restores an archived ungrouped conversation to Ungrouped", async () => {
    const original = conversation("loose", "Loose", { isArchived: true });
    function Sidebar() {
      const [item, setItem] = useState(original);
      return <ConversationList conversations={[item]} activeConversations={item.isArchived ? [] : [item]}
        archivedConversations={item.isArchived ? [item] : []} folders={[folder]} activeConversationId={null}
        onNewChat={noop} onSelect={noop}
        onSetConversationArchived={async (_id, isArchived) => setItem((current) => ({ ...current, isArchived }))} />;
    }
    const { container } = render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Loose" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Restore" }));
    await waitFor(() => expect(screen.getByText("No archived conversations")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Active" }));
    await waitFor(() => expect(container.querySelector('[data-folder-drop-target="ungrouped"] [data-conversation-row="loose"]')).not.toBeNull());
  });

  it("removes a hard-deleted archived conversation without adding it to Active", async () => {
    const archived = conversation("deleted-archive", "Deleted archive", { isArchived: true });
    function Sidebar() {
      const [items, setItems] = useState([archived]);
      return <ConversationList conversations={items} activeConversations={items.filter((item) => !item.isArchived)}
        archivedConversations={items.filter((item) => item.isArchived)} activeConversationId={null}
        onNewChat={noop} onSelect={noop} onDelete={async (id) => setItems((current) => current.filter((item) => item.id !== id))} />;
    }
    const { container } = render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Deleted archive" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(screen.getByText("No archived conversations")).toBeTruthy());
    expect(container.querySelector('[data-conversation-row="deleted-archive"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Active" }));
    expect(container.querySelector('[data-conversation-row="deleted-archive"]')).toBeNull();
  });

  it("moves a selected conversation to Archived after archive and shows an empty state", async () => {
    const item = conversation("selected", "Selected", { isPinned: true, folderId: folder.id, projectId: project.id });
    function Sidebar() {
      const [current, setCurrent] = useState(item);
      const [active, setActive] = useState("selected");
      return <ConversationList conversations={[current]} activeConversations={current.isArchived ? [] : [current]}
        archivedConversations={current.isArchived ? [current] : []} folders={[folder]} activeConversationId={active}
        onNewChat={noop} onSelect={setActive} onSetConversationArchived={async (_id, isArchived) => setCurrent((value) => ({ ...value, isArchived }))} />;
    }
    const { container } = render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(container.querySelector('[data-archived-conversations] [data-conversation-row="selected"]')).not.toBeNull());
    expect(screen.getByRole("button", { name: "Archived" }).getAttribute("aria-current")).toBe("page");
    expect(container.querySelector('[data-conversation-row="selected"] [aria-current="true"]')).not.toBeNull();
    await waitFor(() => expect((document.activeElement as HTMLElement).dataset.conversationItem).toBe("selected"));
  });

  it("does not change the selected conversation when archiving a different row", async () => {
    function Sidebar() {
      const [items, setItems] = useState([conversation("selected", "Selected"), conversation("other", "Other")]);
      return <ConversationList conversations={items} activeConversationId="selected" onNewChat={noop} onSelect={noop}
        onSetConversationArchived={async (id, isArchived) => setItems((current) => current.map((item) => item.id === id ? { ...item, isArchived } : item))} />;
    }
    const { container } = render(<Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Other" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(container.querySelector('[data-conversation-row="other"]')).toBeNull());
    expect(container.querySelector('[data-conversation-row="selected"] [aria-current="true"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: "Active" }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect((document.activeElement as HTMLElement).dataset.conversationItem).toBe("selected"));
  });

  it("keeps canonical state on archive failure and exposes retryable feedback", async () => {
    const item = conversation("failure", "Failure case");
    const onArchive = vi.fn().mockRejectedValueOnce(new Error("private backend detail"));
    render(<ConversationList conversations={[item]} activeConversationId={item.id}
      onNewChat={noop} onSelect={noop} onSetConversationArchived={onArchive} />);
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Failure case" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Unable to update this conversation's archive status");
    expect(screen.getByRole("button", { name: "Failure case" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Archived" }).getAttribute("aria-current")).toBeNull();
    expect(screen.queryByText("private backend detail")).toBeNull();
  });

  it("keeps an archived conversation visible after restore failure", async () => {
    const item = conversation("restore-failure", "Restore failure", { isArchived: true, folderId: folder.id });
    const onArchive = vi.fn().mockRejectedValue(new Error("private backend detail"));
    const { container } = render(<ConversationList conversations={[item]} activeConversationId={null} folders={[folder]}
      onNewChat={noop} onSelect={noop} onSetConversationArchived={onArchive} />);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Restore failure" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Restore" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Unable to update this conversation's archive status");
    expect(container.querySelector('[data-archived-conversations] [data-conversation-row="restore-failure"]')).not.toBeNull();
    expect(screen.queryByText("private backend detail")).toBeNull();
  });

  it("shows an explicit empty Archived state", () => {
    render(<ConversationList conversations={[]} activeConversationId={null} onNewChat={noop} onSelect={noop} />);
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    expect(screen.getByText("No archived conversations")).toBeTruthy();
  });
});
