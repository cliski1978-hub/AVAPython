import { attachmentContextPresentation, attachmentContextSummary, type AttachmentContextItem } from "@ava/agent-ui";
import { useEffect, useRef, useState } from "react";
import { Button } from "@ava/ui-core";
import { getConversationPromptPreview, getRunInspection, listConversationRuns, type ApiClient, type ContextWindowPreview, type RunInspectionResponse, type RunListItem, type RunPromptPreview } from "@ava/api-client";

type InspectionState = { status: "idle" } | ({ runId: string; conversationId: string | null } & (
  { status: "loading" } | { status: "success"; data: RunInspectionResponse } | { status: "error"; message: string }
));

export type RunInspectorTab = "Prompts" | "Request" | "Response" | "Run" | "Events";
const tabs: RunInspectorTab[] = ["Prompts", "Request", "Response", "Run", "Events"];

function json(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "Unavailable";
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return <button type="button" className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2" aria-label={`Copy ${label}`} onClick={() => {
    void navigator.clipboard?.writeText(value).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1000); });
  }}>{copied ? "Copied" : "Copy"}</button>;
}

function TextBlock({ title, value, copyLabel = title }: { title: string; value: string; copyLabel?: string }) {
  return <section className="mb-4 min-w-0">
    <div className="mb-1 flex items-center justify-between gap-2"><h3 className="m-0 text-xs font-semibold text-foreground">{title}</h3><CopyButton value={value} label={copyLabel} /></div>
    <pre className="max-h-[45vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed text-foreground">{value}</pre>
  </section>;
}

function ContextCompaction({ value }: { value: NonNullable<NonNullable<RunInspectionResponse["snapshot"]>["context_compaction"]> }) {
  return <section className="mb-4 rounded-md border border-border p-3 text-xs">
    <h3 className="mb-2 mt-0 text-sm font-semibold">Conversation Compaction</h3>
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
      <dt>Status</dt><dd className="m-0">{value.failed ? "Failed · safe history fallback used" : value.used ? "Summary used" : value.attempted ? "No summary created" : "Not needed"}</dd>
      {value.summary_id && <><dt>Summary</dt><dd className="m-0 break-all">{value.summary_id} · v{value.summary_version}</dd></>}
      {value.covers_through_message_id && <><dt>Covers through</dt><dd className="m-0 break-all">{value.covers_through_message_id} · sequence {value.covers_through_sequence}</dd></>}
      <dt>Summary tokens</dt><dd className="m-0">{value.summary_token_count.toLocaleString()}</dd>
      <dt>Usage</dt><dd className="m-0">{value.estimated_before_tokens.toLocaleString()} → {value.estimated_after_tokens.toLocaleString()} estimated tokens</dd>
      <dt>Recent raw messages</dt><dd className="m-0 break-words">{value.recent_message_ids.length ? value.recent_message_ids.join(", ") : "—"}</dd>
    </dl>
    {value.failure_reason && <p role="status" className="mb-0 mt-2 text-muted-foreground">Summary generation failed ({value.failure_reason}); the existing summary or deterministic history window was used.</p>}
    {value.summary_content && <details className="mt-3"><summary className="cursor-pointer font-semibold">Inspect exact summary content used</summary><pre className="max-h-[35vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed">{value.summary_content}</pre></details>}
  </section>;
}

function capturedAttachmentBlock(item: AttachmentContextItem, request: NonNullable<RunInspectionResponse["snapshot"]>["normalized_request"] = []) {
  return request.find(message => message.role === "user" && message.message_id == null && message.content.includes(`--- BEGIN ATTACHMENT CONTENT (${item.attachment_id}) ---`))?.content;
}

function AttachmentContent({ item, block }: { item: AttachmentContextItem; block?: string }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="mt-2">
    <summary className="cursor-pointer font-medium">View Context Sent — {item.file_name}</summary>
    {open && <TextBlock title="Exact extracted content" value={item.text ?? "Content snapshot was not captured."} copyLabel={`${item.file_name} extracted content`} />}
    {open && block && <CopyButton value={block} label={`${item.file_name} context block`} />}
  </details>;
}

