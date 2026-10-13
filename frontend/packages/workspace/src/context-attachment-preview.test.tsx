// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { previewContextWindow, type ApiClient, type ContextWindowPreview } from "@ava/api-client";
import { useContextWindowPreview } from "./useContextWindowPreview";
vi.mock("@ava/api-client", async load => ({ ...await load<typeof import("@ava/api-client")>(), previewContextWindow: vi.fn() }));
const client = {} as ApiClient;
const result = (name: string): ContextWindowPreview => ({ context_window_tokens: 2048, input_budget_tokens: 1536, estimated_input_tokens: 143, output_reserve_tokens: 512, dropped_message_count: 0, dropped_turn_count: 0, count_accuracy: "estimated", can_fit: true, required_input_tokens: 143, model_id: name, attachment_context_tokens: 93, attachments: [] });
function Harness({ cid = "a", model = "large", files = "file-a", prompt = "question" }) { const state = useContextWindowPreview(client, { prompt, conversation_id: cid, execution: { model_id: model } }, files); return <div>{state.loading ? "checking" : state.error ? "failed" : state.preview?.model_id ?? "no preview"}</div>; }
beforeEach(() => { vi.clearAllMocks(); });
it("refreshes for attachment mutations, effective settings, and model changes and rejects old responses", async () => {
  let resolve!: (value: ContextWindowPreview) => void;
  vi.mocked(previewContextWindow).mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValue(result("small"));
  const view = render(<Harness />);
  await waitFor(() => expect(previewContextWindow).toHaveBeenCalledTimes(1));
  view.rerender(<Harness cid="b" model="small" files="file-b" />);
  expect(screen.getByText("checking")).toBeTruthy();
  expect(await screen.findByText("small")).toBeTruthy();
  await act(async () => resolve(result("stale-large")));
  expect(screen.queryByText("stale-large")).toBeNull();
  view.rerender(<Harness cid="b" model="small" files="removed-file-b" />);
  await waitFor(() => expect(previewContextWindow).toHaveBeenCalledTimes(3));
  fireFocus();
  await waitFor(() => expect(previewContextWindow).toHaveBeenCalledTimes(4));
  view.rerender(<Harness prompt="" />);
  expect(screen.getByText("no preview")).toBeTruthy();
});
function fireFocus() { act(() => window.dispatchEvent(new Event("focus"))); }
