import { useEffect, useRef, useState } from "react";
import { Modal } from "@ava/ui-core";
import type { ApprovalDataSource, ApprovalDecision, ApprovalDetail, ApprovalHistoryItem, ApprovalQueueSnapshot, ApprovalStatus } from "./contracts";

export interface ApprovalsWorkspaceProps { dataSource?: ApprovalDataSource }
type LoadState = { status: "loading" } | { status: "ready"; snapshot: ApprovalQueueSnapshot } | { status: "unavailable" } | { status: "unauthorized" } | { status: "error" };
const STATUS_LABEL: Record<ApprovalStatus, string> = { pending: "Pending", approved: "Approved", denied: "Denied", expired: "Expired", cancelled: "Cancelled", invalidated: "Invalidated" };
const dateLabel = (value: string) => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "Time unavailable" : date.toLocaleString(); };

function errorKind(error: unknown): "unauthorized" | "unavailable" | "conflict" | "expired" | "error" {
  if (typeof error === "object" && error !== null && "kind" in error) {
    const kind = error.kind;
    if (kind === "unauthorized" || kind === "unavailable" || kind === "conflict" || kind === "expired") return kind;
  }
  return "error";
}

function Status({ status }: { status: ApprovalStatus }) {
  return <span className="inline-flex rounded-full border border-border px-2 py-0.5 text-xs font-medium" data-status={status}>{STATUS_LABEL[status]}</span>;
}

function ApprovalCard({ item, selected, onSelect }: { item: ApprovalDetail | ApprovalHistoryItem; selected: boolean; onSelect: () => void }) {
  return <button type="button" aria-pressed={selected} onClick={onSelect} className="w-full rounded-lg border border-border bg-card p-4 text-left text-card-foreground hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
    <div className="flex flex-wrap items-center justify-between gap-2"><strong>{item.toolName}</strong><Status status={item.status} /></div>
    <p className="my-2 text-sm">{item.requestedAction}</p>
    <p className="m-0 text-sm text-muted-foreground">{item.safeSummary}</p>
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span>Requested {dateLabel(item.requestedAt)}</span>
      {item.status === "pending" && <span>Expires {dateLabel(item.expiresAt)}</span>}
      {item.workspaceLabel && <span>Workspace: {item.workspaceLabel}</span>}
      {item.run && <span>Run: {item.run.label ?? item.run.id}</span>}
      {item.conversation && <span>Conversation: {item.conversation.label ?? item.conversation.id}</span>}
      {"decisionAt" in item && item.decisionAt && <span>Resolved {dateLabel(item.decisionAt)}</span>}
    </div>
  </button>;
}