function Attachments({ items, request, prospective = false, requestCanFit }: { requestCanFit?: boolean; items?: AttachmentContextItem[]; request?: NonNullable<RunInspectionResponse["snapshot"]>["normalized_request"]; prospective?: boolean }) {
  return <section aria-label="Conversation Attachments" className="mb-4 text-xs">
    <h3 className="mb-2 mt-0 text-sm font-semibold">Conversation Attachments</h3>
    {items == null ? <p className="text-muted-foreground">{prospective ? "Attachment readiness is checked while you draft." : "Attachment context metadata was not captured for this run."}</p> : !items.length ? <p className="text-muted-foreground">{prospective ? "No attachment context in this preview." : "No attachment context used."}</p> : <>
      <p className="text-muted-foreground">{prospective ? "Draft preview: " : "Captured run: "}{attachmentContextSummary(items)}</p>
      {items.map(item => <article key={item.attachment_id} className="mb-2 rounded-md border border-border bg-background p-3">
        <h4 className="mb-2 mt-0 break-words font-semibold">{item.file_name}</h4>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
          <dt>Status</dt><dd className="m-0">{item.status === "included" && item.included ? prospective ? "Ready for context" : "Included" : item.status === "unsupported" ? "Unsupported" : item.status === "extraction_failed" ? "Extraction failed" : item.status === "excluded_context_limit" ? "Excluded · context limit" : "Not included"}</dd>
          <dt>Text extraction</dt><dd className="m-0">{item.status === "included" || item.status === "excluded_context_limit" ? "Succeeded" : item.status === "unsupported" ? "Unsupported" : "Failed"}</dd><dt>Included</dt><dd className="m-0">{item.included ? "Yes" : "No"}</dd>
          <dt>Content type</dt><dd className="m-0 break-all">{item.media_type}</dd>
          <dt>Attachment ID</dt><dd className="m-0 break-all">{item.attachment_id} <CopyButton value={item.attachment_id} label={`${item.file_name} attachment ID`} /></dd>
          <dt>{item.status === "excluded_context_limit" ? "Tokens required" : "Token contribution"}</dt><dd className="m-0">{item.token_count == null || (item.status === "excluded_context_limit" && requestCanFit === false && item.token_count === 0) ? "Not captured" : `${item.token_count.toLocaleString()} (${item.count_accuracy ?? "accuracy not captured"})`}</dd>
        </dl>
        {!item.included && <p className="mb-0 mt-2 text-muted-foreground">{item.status === "excluded_context_limit" && requestCanFit === false ? "The required run prompt exceeds the model input budget; attachment context was not sent." : attachmentContextPresentation(item).detail}</p>}
        {!prospective && item.included && item.text != null && <AttachmentContent key={item.attachment_id} item={item} block={capturedAttachmentBlock(item, request)} />}
      </article>)}
      <p className="text-muted-foreground">Attachments are contextual data. Conversation compaction summarizes chat history, not these files.</p>
    </>}
  </section>;
}

