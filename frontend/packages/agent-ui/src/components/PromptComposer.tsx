import { ArrowUpIcon, ChevronDownIcon, PaperclipIcon, SquareIcon, XIcon, shadcn } from "@ava/ui-core";
import type { AttachmentResponse, AttachmentContextItem, ExecutionMode } from "@ava/contracts";
import { attachmentContextPresentation } from "../lib/attachmentContextPresentation";
import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";

import { presentAvaError } from "../lib/errorPresentation";
import {
  enterShouldSubmit,
  isMeaningfulPrompt,
  rowsForPrompt,
} from "../lib/prompt";

export interface PromptComposerProps {
  /**
   * Controlled value. When provided, the composer is fully controlled: the
   * parent owns the text and is expected to clear it after a successful
   * submit. When omitted, the composer manages its own draft text and clears
   * it after a successful submit.
   */
  value?: string;
  /** Called on every edit in both controlled and self-managed modes. */
  onChange?: (value: string) => void;
  /** Called with the trimmed prompt once meaningful content is submitted. */
  onSubmit: (prompt: string, executionMode: ExecutionMode) => void | Promise<void>;
  /** Called when the user activates the Stop action while running. */
  onStop: () => void;
  /** True while a run is active with a backend run id (Stop is enabled). */
  isRunning?: boolean;
  /** True while the run id is still being created (Send and Stop disabled). */
  isStarting?: boolean;
  /** True while a cancellation request is in flight (Stop disabled). */
  isStopping?: boolean;
  /** Disables editing and all actions. */
  disabled?: boolean;
  placeholder?: string;
  minRows?: number;
  maxRows?: number;
  controls?: ReactNode;
  /** Human-readable execution choice shown while the settings are closed. */
  executionSummary?: string;
  /** Transient mode for the next Run; the persisted Run remains authoritative. */
  executionMode?: ExecutionMode;
  onExecutionModeChange?: (mode: ExecutionMode) => void;
  /** Conservative capability feedback for Plan and Agent modes. */
  executionModeStatus?: ReactNode;
  /** Context window estimate for the current unsent draft. */
  contextWindowStatus?: ReactNode;
  /** Active conversation id, used to bind a file picker selection to its original owner. */
  conversationId?: string | null;
  /** Conversation-owned attachments and actions. Omit upload to hide the control for a new conversation. */
  attachments?: AttachmentResponse[];
  attachmentContext?: AttachmentContextItem[];
  attachmentContextLoading?: boolean;
  attachmentsLoading?: boolean;
  attachmentsLoadError?: string | null;
  onUploadAttachment?: (file: File, conversationId: string | null) => Promise<void>;
  onRemoveAttachment?: (attachmentId: string, conversationId: string | null) => Promise<void>;
}