function Detail({ item, now, onDecision }: { item: ApprovalDetail | ApprovalHistoryItem; now: number; onDecision?: (decision: ApprovalDecision) => void }) {
  const pending = item.status === "pending";
  const expiresAt = Date.parse(item.expiresAt);
  const expiredLocally = pending && (!Number.isFinite(expiresAt) || expiresAt <= now);
  const actionable = pending && !expiredLocally && item.decisionAvailability === "available" && onDecision != null;
  return <section aria-label="Approval details" className="rounded-lg border border-border bg-card p-5 text-card-foreground">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="m-0 text-lg">Approval details</h2><Status status={item.status} /></div>
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
      <div><dt className="font-medium">Approval ID</dt><dd className="m-0 break-all text-muted-foreground">{item.approvalId}</dd></div>
      <div><dt className="font-medium">Tool and invocation</dt><dd className="m-0 text-muted-foreground">{item.toolName} · {item.invocationLabel}</dd></div>
      <div className="sm:col-span-2"><dt className="font-medium">Operation summary</dt><dd className="m-0 text-muted-foreground">{item.safeSummary}</dd></div>
      <div className="sm:col-span-2"><dt className="font-medium">Target or resource</dt><dd className="m-0 text-muted-foreground">{item.targetDescription}</dd></div>
      <div><dt className="font-medium">Requested action</dt><dd className="m-0 text-muted-foreground">{item.requestedAction}</dd></div>
      <div><dt className="font-medium">Risk classification</dt><dd className="m-0 capitalize text-muted-foreground">{item.risk}</dd></div>
      <div><dt className="font-medium">Approval reason</dt><dd className="m-0 text-muted-foreground">{item.reason}</dd></div>
      <div><dt className="font-medium">Expires</dt><dd className="m-0 text-muted-foreground">{dateLabel(item.expiresAt)}</dd></div>
      {item.workspaceLabel && <div><dt className="font-medium">Workspace</dt><dd className="m-0 text-muted-foreground">{item.workspaceLabel}</dd></div>}
      {item.run && <div><dt className="font-medium">Associated run</dt><dd className="m-0 text-muted-foreground">{item.run.label ?? item.run.id}</dd></div>}
      {item.conversation && <div><dt className="font-medium">Conversation</dt><dd className="m-0 text-muted-foreground">{item.conversation.label ?? item.conversation.id}</dd></div>}
      <div className="sm:col-span-2"><dt className="font-medium">Requested capabilities</dt><dd className="m-0 text-muted-foreground">{item.requestedCapabilities.length ? item.requestedCapabilities.join(", ") : "None disclosed"}</dd></div>
    </dl>
    {item.policyWarnings.length > 0 && <div role="note" className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"><strong>Policy warnings</strong><ul className="mb-0 mt-1">{item.policyWarnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></div>}
    {"decisionLabel" in item && item.decisionLabel && <p className="text-sm text-muted-foreground">Decision by {item.decisionLabel}</p>}
    {pending && expiredLocally && <p role="status" className="text-sm text-muted-foreground">This request has expired and is no longer actionable. The backend will confirm its terminal status.</p>}
    {pending && !expiredLocally && !actionable && <p className="text-sm text-muted-foreground">{item.decisionAvailability === "not_authorized" ? "You are not authorized to decide this request." : "Decision service is unavailable. This request is read-only."}</p>}
    {pending && <div className="mt-5 flex flex-wrap gap-2"><button type="button" disabled={!actionable} onClick={() => onDecision?.("approve")} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">Approve</button><button type="button" disabled={!actionable} onClick={() => onDecision?.("deny")} className="rounded-md border border-border px-4 py-2 text-sm font-medium enabled:hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50">Deny</button></div>}
  </section>;
}

export function ApprovalsWorkspace({ dataSource }: ApprovalsWorkspaceProps) {
  const [state, setState] = useState<LoadState>(() => dataSource == null ? { status: "unavailable" } : { status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"pending" | "history">("pending");
  const [pendingDecision, setPendingDecision] = useState<{ item: ApprovalDetail; decision: ApprovalDecision } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const generation = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    const current = ++generation.current;
    let cancelled = false;
    inFlight.current = false;
    setSubmitting(false);
    setPendingDecision(null);
    if (dataSource == null) { setState({ status: "unavailable" }); return () => { cancelled = true; }; }
    setState({ status: "loading" });
    void dataSource.load().then((snapshot) => {
      if (cancelled || generation.current !== current) return;
      setState({ status: "ready", snapshot });
      setSelectedId((previous) => previous ?? snapshot.pending[0]?.approvalId ?? snapshot.history[0]?.approvalId ?? null);
    }).catch((error: unknown) => {
      if (cancelled || generation.current !== current) return;
      const kind = errorKind(error);
      setState(kind === "unauthorized" ? { status: "unauthorized" } : kind === "unavailable" ? { status: "unavailable" } : { status: "error" });
    });
    return () => { cancelled = true; };
  }, [dataSource, attempt]);

  useEffect(() => {
    if (state.status !== "ready") return;
    const expirations = state.snapshot.pending.map((item) => Date.parse(item.expiresAt)).filter(Number.isFinite);
    if (expirations.length === 0) return;
    const nextExpiration = Math.min(...expirations);
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, nextExpiration - Date.now()));
    return () => window.clearTimeout(timer);
  }, [state]);

  const items = state.status === "ready" ? view === "pending" ? state.snapshot.pending : state.snapshot.history : [];
  const selected = items.find((item) => item.approvalId === selectedId) ?? items[0] ?? null;
  const doDecision = async () => {
    if (dataSource == null || pendingDecision == null || inFlight.current || pendingDecision.item.decisionAvailability !== "available") return;
    const currentGeneration = generation.current;
    inFlight.current = true; setSubmitting(true); setActionMessage(null);
    try {
      const result = await dataSource.decide(pendingDecision.item.approvalId, pendingDecision.decision);
      const expected: ApprovalStatus = pendingDecision.decision === "approve" ? "approved" : "denied";
      if (result.approvalId !== pendingDecision.item.approvalId || result.status !== expected) throw new Error("Decision was not confirmed");
      if (generation.current !== currentGeneration) return;
      setState((previous) => previous.status !== "ready" ? previous : { status: "ready", snapshot: {
        pending: previous.snapshot.pending.filter((item) => item.approvalId !== result.approvalId),
        history: [result, ...previous.snapshot.history.filter((item) => item.approvalId !== result.approvalId)],
      } });
      setView("history"); setSelectedId(result.approvalId);
      setActionMessage(result.status === "denied" ? "Approval was denied by the backend." : "Approval was confirmed by the backend.");
      setPendingDecision(null);
      try {
        const refreshed = await dataSource.load();
        if (generation.current === currentGeneration) setState({ status: "ready", snapshot: {
          pending: refreshed.pending.filter((item) => item.approvalId !== result.approvalId),
          history: [result, ...refreshed.history.filter((item) => item.approvalId !== result.approvalId)],
        } });
      } catch { /* The confirmed decision remains visible from the backend response. */ }
    } catch (error) {
      if (generation.current !== currentGeneration) return;
      const kind = errorKind(error);
      setActionMessage(kind === "expired" ? "This approval has expired and can no longer be decided." : kind === "conflict" ? "The backend reports that this approval changed. The queue was refreshed without recording success." : "The backend did not confirm this decision. No success was recorded.");
      try {
        const refreshed = await dataSource.load();
        setState({ status: "ready", snapshot: refreshed });
      } catch { /* Keep the current non-success state when refresh also fails. */ }
    } finally { inFlight.current = false; setSubmitting(false); }
  };

  const requestDecision = (decision: ApprovalDecision) => {
    const expiresAt = selected == null ? Number.NaN : Date.parse(selected.expiresAt);
    if (selected == null || selected.status !== "pending" || selected.decisionAvailability !== "available" || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) return;
    setPendingDecision({ item: selected, decision });
  };

  return <main className="flex min-h-0 flex-1 flex-col overflow-auto bg-background p-4 text-foreground sm:p-6" aria-label="Approvals">
    <header className="mx-auto w-full max-w-6xl"><h1 className="text-2xl font-semibold">Approvals</h1><p className="mt-1 text-sm text-muted-foreground">Review human approval requests for normalized tool operations.</p></header>
    <div className="mx-auto mt-5 flex w-full max-w-6xl gap-2" role="tablist" aria-label="Approval views">
      <button role="tab" aria-selected={view === "pending"} onClick={() => setView("pending")} className="rounded-md border border-border px-4 py-2 text-sm aria-selected:bg-secondary">Pending approvals</button>
      <button role="tab" aria-selected={view === "history"} onClick={() => setView("history")} className="rounded-md border border-border px-4 py-2 text-sm aria-selected:bg-secondary">Approval history</button>
    </div>
    {state.status === "loading" && <p role="status" className="mx-auto mt-8 w-full max-w-6xl text-sm text-muted-foreground">Loading approvals…</p>}
    {state.status === "unavailable" && <section className="mx-auto mt-8 w-full max-w-6xl rounded-lg border border-border p-5" aria-live="polite"><h2 className="m-0 text-lg">Approval service unavailable</h2><p className="mb-0 mt-2 text-sm text-muted-foreground">This AVA installation does not yet provide an authorized approval API. The view is read-only and no approval records are stored in the browser.</p></section>}
    {(state.status === "error" || state.status === "unauthorized") && <div className="mx-auto mt-8 w-full max-w-6xl text-sm">{state.status === "unauthorized" ? <p role="alert">You are not authorized to view these approvals.</p> : <p role="alert">Approval data could not be loaded.</p>}<button type="button" onClick={() => setAttempt((value) => value + 1)} className="mt-2 rounded-md border border-border px-3 py-1.5 hover:bg-muted">Retry loading approvals</button></div>}
    {state.status === "ready" && items.length === 0 && <p className="mx-auto mt-8 w-full max-w-6xl rounded-lg border border-border p-6 text-sm text-muted-foreground">{view === "pending" ? "There are no pending approvals." : "There is no approval history."}</p>}
    {state.status === "ready" && items.length > 0 && <div className="mx-auto mt-5 grid w-full max-w-6xl gap-4 lg:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.2fr)]">
      <section aria-label={view === "pending" ? "Pending approvals" : "Approval history"} className="grid content-start gap-3">{items.map((item) => <ApprovalCard key={item.approvalId} item={item} selected={selected?.approvalId === item.approvalId} onSelect={() => setSelectedId(item.approvalId)} />)}</section>
      {selected && <Detail item={selected} now={now} onDecision={view === "pending" ? requestDecision : undefined} />}
    </div>}
    {actionMessage && <p role="status" className="mx-auto mt-4 w-full max-w-6xl text-sm">{actionMessage}</p>}
    <Modal open={pendingDecision != null} title={pendingDecision?.decision === "approve" ? "Confirm approval" : "Confirm denial"} onClose={() => { if (!submitting) setPendingDecision(null); }} secondaryAction="Cancel" onSecondaryAction={() => setPendingDecision(null)} primaryAction={pendingDecision?.decision === "approve" ? "Confirm approval" : "Confirm denial"} onPrimaryAction={() => void doDecision()} primaryBusy={submitting} primaryDisabled={submitting} closeOnOverlayClick={!submitting}>
      {pendingDecision && <div className="space-y-3 text-sm"><p>You are about to {pendingDecision.decision} this operation:</p><p className="rounded-md border border-border p-3">{pendingDecision.item.toolName}: {pendingDecision.item.safeSummary}</p><p>This decision does not start tool execution. The backend must confirm the decision before it is shown as resolved.</p></div>}
    </Modal>
  </main>;
}
