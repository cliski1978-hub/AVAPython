// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect, useState } from "react";
import { AppearanceProvider, useAppearance } from "@ava/ui-core";
import { getConversationPromptPreview, getRunInspection, listConversationRuns, type ApiClient, type RunInspectionResponse } from "@ava/api-client";
import type { AttachmentContextItem } from "@ava/agent-ui";
import { RunInspector, type RunInspectorTab } from "./RunInspector";

vi.mock("@ava/api-client", async load => ({ ...await load<typeof import("@ava/api-client")>(), getConversationPromptPreview: vi.fn(), getRunInspection: vi.fn(), listConversationRuns: vi.fn() }));
const client = {} as ApiClient;
const item = (status: AttachmentContextItem["status"], id: string, text: string | null = null): AttachmentContextItem => ({ attachment_id: id, file_name: `${id}.md`, media_type: "text/markdown", status, included: status === "included", text, token_count: status === "included" ? 93 : status === "excluded_context_limit" ? 5072 : 0, count_accuracy: "estimated", error_code: null, error_message: "PRIVATE STORAGE PATH" });
const block = (id: string, text: string) => `[Conversation Attachment]\n--- BEGIN ATTACHMENT CONTENT (${id}) ---\n${text}\n--- END ATTACHMENT CONTENT (${id}) ---`;
const snapshot = (runId: string, cid: string, attachments: AttachmentContextItem[]): RunInspectionResponse => ({ run_id: runId, conversation_id: cid, status: "completed", created_at: "2026-10-09T12:00:00Z", updated_at: "2026-10-09T12:00:00Z", source_user_message_id: "current", events: [], snapshot: { execution_resolution: {}, prompt_layers: { root_system_prompt: "ROOT", resolved_core_prompts: [] }, attachments, normalized_request: [{ role: "system", content: "ROOT" }, { role: "user", content: "HISTORY", message_id: "old" }, ...attachments.filter(a => a.included).map(a => ({ role: "user" as const, content: block(a.attachment_id, a.text ?? "") })), { role: "user", content: "CURRENT", message_id: "current" }], runtime_request: { captured: "ACTUAL RUNTIME REQUEST" } } });
const runs = (ids: string[]) => ids.map(run_id => ({ run_id, status: "completed" as const, contract_version: "v1" as const, created_at: "2026-10-09T12:00:00Z", updated_at: "2026-10-09T12:00:00Z" }));
function Harness({ cid = "a", draft = "" }: { cid?: string; draft?: string }) {
  const [selectedTab, onTabChange] = useState<RunInspectorTab>("Prompts");
  return <RunInspector client={client} conversationId={cid} draftPrompt={draft} selectedTab={selectedTab} onTabChange={onTabChange} onClose={() => undefined} />;
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getConversationPromptPreview).mockResolvedValue({ root_system_prompt: "CURRENT CONFIG", resolved_core_prompts: [] });
  vi.mocked(listConversationRuns).mockResolvedValue(runs(["run-1"]));
});

describe("historical attachment transparency", () => {
  it("shows every recorded outcome and lazily reveals exact captured content, without leaking storage errors", async () => {
    vi.mocked(getRunInspection).mockResolvedValue(snapshot("run-1", "a", [item("included", "notes", "AVA-ATTACHMENT-RUN-8426"), item("unsupported", "diagram"), item("extraction_failed", "broken"), item("excluded_context_limit", "large")]));
    render(<Harness />);
    const section = await screen.findByRole("region", { name: "Conversation Attachments" });
    expect(within(section).getAllByText("Included").length).toBeGreaterThan(0);
    expect(within(section).getAllByText("Unsupported")).toHaveLength(2);
    expect(within(section).getByText("Yes")).toBeTruthy();
    expect(within(section).getByText("Extraction failed")).toBeTruthy();
    expect(within(section).getByText("Excluded · context limit")).toBeTruthy();
    expect(within(section).getByText("5,072 (estimated)")).toBeTruthy();
    expect(within(section).getByText("93 (estimated)")).toBeTruthy();
    expect(screen.queryByText("AVA-ATTACHMENT-RUN-8426")).toBeNull();
    expect(screen.queryByText(/PRIVATE STORAGE PATH/)).toBeNull();
    const details = within(section).getByText("View Context Sent — notes.md").closest("details")!;
    details.open = true; fireEvent(details, new Event("toggle"));
    expect(await within(section).findByText("AVA-ATTACHMENT-RUN-8426")).toBeTruthy();
    expect(within(section).getByRole("button", { name: "Copy notes.md extracted content" })).toBeTruthy();
    expect(within(section).getByRole("button", { name: "Copy notes.md context block" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Request" }));
    const normalized = screen.getByText(/BEGIN ATTACHMENT CONTENT \(notes\)/);
    expect(normalized.textContent!.indexOf("HISTORY")).toBeLessThan(normalized.textContent!.indexOf("BEGIN ATTACHMENT"));
    expect(normalized.textContent!.indexOf("BEGIN ATTACHMENT")).toBeLessThan(normalized.textContent!.indexOf("CURRENT"));
    expect(screen.getByText(/ACTUAL RUNTIME REQUEST/)).toBeTruthy();
  });

  it("uses selected run snapshots, preserving deleted files and omitting files added later", async () => {
    vi.mocked(listConversationRuns).mockResolvedValue(runs(["before-add", "included", "after-delete"]));
    vi.mocked(getRunInspection).mockImplementation(async (_client, id) => snapshot(id, "a", id === "included" ? [item("included", "deleted-file", "VERSION A")] : []));
    render(<Harness />);
    expect(await screen.findByText("No attachment context used.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "included" } });
    expect(await screen.findByText("deleted-file.md")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "before-add" } });
    expect(screen.queryByText("deleted-file.md")).toBeNull();
    expect(await screen.findByText("No attachment context used.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "after-delete" } });
    expect(await screen.findByText("No attachment context used.")).toBeTruthy();
  });

  it("rejects delayed conversation and historical-run results", async () => {
    const a = deferred<RunInspectionResponse>(), old = deferred<RunInspectionResponse>();
    vi.mocked(listConversationRuns).mockImplementation(async (_client, cid) => runs(cid === "a" ? ["a"] : ["old", "new"]));
    vi.mocked(getRunInspection).mockImplementation(async (_client, id) => id === "a" ? a.promise : id === "old" ? old.promise : snapshot(id, "b", [item("included", "b-file")]));
    const view = render(<Harness />);
    await waitFor(() => expect(getRunInspection).toHaveBeenCalledWith(client, "a"));
    view.rerender(<Harness cid="b" />);
    expect(await screen.findByText("b-file.md")).toBeTruthy();
    a.resolve(snapshot("a", "a", [item("included", "stale-a")]));
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "old" } });
    expect(screen.queryByText("b-file.md")).toBeNull();
    await waitFor(() => expect(getRunInspection).toHaveBeenCalledWith(client, "old"));
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "new" } });
    expect(await screen.findByText("b-file.md")).toBeTruthy();
    old.resolve(snapshot("old", "b", [item("included", "stale-old")]));
    await waitFor(() => expect(screen.queryByText("stale-old.md")).toBeNull());
    expect(screen.queryByText("stale-a.md")).toBeNull();
  });

  it("does not replace an explicitly selected historical run with draft attachment state", async () => {
    vi.mocked(getRunInspection).mockResolvedValue(snapshot("run-1", "a", [item("included", "historical")]));
    render(<Harness draft="new draft" />);
    await screen.findByLabelText("Select run");
    await waitFor(() => expect(screen.getByLabelText("Select run").querySelector('option[value="run-1"]')).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Select run"), { target: { value: "run-1" } });
    expect(await screen.findByText("historical.md")).toBeTruthy();
    expect(screen.queryByText(/Draft preview:/)).toBeNull();
  });
});