function PromptLayers({ layers, request, currentMessageId, draftPrompt = "", attachments, summary, requestCanFit }: { requestCanFit?: boolean; attachments?: AttachmentContextItem[]; summary?: string | null; layers: RunPromptPreview | null | undefined; request?: NonNullable<RunInspectionResponse["snapshot"]>["normalized_request"]; currentMessageId?: string | null; draftPrompt?: string }) {
  if (layers == null) return <><p className="text-sm text-muted-foreground">No captured prompt snapshot is available for this run.</p><Attachments items={attachments} request={request} requestCanFit={requestCanFit} /></>;
  const items = [
    { title: "AVA Root System", content: layers.root_system_prompt },
    ...layers.resolved_core_prompts.map((prompt) => ({ title: `CORE Prompt — ${prompt.name}`, content: prompt.prompt_text, detail: `ID: ${prompt.id} · Scope: ${prompt.winning_scope_type}${prompt.winning_scope_id ? ` (${prompt.winning_scope_id})` : ""}${prompt.winning_assignment_id ? ` · Assignment: ${prompt.winning_assignment_id}` : ""}` })),
    ...(layers.project_instructions ? [{ title: "Project Instructions", content: layers.project_instructions }] : []),
  ];
  const currentIndex = currentMessageId ? request?.findIndex((message) => message.message_id === currentMessageId) ?? -1 : -1;
  const fallbackCurrentIndex = currentIndex >= 0 ? currentIndex : (request?.map((message) => message.role).lastIndexOf("user") ?? -1);
  const current = fallbackCurrentIndex >= 0 ? request?.[fallbackCurrentIndex] : undefined;
  const attachmentBlocks = new Set((attachments ?? []).filter(item => item.included).map(item => capturedAttachmentBlock(item, request)).filter(Boolean));
  const history = request?.filter((message, index) => index !== fallbackCurrentIndex && !(message.message_id == null && attachmentBlocks.has(message.content)));
  return <>
    <ol className="mb-4 list-decimal pl-5 text-xs text-muted-foreground">{items.map((item, i) => <li key={`${item.title}-${i}`}>{item.title}</li>)}{summary && <li>Conversation Summary</li>}<li>Recent Conversation History</li><li>Conversation Attachments</li><li>Current User Message</li></ol>
    {items.map((item, index) => <section className="mb-4" key={`${item.title}-${index}`}><h3 className="m-0 text-sm font-semibold">{index + 1}. {item.title}</h3>{"detail" in item && <p className="my-1 text-xs text-muted-foreground">{item.detail}</p>}<TextBlock title="Content" value={item.content} copyLabel={item.title} /></section>)}
    {summary && <TextBlock title="Conversation Summary" value={summary} />}
    {request ? <><TextBlock title="Conversation History Context" value={json(history?.filter((message) => message.role !== "system"))} copyLabel="conversation history" /><Attachments items={attachments} request={request} requestCanFit={requestCanFit} />{current ? <TextBlock title="Current User Message" value={json(current)} copyLabel="current user message" /> : null}</> : <><Attachments items={attachments} prospective /><TextBlock title="Current User Message — Draft Preview" value={draftPrompt.trim() ? draftPrompt : "Type a message in the composer to preview it here."} copyLabel="draft user message" /><p className="text-xs text-muted-foreground">This draft is not submitted. Conversation history and runtime formatting are added when a run starts.</p></>}
  </>;
}