export function PromptComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  isRunning = false,
  isStarting = false,
  isStopping = false,
  disabled = false,
  placeholder,
  minRows = 1,
  maxRows = 6,
  controls,
  executionSummary = "Execution settings",
  executionMode = "chat",
  onExecutionModeChange,
  executionModeStatus,
  contextWindowStatus,
  conversationId = null,
  attachments = [],
  attachmentContext = [],
  attachmentContextLoading = false,
  attachmentsLoading = false,
  attachmentsLoadError = null,
  onUploadAttachment,
  onRemoveAttachment,
}: PromptComposerProps) {
  const [draft, setDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [uploadingConversationId, setUploadingConversationId] = useState<string | null>(null);
  const [removingAttachmentId, setRemovingAttachmentId] = useState<string | null>(null);
  const draftRef = useRef("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const filePickerConversationId = useRef<string | null>(null);
  const currentConversationId = useRef(conversationId);
  const submissionPending = useRef(false);
  currentConversationId.current = conversationId;

  const controlled = value !== undefined;
  const text = controlled ? value : draft;
  const uploadingAttachments = conversationId != null && uploadingConversationId === conversationId;

  useEffect(() => {
    setAttachmentError(null);
  }, [conversationId]);

  const update = (next: string) => {
    draftRef.current = next;
    if (!controlled) {
      setDraft(next);
    }
    onChange?.(next);
  };

  const reportSubmissionFailure = (error: unknown) => {
    setSubmissionError(presentAvaError(
      error,
      "Unable to start this run. Check the selected runtime and model configuration, then try again.",
    ));
    // A user may have started editing while an async submit was pending. Only
    // restore the submitted prompt when the draft is still empty.
    if (draftRef.current === "") update(text);
  };

  const inFlight = isRunning || isStarting || isStopping;

  // The shared submit callback resolves after streaming completes. Once the
  // parent reports a starting/running phase, the in-flight props own the lock;
  // release the local synchronous guard so switching conversations can submit
  // independently while the original Run continues in the background.
  useEffect(() => {
    if (inFlight) submissionPending.current = false;
  }, [inFlight]);

  const handleSubmit = () => {
    if (disabled || inFlight || submissionPending.current) return;
    if (!isMeaningfulPrompt(text)) return;
    const prompt = text.trim();
    setSubmissionError(null);
    submissionPending.current = true;
    let outcome: void | Promise<void>;
    try {
      outcome = onSubmit(prompt, executionMode);
    } catch (error) {
      submissionPending.current = false;
      reportSubmissionFailure(error);
      return;
    }
    void Promise.resolve(outcome)
      .catch(reportSubmissionFailure)
      .finally(() => { submissionPending.current = false; });
    update("");
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (
      enterShouldSubmit({
        key: event.key,
        shiftKey: event.shiftKey,
        isComposing: event.nativeEvent.isComposing,
      })
    ) {
      event.preventDefault();
      handleSubmit();
    }
  };

  const rows = rowsForPrompt(text, minRows, maxRows);
  const canSend = !disabled && !inFlight && isMeaningfulPrompt(text);

  const handleFilesSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    if (!onUploadAttachment || files.length === 0) return;
    const uploadConversationId = filePickerConversationId.current;
    filePickerConversationId.current = null;
    if (!uploadConversationId) return;
    setAttachmentError(null);
    setUploadingConversationId(uploadConversationId);
    try {
      for (const file of files) await onUploadAttachment(file, uploadConversationId);
    } catch (error) {
      if (currentConversationId.current === uploadConversationId) {
        setAttachmentError(presentAvaError(error, "Unable to upload this file. Please try again."));
      }
    } finally {
      setUploadingConversationId((current) => current === uploadConversationId ? null : current);
    }
  };

  const handleRemoveAttachment = async (attachmentId: string) => {
    if (!onRemoveAttachment) return;
    setAttachmentError(null);
    setRemovingAttachmentId(attachmentId);
    try {
      await onRemoveAttachment(attachmentId, conversationId);
    } catch (error) {
      if (currentConversationId.current === conversationId) {
        setAttachmentError(presentAvaError(error, "Unable to remove this file. Please try again."));
      }
    } finally {
      setRemovingAttachmentId(null);
    }
  };

  return (
    <div
      className={`group relative box-border w-full rounded-3xl border border-border text-card-foreground shadow-sm transition-[border-color,box-shadow,background-color] duration-150 focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/20 ${disabled ? "bg-muted" : "bg-card"}`}
      data-prompt-composer=""
    >
      {onUploadAttachment ? (
        <div className="px-3 pt-3 sm:px-4" data-conversation-attachments="">
          {attachmentsLoading ? <p role="status" className="mb-2 text-xs text-muted-foreground">Loading attachments…</p> : null}
          {attachmentsLoadError ? <p role="alert" className="mb-2 text-xs text-destructive">{attachmentsLoadError}</p> : null}
          {attachments.length > 0 ? (
            <>
            <ul aria-label="Conversation attachments" className="mb-2 flex flex-wrap gap-2 p-0">
              {attachments.map((attachment) => {
                const status = attachmentContextPresentation(attachmentContext.find(item => item.attachment_id === attachment.attachment_id));
                return (
                <li key={attachment.attachment_id} className="flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-1 text-xs">
                  <span className="max-w-56 truncate" title={attachment.file_name}>{attachment.file_name}</span>
                  <span className="shrink-0 text-muted-foreground">{formatAttachmentSize(attachment.size_bytes)}</span>
                  <shadcn.TooltipProvider><shadcn.Tooltip><shadcn.TooltipTrigger asChild>
                    <span tabIndex={0} className="max-w-44 truncate text-muted-foreground" aria-label={`${attachment.file_name}: ${attachmentContextLoading ? "Checking context…" : status.label}`}>
                      {attachmentContextLoading ? "Checking…" : status.label}
                    </span>
                  </shadcn.TooltipTrigger><shadcn.TooltipContent className="max-w-72">{status.detail}</shadcn.TooltipContent></shadcn.Tooltip></shadcn.TooltipProvider>
                  {onRemoveAttachment ? (
                    <button type="button" aria-label={`Remove ${attachment.file_name}`} title={`Remove ${attachment.file_name}`} disabled={removingAttachmentId != null || uploadingAttachments} onClick={() => void handleRemoveAttachment(attachment.attachment_id)} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline focus-visible:outline-2 disabled:opacity-50">
                      <XIcon aria-hidden="true" className="size-3.5" />
                    </button>
                  ) : null}
                </li>
              ); })}
            </ul>
            <p className="mb-2 text-[11px] text-muted-foreground">Supported text files are included when they fit the model context. Run metadata records file inclusion.</p>
            {attachmentContext.filter(item => !item.included).map(item => <p key={item.attachment_id} role="status" className="mb-1 text-[11px] text-muted-foreground">{item.file_name}: {attachmentContextPresentation(item).detail}</p>)}
            </>
          ) : null}
          {attachmentError ? <p role="alert" className="mb-2 text-xs text-destructive">{attachmentError}</p> : null}
          <input ref={fileInputRef} type="file" multiple className="sr-only" aria-label="Choose files to attach" onChange={(event) => void handleFilesSelected(event)} />
        </div>
      ) : null}
      <shadcn.Textarea
        value={text}
        onChange={(event) => {
          setSubmissionError(null);
          update(event.currentTarget.value);
        }}
        onKeyDown={handleKeyDown}
        rows={rows}
        placeholder={placeholder}
        disabled={disabled}
        aria-label="Message"
        className="min-h-12 w-full resize-none border-0 bg-transparent px-5 pb-2 pt-4 text-base leading-relaxed text-foreground shadow-none placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 disabled:cursor-not-allowed sm:px-6"
      />

      {contextWindowStatus != null ? (
        <div data-composer-context-window="" className="px-4 pb-2 text-xs text-muted-foreground sm:px-5">
          {contextWindowStatus}
        </div>
      ) : null}

      {submissionError != null ? (
        <div
          role="alert"
          data-composer-submit-error=""
          className="mx-4 mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {submissionError}
        </div>
      ) : null}

      {executionModeStatus != null && executionMode !== "chat" ? (
        <div
          id="execution-mode-status"
          data-execution-mode-status=""
          role="status"
          aria-live="polite"
          className="px-4 pb-2 text-[11px] leading-snug text-muted-foreground sm:px-5"
        >
          {executionModeStatus}
        </div>
      ) : null}

      <div className="flex min-h-12 items-center justify-between gap-3 px-3 pb-2 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <label className="sr-only" htmlFor="prompt-execution-mode">Execution mode</label>
          <select
            id="prompt-execution-mode"
            aria-label="Execution mode"
            aria-describedby={executionModeStatus != null && executionMode !== "chat" ? "execution-mode-description execution-mode-status" : "execution-mode-description"}
            title={executionModeDescription(executionMode)}
            value={executionMode}
            disabled={disabled}
            onChange={(event) => onExecutionModeChange?.(event.currentTarget.value as ExecutionMode)}
            className="h-8 w-[5.5rem] shrink-0 rounded-md border border-input bg-background px-2 text-xs font-medium text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 [color-scheme:inherit]"
          >
            <option value="chat">Chat</option>
            <option value="plan">Plan</option>
            <option value="agent">Agent</option>
          </select>
          <span id="execution-mode-description" className="sr-only">
            Chat does not request agent tools. Plan is read-only and still requires authorization. Agent tool requests remain subject to policy, Workspace permissions, and approval.
          </span>
          {onUploadAttachment ? (
            <>
              <shadcn.IconButton icon={PaperclipIcon} label="Attach files" tooltip={uploadingAttachments ? "Uploading attachments…" : "Attach files to this conversation"} variant="ghost" shape="circle" disabled={disabled || uploadingAttachments || attachmentsLoading} onClick={() => { filePickerConversationId.current = conversationId; fileInputRef.current?.click(); }} />
              {uploadingAttachments ? <span role="status" className="shrink-0 text-xs text-muted-foreground">Uploading…</span> : null}
            </>
          ) : null}
          {isStarting || isStopping ? (
            <span
              data-composer-status=""
              role="status"
              className="shrink-0 text-xs text-muted-foreground"
            >
              {isStarting ? "Starting…" : "Stopping…"}
            </span>
          ) : null}
          {controls ? (
            <shadcn.Popover open={settingsOpen} onOpenChange={setSettingsOpen}>
              <shadcn.PopoverTrigger asChild>
              <shadcn.Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Execution settings: ${executionSummary}`}
                title={`Execution settings: ${executionSummary}`}
                disabled={disabled}
                className="max-w-full rounded-full bg-muted px-3 text-xs text-foreground hover:bg-accent hover:text-accent-foreground aria-expanded:bg-accent dark:bg-black dark:text-white dark:hover:bg-neutral-950 dark:hover:text-white dark:aria-expanded:bg-neutral-950"
              >
                <span className="truncate">{executionSummary}</span>
                <ChevronDownIcon aria-hidden="true" focusable="false" className="size-3.5 shrink-0" />
              </shadcn.Button>
              </shadcn.PopoverTrigger>
              <shadcn.PopoverContent
                aria-label="Execution settings"
                data-execution-settings-popover=""
                className="max-h-[min(70vh,32rem)] w-[min(32rem,calc(100vw-1.5rem))] overflow-y-auto p-4"
              >
                {controls}
              </shadcn.PopoverContent>
            </shadcn.Popover>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {inFlight ? (
            <shadcn.IconButton
              icon={SquareIcon}
              label="Stop"
              tooltip={
                isStarting
                  ? "Starting — Stop unavailable"
                  : isStopping
                    ? "Stopping…"
                    : "Stop responding"
              }
              variant="destructive"
              shape="circle"
              disabled={disabled || !isRunning}
              onClick={onStop}
            />
          ) : (
            <shadcn.IconButton
              icon={ArrowUpIcon}
              label="Send"
              tooltip={canSend ? "Send message" : "Type a message to send a prompt"}
              variant="default"
              shape="circle"
              disabled={!canSend}
              onClick={handleSubmit}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function formatAttachmentSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(0)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function executionModeDescription(mode: ExecutionMode): string {
  switch (mode) {
    case "plan": return "Plan: authorized read-only investigation and planning.";
    case "agent": return "Agent: tool requests remain subject to policy, Workspace permissions, and human approval.";
    default: return "Chat: normal conversation without agentic tools.";
  }
}