it("shows backend attachment token totals separately from compaction and never computes an estimate", async () => {
  const value = snapshot("run-1", "a", [item("included", "notes", "content")]);
  value.snapshot!.context_window = { context_window_tokens: 2048, input_budget_tokens: 1536, estimated_input_tokens: 130, output_reserve_tokens: 512, dropped_message_count: 0, dropped_turn_count: 0, count_accuracy: "estimated", attachment_context_tokens: 80 };
  vi.mocked(getRunInspection).mockResolvedValue(value);
  render(<Harness />);
  await screen.findByText("notes.md");
  fireEvent.click(screen.getByRole("tab", { name: "Run" }));
  expect(screen.getByText("Attachment Context")).toBeTruthy();
  expect(screen.getByText("80 tokens")).toBeTruthy(); // Not the fixture's per-file 93.
});

function TestAppearance({ mode }: { mode: "light" | "dark" | "system" }) {
  const { setThemeMode } = useAppearance();
  useEffect(() => setThemeMode(mode), [mode, setThemeMode]);
  return null;
}
it.each(["light", "dark", "system"] as const)("keeps attachment details readable under %s appearance", async mode => {
  vi.mocked(getRunInspection).mockResolvedValue(snapshot("run-1", "a", [item("included", "themed", "themed data")]));
  render(<AppearanceProvider><TestAppearance mode={mode} /><Harness /></AppearanceProvider>);
  expect(await screen.findByText("themed.md")).toBeTruthy();
  const region = screen.getByRole("region", { name: "Conversation Attachments" });
  expect(region.querySelector("article")!.className).toContain("bg-background");
  expect(screen.getByRole("complementary", { name: "Run Inspector" }).className).toContain("text-foreground");
  expect(document.documentElement.classList.contains("dark")).toBe(mode === "dark" || (mode === "system" && Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches)));
});

it("reports required-prompt failure without inventing an uncounted file token requirement", async () => {
  const excluded = { ...item("excluded_context_limit", "file"), token_count: 0 };
  const value = snapshot("run-1", "a", [excluded]);
  value.snapshot!.context_window = { context_window_tokens: 128, input_budget_tokens: 96, estimated_input_tokens: 200, output_reserve_tokens: 32, dropped_message_count: 0, dropped_turn_count: 0, count_accuracy: "estimated", can_fit: false };
  vi.mocked(getRunInspection).mockResolvedValue(value);
  render(<Harness />);
  const region = await screen.findByRole("region", { name: "Conversation Attachments" });
  expect(within(region).getByText("Not captured")).toBeTruthy();
  expect(within(region).getByText(/required run prompt exceeds/)).toBeTruthy();
});

it("lets a slow active-run inspection settle instead of repeatedly cancelling its request", async () => {
  vi.useFakeTimers();
  const pending = deferred<RunInspectionResponse>();
  vi.mocked(listConversationRuns).mockResolvedValue([{ ...runs(["run-1"])[0], status: "running" }]);
  vi.mocked(getRunInspection).mockReturnValue(pending.promise);
  const view = render(<Harness />);
  try {
    await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(2500); await Promise.resolve(); });
    expect(getRunInspection).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(snapshot("run-1", "a", [item("included", "slow-file")])));
    expect(screen.getByText("slow-file.md")).toBeTruthy();
  } finally {
    view.unmount();
    vi.useRealTimers();
  }
});