export function RunInspector({ client, conversationId, activeRunId, draftPrompt = "", contextWindowPreview, contextWindowPreviewLoading = false, contextWindowPreviewError = false, onClose, selectedTab, onTabChange }: { client: ApiClient; conversationId: string | null; activeRunId?: string | null; draftPrompt?: string; contextWindowPreview?: ContextWindowPreview | null; contextWindowPreviewLoading?: boolean; contextWindowPreviewError?: boolean; onClose: () => void; selectedTab: RunInspectorTab; onTabChange: (tab: RunInspectorTab) => void }) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [inspectionState, setInspectionState] = useState<InspectionState>({ status: "idle" });
  const retryInspection = useRef<(() => void) | null>(null);
  const [preview, setPreview] = useState<RunPromptPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const generation = useRef(0);
  const [historicalSelection, setHistoricalSelection] = useState(false);

  useEffect(() => {
    const token = ++generation.current;
    setRuns([]); setInspectionState({ status: "idle" }); setPreview(null); setSelectedRunId(null); setHistoricalSelection(false); setError(null);
    if (conversationId == null) return;
    setRunLoading(true);
    void listConversationRuns(client, conversationId).then((items) => {
      if (generation.current !== token) return;
      setRuns(items);
      const selected = activeRunId && items.some((run) => run.run_id === activeRunId) ? activeRunId : items.length ? items[items.length - 1].run_id : null;
      setSelectedRunId(selected);
    }).catch(() => { if (generation.current === token) setError("Runs for this conversation could not be loaded."); })
      .finally(() => { if (generation.current === token) setRunLoading(false); });
    return () => { generation.current += 1; };
  }, [client, conversationId, activeRunId]);

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    void getConversationPromptPreview(client, conversationId).then((result) => { if (!cancelled) setPreview(result); })
      .catch(() => { if (!cancelled) setError("Current conversation prompt configuration could not be resolved."); });
    return () => { cancelled = true; };
  }, [client, conversationId]);

  const selectedRunStatus = runs.find(run => run.run_id === selectedRunId)?.status;

  useEffect(() => {
    if (selectedRunId == null) { setInspectionState({ status: "idle" }); return; }
    const identity = { runId: selectedRunId, conversationId };
    let cancelled = false;
    let queryGeneration = 0;
    let inFlight = false;
    const refresh = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      const query = ++queryGeneration;
      setInspectionState({ ...identity, status: "loading" });
      try {
        const result = await getRunInspection(client, selectedRunId);
        if (!cancelled && query === queryGeneration) { setInspectionState({ ...identity, status: "success", data: result }); setError(null); }
      } catch {
        if (!cancelled && query === queryGeneration) setInspectionState({ ...identity, status: "error", message: "Run inspection could not be loaded." });
      } finally { inFlight = false; }
    };
    retryInspection.current = () => { void refresh(); };
    void refresh();
    const timer = selectedRunStatus && ["pending", "running", "waiting_for_approval"].includes(selectedRunStatus)
      ? window.setInterval(() => { void refresh(); void listConversationRuns(client, conversationId ?? "").then((items) => { if (!cancelled) setRuns(items); }).catch(() => undefined); }, 1000)
      : undefined;
    return () => { cancelled = true; retryInspection.current = null; if (timer != null) window.clearInterval(timer); };
  }, [client, conversationId, selectedRunId, selectedRunStatus]);

  const selectedInspectionState = inspectionState.status !== "idle" && inspectionState.runId === selectedRunId && inspectionState.conversationId === conversationId ? inspectionState : null;
  const inspection = selectedInspectionState?.status === "success" ? selectedInspectionState.data : null;
  const currentInspection = inspection?.run_id === selectedRunId && inspection?.conversation_id === conversationId ? inspection : null;
  const inspectionFeedback = selectedInspectionState?.status === "error" ? (
    <div role="alert" className="text-sm text-destructive">
      <p>{selectedInspectionState.message}</p>
      <Button size="sm" onClick={() => retryInspection.current?.()}>Retry</Button>
    </div>
  ) : selectedInspectionState?.status === "loading" ? (
    <p role="status" className="text-sm text-muted-foreground">Loading selected run inspection…</p>
  ) : <p className="text-sm text-muted-foreground">Select a run to inspect.</p>;
  const snapshot = currentInspection?.snapshot;
  const previewingDraft = !historicalSelection && draftPrompt.trim().length > 0 && selectedTab === "Prompts" && preview != null;
  const contextWindowStatus = <section aria-live="polite" className="border-b border-border px-3 py-2 text-xs"><h3 className="mb-1 mt-0 text-xs font-semibold">Current draft estimate</h3>{!draftPrompt.trim() ? <span className="text-muted-foreground">Context window estimate appears while you draft a message.</span> : contextWindowPreviewLoading ? <span className="text-muted-foreground">Estimating context window…</span> : contextWindowPreviewError ? <span role="status" className="text-destructive">Context window estimate unavailable. Check the selected model configuration.</span> : contextWindowPreview ? <><strong className={contextWindowPreview.can_fit ? "text-foreground" : "text-destructive"}>{contextWindowPreview.can_fit ? "Prompt fits" : "Prompt exceeds the available input budget"}</strong><p className="mb-0 mt-1 text-muted-foreground">{contextWindowPreview.estimated_input_tokens.toLocaleString()} estimated prompt tokens · {contextWindowPreview.input_budget_tokens?.toLocaleString() ?? "unbounded"} available · {contextWindowPreview.dropped_turn_count} turns trimmed for fit{contextWindowPreview.active_summary_version ? ` · summary v${contextWindowPreview.active_summary_version} (${contextWindowPreview.active_summary_token_count?.toLocaleString() ?? 0} tokens)` : ""}{contextWindowPreview.model_id ? ` · ${contextWindowPreview.model_id}` : ""}</p>{contextWindowPreview.attachments?.length ? <p className="mb-0 mt-1">Attachment Context: {contextWindowPreview.attachment_context_tokens?.toLocaleString() ?? "not captured"} tokens ({contextWindowPreview.count_accuracy}) · {attachmentContextSummary(contextWindowPreview.attachments)}</p> : null}{contextWindowPreview.compaction_recommended && <p className="mb-0 mt-1 font-medium">Context nearing limit · AVA will compact older conversation turns automatically when this run starts.</p>}</> : <span className="text-muted-foreground">Context window estimate unavailable.</span>}</section>;
  const content = previewingDraft ? <><p className="mb-3 text-xs text-muted-foreground">Preview of the current unsent prompt with the current instruction configuration.</p><PromptLayers layers={preview} draftPrompt={draftPrompt} attachments={contextWindowPreview?.attachments} /></> : !currentInspection ? selectedRunId ? inspectionFeedback : preview ? <><p className="mb-3 text-xs text-muted-foreground">Current prompt configuration preview; captured run snapshots appear after execution.</p><PromptLayers layers={preview} draftPrompt={draftPrompt} attachments={contextWindowPreview?.attachments} /></> : <p className="text-sm text-muted-foreground">{runLoading ? "Loading run inspection…" : runs.length === 0 ? "No run selected." : error ?? "Select a run to inspect."}</p> : (() => {
    switch (selectedTab) {
      case "Prompts": return <><PromptLayers key={currentInspection.run_id} layers={snapshot?.prompt_layers} request={snapshot?.normalized_request} currentMessageId={currentInspection?.source_user_message_id} attachments={snapshot?.attachments} summary={snapshot?.context_compaction?.used ? snapshot.context_compaction.summary_content : null} requestCanFit={snapshot?.context_window?.can_fit} />{snapshot?.context_compaction && <ContextCompaction value={snapshot.context_compaction} />}</>;
      case "Request": return <>
        <TextBlock title="Normalized AVA Request" value={json(snapshot?.normalized_request)} copyLabel="normalized request" />
        <TextBlock title="Runtime Request" value={snapshot?.runtime_request === undefined || snapshot.runtime_request === null ? "Runtime-specific request was not captured by this runtime." : json(snapshot.runtime_request)} copyLabel="runtime request" />
      </>;
      case "Response": return <>
        <TextBlock title="Runtime Response" value={snapshot?.runtime_response === undefined || snapshot.runtime_response === null ? "Runtime response metadata was not captured." : json(snapshot.runtime_response)} copyLabel="runtime response" />
        <TextBlock title="Normalized AVA Response" value={snapshot?.normalized_response === undefined || snapshot.normalized_response === null ? "No normalized response snapshot is available." : json(snapshot.normalized_response)} copyLabel="normalized response" />
        <TextBlock title="Final Assistant Message" value={currentInspection.assistant_message ?? "No assistant message is persisted for this run."} copyLabel="final assistant message" />
      </>;
      case "Run": return <><Attachments key={currentInspection.run_id} items={snapshot?.attachments} request={snapshot?.normalized_request} requestCanFit={snapshot?.context_window?.can_fit} />
        {snapshot?.context_window && <section className="mb-4 rounded-md border border-border p-3 text-xs"><h3 className="mb-2 mt-0 text-sm font-semibold">Context Window</h3>{snapshot.context_window.can_fit === false && <p role="alert" className="mb-2 text-destructive">This request exceeded the selected model's input budget: {snapshot.context_window.required_input_tokens?.toLocaleString() ?? snapshot.context_window.estimated_input_tokens.toLocaleString()} estimated tokens required.</p>}<dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1"><dt>Window</dt><dd className="m-0">{snapshot.context_window.context_window_tokens?.toLocaleString() ?? "Unknown"} tokens</dd><dt>Input budget</dt><dd className="m-0">{snapshot.context_window.input_budget_tokens?.toLocaleString() ?? "Unbounded"} tokens</dd><dt>Estimated input</dt><dd className="m-0">{snapshot.context_window.estimated_input_tokens.toLocaleString()} tokens</dd><dt>Attachment Context</dt><dd className="m-0">{snapshot.context_window.attachment_context_tokens == null ? "Not captured" : `${snapshot.context_window.attachment_context_tokens.toLocaleString()} tokens`}</dd><dt>Output reserve</dt><dd className="m-0">{snapshot.context_window.output_reserve_tokens.toLocaleString()} tokens</dd><dt>History omitted</dt><dd className="m-0">{snapshot.context_window.dropped_message_count} messages · {snapshot.context_window.dropped_turn_count} turns</dd><dt>Count accuracy</dt><dd className="m-0">{snapshot.context_window.count_accuracy}</dd></dl></section>}
        {snapshot?.context_compaction && <ContextCompaction value={snapshot.context_compaction} />}
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-2 text-xs"><dt>Run ID</dt><dd className="m-0 break-all">{currentInspection.run_id} <CopyButton value={currentInspection.run_id} label="run ID" /></dd><dt>Conversation</dt><dd className="m-0 break-all">{currentInspection.conversation_id ?? "—"}</dd><dt>Status</dt><dd className="m-0">{currentInspection.status}</dd><dt>Created</dt><dd className="m-0">{currentInspection.created_at}</dd><dt>Updated</dt><dd className="m-0">{currentInspection.updated_at}</dd><dt>Assistant Message ID</dt><dd className="m-0 break-all">{currentInspection.assistant_message_id ?? "—"}</dd>
          {Object.entries(currentInspection.execution_selection ?? {}).filter(([key, value]) => key !== "contract_version" && value != null).map(([key, value]) => <div className="contents" key={key}><dt>{key.replaceAll("_", " ")}</dt><dd className="m-0 break-words">{String(value)}</dd></div>)}
        </dl>
        <TextBlock title="Execution Resolution Sources" value={json(snapshot?.execution_resolution ?? {})} />
      </>;
      case "Events": return <div className="space-y-3">{currentInspection.events.length === 0 ? <p className="text-sm text-muted-foreground">No run events yet.</p> : currentInspection.events.map((event) => <article className="rounded-md border border-border p-2" key={event.event_id}><header className="flex justify-between gap-2 text-xs"><strong>{event.sequence ?? "—"} · {event.event_type}</strong><time>{event.timestamp}</time></header><p className="mb-1 mt-1 break-all font-mono text-[10px] text-muted-foreground">{event.event_id}</p><TextBlock title="Payload" value={json(event.payload)} copyLabel="event payload" /></article>)}</div>;
    }
  })();

  return <aside aria-label="Run Inspector" className="flex h-full min-h-0 min-w-0 flex-col border-l border-border bg-background text-foreground">
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border p-3"><h2 className="m-0 whitespace-nowrap text-sm font-semibold">Run Inspector</h2><button type="button" onClick={onClose} aria-label="Close Run Inspector" className="rounded px-2 py-1 text-sm hover:bg-muted focus-visible:outline focus-visible:outline-2">×</button></div>
    <div className="shrink-0 border-b border-border p-2"><label className="mb-1 block text-[11px] text-muted-foreground" htmlFor="inspector-run-select">Run</label><select id="inspector-run-select" aria-label="Select run" className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground" value={selectedRunId ?? ""} disabled={runLoading || runs.length === 0} onChange={(event) => { setHistoricalSelection(Boolean(event.target.value)); setSelectedRunId(event.target.value || null); }}><option value="">{runLoading ? "Loading…" : "No run selected"}</option>{[...runs].reverse().map((run) => <option value={run.run_id} key={run.run_id}>{new Date(run.created_at).toLocaleString()} · {run.status} · {run.run_id.slice(0, 8)}</option>)}</select></div>
    <div role="tablist" aria-label="Run inspection sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border p-2">{tabs.map((name) => <button type="button" role="tab" aria-selected={selectedTab === name} key={name} onClick={() => onTabChange(name)} className={`rounded px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 ${selectedTab === name ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>{name}</button>)}</div>
    {draftPrompt.trim() ? contextWindowStatus : null}
    {error && <p role="alert" className="m-2 text-xs text-destructive">{error}</p>}
    <div className="min-h-0 flex-1 overflow-auto p-3">{content}</div>
  </aside>;
}
