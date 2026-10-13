// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { ApiClient } from "@ava/api-client";
import { getConversationPromptPreview, getRunInspection, listConversationRuns, previewContextWindow } from "@ava/api-client";
import { RunInspector } from "./RunInspector";

vi.mock("@ava/api-client", async (load) => {
  const actual = await load<typeof import("@ava/api-client")>();
  return { ...actual, getConversationPromptPreview: vi.fn(), getRunInspection: vi.fn(), listConversationRuns: vi.fn(), previewContextWindow: vi.fn() };
});

const client = {} as ApiClient;
const run = (id: string, conversationId: string) => ({
  run_id: id, conversation_id: conversationId, status: "completed" as const, contract_version: "v1" as const,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:02Z",
});
const inspection = (id: string, prompt: string, userText: string, compaction = false) => ({
  run_id: id, conversation_id: id.startsWith("run-conversation-") ? id.slice(4) : "conversation-a", status: "completed" as const,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:02Z",
  snapshot: {
    execution_resolution: { runtime_source: "application_default" },
    prompt_layers: { root_system_prompt: prompt, resolved_core_prompts: [], project_instructions: null },
    normalized_request: [{ role: "system" as const, content: prompt }, { role: "user" as const, content: userText, message_id: "m-1" }],
    runtime_request: { messages: [{ role: "system", content: prompt }, { role: "user", content: userText }] },
    runtime_response: { content: "answer" }, normalized_response: { status: "completed", content: "answer" },
    context_compaction: compaction ? {
      attempted: true, used: true, failed: false, summary_id: "summary-1", summary_version: 2,
      summary_content: "Goals\n- Preserve constraints", summary_token_count: 12,
      covers_through_message_id: "m-9", covers_through_sequence: 17,
      recent_message_ids: ["m-10", "m-11"], source_token_count: 900,
      estimated_before_tokens: 4200, estimated_after_tokens: 1800, trigger_percent: 80, target_percent: 60,
    } : null,
  },
  assistant_message: "answer", events: [],
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

function renderInspector() {
  return render(<RunInspector client={client} conversationId="conversation-a" onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
}

describe("RunInspector", () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(getConversationPromptPreview).mockResolvedValue({ root_system_prompt: "Current root", resolved_core_prompts: [] }); });

  it("settles a failed inspection with an error and Retry instead of loading", async () => {
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockRejectedValue(new Error("private backend trace"));
    render(<RunInspector client={client} conversationId="conversation-a" onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
    await screen.findByText("Run inspection could not be loaded.");
    expect(screen.queryByText("Loading selected run inspection…")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("private backend trace")).toBeNull();
  });

  it("retries the selected run, clears its error while loading, and prevents duplicate submissions", async () => {
    const retry = deferred<ReturnType<typeof inspection>>();
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockRejectedValueOnce(new Error("offline")).mockReturnValueOnce(retry.promise);
    renderInspector();
    const button = await screen.findByRole("button", { name: "Retry" });
    act(() => { fireEvent.click(button); fireEvent.click(button); fireEvent.click(button); });
    expect(screen.getByText("Loading selected run inspection…")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(getRunInspection).toHaveBeenCalledTimes(2);
    expect(getRunInspection).toHaveBeenLastCalledWith(client, "run-a");
    await act(async () => { retry.resolve(inspection("run-a", "Recovered A", "Question A")); });
    expect(await screen.findByText("Recovered A")).toBeTruthy();
    expect(screen.queryByText("Loading selected run inspection…")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("settles a second failure and makes Retry available again", async () => {
    const retry = deferred<ReturnType<typeof inspection>>();
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockRejectedValueOnce(new Error("offline")).mockReturnValueOnce(retry.promise);
    renderInspector();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(screen.getByText("Loading selected run inspection…")).toBeTruthy();
    await act(async () => { retry.reject(new Error("still offline")); });
    expect(await screen.findByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Run inspection could not be loaded.");
    expect(screen.queryByText("Loading selected run inspection…")).toBeNull();
  });

  it.each(["success", "failure"] as const)("ignores a stale retry %s after switching runs", async (outcome) => {
    const retry = deferred<ReturnType<typeof inspection>>();
    const next = deferred<ReturnType<typeof inspection>>();
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-b", "conversation-a"), run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockRejectedValueOnce(new Error("offline")).mockReturnValueOnce(retry.promise).mockReturnValueOnce(next.promise);
    renderInspector();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Select run" }), { target: { value: "run-b" } });
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => { next.resolve(inspection("run-b", "Authoritative B", "Question B")); });
    await screen.findByText("Authoritative B");
    await act(async () => {
      if (outcome === "success") retry.resolve(inspection("run-a", "Stale A", "Question A"));
      else retry.reject(new Error("stale failure"));
    });
    expect(screen.getByText("Authoritative B")).toBeTruthy();
    expect(screen.queryByText("Stale A")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Loading selected run inspection…")).toBeNull();
  });

  it("clears a failed run's error when switching and fetches it anew when returning", async () => {
    const next = deferred<ReturnType<typeof inspection>>();
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-b", "conversation-a"), run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockRejectedValueOnce(new Error("offline")).mockReturnValueOnce(next.promise).mockResolvedValueOnce(inspection("run-a", "Fresh A", "Question A"));
    renderInspector();
    await screen.findByRole("button", { name: "Retry" });
    fireEvent.change(screen.getByRole("combobox", { name: "Select run" }), { target: { value: "run-b" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.getByText("Loading selected run inspection…")).toBeTruthy();
    await act(async () => { next.resolve(inspection("run-b", "Fresh B", "Question B")); });
    await screen.findByText("Fresh B");
    fireEvent.change(screen.getByRole("combobox", { name: "Select run" }), { target: { value: "run-a" } });
    await screen.findByText("Fresh A");
    expect(screen.queryByText("Fresh B")).toBeNull();
    expect(getRunInspection).toHaveBeenLastCalledWith(client, "run-a");
  });

  it("shows captured prompt/request facts and lets the user close the panel", async () => {
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockResolvedValue(inspection("run-a", "System prompt A", "Question A"));
    const onClose = vi.fn();
    function Harness() {
      const [selectedTab, setSelectedTab] = useState<"Prompts" | "Request" | "Response" | "Run" | "Events">("Prompts");
      return <RunInspector client={client} conversationId="conversation-a" onClose={onClose} selectedTab={selectedTab} onTabChange={setSelectedTab} />;
    }
    render(<Harness />);
    expect(await screen.findByText("System prompt A")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Request" }));
    expect((await screen.findAllByText(/Question A/)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Close Run Inspector" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows the exact rolling summary and coverage in the Run Inspector", async () => {
    vi.mocked(listConversationRuns).mockResolvedValue([run("run-a", "conversation-a")]);
    vi.mocked(getRunInspection).mockResolvedValue(inspection("run-a", "System prompt A", "Question A", true));
    render(<RunInspector client={client} conversationId="conversation-a" onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
    expect(await screen.findByText("Summary used")).toBeTruthy();
    expect(screen.getByText(/summary-1 · v2/)).toBeTruthy();
    expect(screen.getByText(/m-9 · sequence 17/)).toBeTruthy();
    fireEvent.click(screen.getByText("Inspect exact summary content used"));
    expect(screen.getAllByText((_text, node) => node?.tagName === "PRE" && node.textContent === "Goals\n- Preserve constraints").length).toBeGreaterThan(0);
  });

  it("drops old conversation data before showing the newly selected conversation", async () => {
    vi.mocked(listConversationRuns).mockImplementation(async (_client, conversationId) => [run(`run-${conversationId}`, conversationId)]);
    vi.mocked(getRunInspection).mockImplementation(async (_client, runId) => inspection(runId, `${runId} system`, `${runId} prompt`));
    const view = render(<RunInspector client={client} conversationId="conversation-a" onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
    expect(await screen.findByText("run-conversation-a system")).toBeTruthy();
    view.rerender(<RunInspector client={client} conversationId="conversation-b" onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
    await waitFor(() => expect(screen.getByText("run-conversation-b system")).toBeTruthy());
    expect(screen.queryByText("run-conversation-a system")).toBeNull();
  });

  it("previews the unsent draft before a conversation or run exists", async () => {
    vi.mocked(getConversationPromptPreview).mockResolvedValue({
      root_system_prompt: "AVA root prompt", resolved_core_prompts: [], project_instructions: null,
    });
    vi.mocked(listConversationRuns).mockResolvedValue([]);
    vi.mocked(previewContextWindow).mockResolvedValue({
      context_window_tokens: 8192, input_budget_tokens: 7168, estimated_input_tokens: 52,
      output_reserve_tokens: 1024, dropped_message_count: 0, dropped_turn_count: 0,
      count_accuracy: "estimated", can_fit: true, required_input_tokens: 52, model_id: "model-a",
      estimated_before_compaction_tokens: 6200, compaction_recommended: true,
    });
    render(<RunInspector client={client} conversationId={null} draftPrompt={"# Draft prompt\n\n- not sent yet"} contextWindowPreview={{ context_window_tokens: 8192, input_budget_tokens: 7168, estimated_input_tokens: 52, output_reserve_tokens: 1024, dropped_message_count: 0, dropped_turn_count: 0, count_accuracy: "estimated", can_fit: true, required_input_tokens: 52, model_id: "model-a", compaction_recommended: true }} onClose={() => undefined} selectedTab="Prompts" onTabChange={() => undefined} />);
    expect(await screen.findByText("AVA root prompt")).toBeTruthy();
    expect(screen.getByText((_text, node) => node?.tagName === "PRE" && node.textContent === "# Draft prompt\n\n- not sent yet")).toBeTruthy();
    expect(screen.getByText(/This draft is not submitted/)).toBeTruthy();
    expect(getConversationPromptPreview).toHaveBeenCalledWith(client, null);
    expect(await screen.findByText("Prompt fits")).toBeTruthy();
    expect(screen.getByText(/AVA will compact older conversation turns automatically/)).toBeTruthy();
  });
});
