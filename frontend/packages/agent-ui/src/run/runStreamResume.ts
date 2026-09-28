/**
 * One shared, same-session SSE resume loop.
 *
 * It owns only client observation state. Run lifecycle remains authoritative
 * on the backend; a disconnected transport never changes it.
 */

import type { RunEvent } from "@ava/contracts";
import { ApiError } from "@ava/api-client";

export interface ResumableRunStreamAgent {
  streamRun(
    runId: string,
    options: {
      signal?: AbortSignal;
      afterSequence?: number;
      onEvent(event: RunEvent): void | Promise<void>;
    },
  ): Promise<void>;
}

export interface RunStreamResumeOptions {
  agent: ResumableRunStreamAgent;
  runId: string;
  signal?: AbortSignal;
  /** Rejects stale/superseded observations before they mutate UI state. */
  isCurrent(): boolean;
  /** Applies one validated AVA event before the durable cursor advances. */
  applyEvent(event: RunEvent): Promise<void>;
  /** Returns true only after an authoritative snapshot reports terminal state. */
  reconcileSnapshot(): Promise<boolean>;
  /** UI-only degraded transport notification; never changes RunStatus. */
  onExhausted(error: unknown): void;
  /** Injectable for deterministic tests; production uses bounded short delays. */
  wait?(milliseconds: number): Promise<void>;
  retryDelaysMs?: readonly number[];
}

const DEFAULT_RETRY_DELAYS_MS = [0, 50, 150] as const;

function isTerminalEvent(event: RunEvent): boolean {
  return event.event_type === "run_completed"
    || event.event_type === "run_failed"
    || event.event_type === "run_cancelled";
}

function waitFor(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function isPermanentResumeError(error: unknown): boolean {
  return error instanceof ApiError
    && (error.status === 404 || error.status === 409 || error.status === 422);
}

/**
 * Observe a run from its last successfully applied persisted sequence.
 *
 * The cursor is exclusive and advances only after `applyEvent` resolves. A
 * gap or protocol conflict restarts the server-owned cursor stream from the
 * last contiguous sequence, which repairs observation without fabricating
 * client history.
 */
export async function observeRunWithResume(options: RunStreamResumeOptions): Promise<void> {
  const delays = options.retryDelaysMs ?? DEFAULT_RETRY_DELAYS_MS;
  const wait = options.wait ?? waitFor;
  const seenSequences = new Map<string, number>();
  let lastProcessedSequence = 0;
  let retries = 0;
  let lastError: unknown = new Error("Live updates disconnected.");

  while (!options.signal?.aborted && options.isCurrent()) {
    let terminal = false;
    let receivedEvent = false;
    // Some test adapters and lightweight callers invoke onEvent without
    // awaiting it. Serializing here still makes cursor advancement follow
    // successful application and preserves backend sequence order.
    let eventQueue: Promise<void> = Promise.resolve();
    let queuedFailure: unknown = null;
    try {
      await options.agent.streamRun(options.runId, {
        signal: options.signal,
        afterSequence: lastProcessedSequence,
        onEvent: (event) => {
          eventQueue = eventQueue.then(async () => {
          if (queuedFailure != null) return;
          if (options.signal?.aborted || !options.isCurrent()) return;
          const sequence = event.sequence;
          if (
            event.run_id !== options.runId
            || sequence == null
            || !Number.isInteger(sequence)
            || sequence < 1
          ) {
            throw new Error("Run stream contained an event outside its active run.");
          }
          const earlierSequence = seenSequences.get(event.event_id);
          if (earlierSequence != null) {
            if (earlierSequence === sequence) return;
            throw new Error("Run stream reused an event id at a different sequence.");
          }
          if (sequence <= lastProcessedSequence) {
            throw new Error("Run stream reused a sequence for a different event.");
          }
          if (sequence !== lastProcessedSequence + 1) {
            throw new Error("Run stream skipped a persisted sequence.");
          }
          await options.applyEvent(event);
          seenSequences.set(event.event_id, sequence);
          lastProcessedSequence = sequence;
          receivedEvent = true;
          terminal = isTerminalEvent(event);
          }).catch((error: unknown) => {
            // Keep a synchronous caller from creating an unhandled rejection;
            // the loop raises it after the adapter has finished this attempt.
            queuedFailure = error;
          });
          return eventQueue;
        },
      });
      await eventQueue;
      if (queuedFailure != null) throw queuedFailure;
      if (terminal || options.signal?.aborted || !options.isCurrent()) return;
    } catch (error) {
      if (options.signal?.aborted || !options.isCurrent()) return;
      if (isPermanentResumeError(error)) {
        // An ahead cursor is a client/protocol fault. Reconcile once before
        // reporting it so a terminal snapshot still wins over transport state.
        if (error instanceof ApiError && error.status === 409) {
          try {
            if (await options.reconcileSnapshot()) return;
          } catch {
            // The normalized cursor error remains the useful outcome.
          }
        }
        options.onExhausted(error);
        return;
      }
      lastError = error;
    }

    // EOF without a terminal event is only interrupted observation. Snapshot
    // reconciliation happens after cursor catch-up, so older snapshots never
    // roll back newer persisted message_content events.
    try {
      if (await options.reconcileSnapshot()) return;
    } catch (error) {
      lastError = error;
    }
    if (options.signal?.aborted || !options.isCurrent()) return;
    if (receivedEvent) retries = 0;
    if (retries >= delays.length) {
      options.onExhausted(lastError);
      return;
    }
    await wait(delays[retries]);
    retries += 1;
  }
}
