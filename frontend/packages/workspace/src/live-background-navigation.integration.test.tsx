// @vitest-environment jsdom
/**
 * LIVE background conversation reconciliation after navigation.
 *
 * Real Web providers → real @ava/api-client → real HTTP → real backend run →
 * real local Ollama model. This file intentionally does NOT mock
 * @ava/api-client.
 *
 * It reproduces the reported defect end to end: start a long streaming response
 * in conversation A, navigate to B before A finishes, let A complete while
 * hidden, then return to A and require the final response to already be there.
 *
 * Opt-in: skipped unless AVA_LIVE_BACKEND_URL is set.
 */
import { ApiClient, createConversation } from "@ava/api-client";
import {
  AgentRunProvider,
  ConversationList,
  ConversationProvider,
  ConversationView,
  useAgentRun,
  useConversationState,
} from "@ava/agent-ui";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

const env =
  (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env ?? {};
const liveBackendUrl = env.AVA_LIVE_BACKEND_URL;

// jsdom's AbortController yields a jsdom AbortSignal that Node's fetch rejects.
// This is a test-sandbox artifact only; browsers are unaffected.
const nodeFetch: typeof fetch = (input, init) =>
  fetch(input, { ...init, signal: undefined });

function liveClient(baseUrl: string): ApiClient {
  return new ApiClient({ baseUrl, fetchImpl: nodeFetch });
}

const LONG_PROMPT =
  "Count slowly from 1 to 40. Put exactly one number on each line and add a short " +
  "comment on each line describing what you are doing. Do not stop early.";

function conversationItem(id: string): HTMLElement {
  const element = document.querySelector(`[data-conversation-item="${id}"]`);
  if (element == null) throw new Error(`Missing conversation item ${id}`);
  return element as HTMLElement;
}

function assistants(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll('[data-message-role="assistant"]'),
  ) as HTMLElement[];
}

/** Reads a conversation's cached projection even while it is not selected. */
function CacheProbe({ conversationId }: { conversationId: string }) {
  const conversation = useConversationState();
  const cached = conversation.state.conversations.find((item) => item.id === conversationId);
  const assistant = cached?.messages.find((message) => message.role === "assistant");
  return (
    <span
      data-testid="cache-probe"
      data-cache-content={assistant?.content ?? ""}
      data-cache-phase={cached?.run?.uiPhase ?? "idle"}
    />
  );
}

function Harness({ probeId }: { probeId: string }) {
  const conversation = useConversationState();
  const run = useAgentRun();
  return (
    <div>
      <button
        type="button"
        onClick={() => void run.submitPrompt(LONG_PROMPT)}
      >
        start-long-run
      </button>
      <CacheProbe conversationId={probeId} />
      <ConversationList
        conversations={conversation.conversations}
        activeConversationId={conversation.activeConversation?.id ?? null}
        onNewChat={() => void conversation.createConversation()}
        onSelect={(id) => void conversation.selectConversation(id)}
        onRename={conversation.renameConversation}
        error={conversation.state.error ?? null}
      />
      <ConversationView conversation={conversation.activeConversation} />
    </div>
  );
}

function probeContent(): string {
  return (
    document.querySelector('[data-testid="cache-probe"]')?.getAttribute("data-cache-content") ?? ""
  );
}

function probePhase(): string {
  return (
    document.querySelector('[data-testid="cache-probe"]')?.getAttribute("data-cache-phase") ?? ""
  );
}

describe.skipIf(!liveBackendUrl)("background conversation reconciliation (live)", () => {
  it(
    "keeps a hidden conversation current and shows the final response on return",
    async () => {
      const client = liveClient(liveBackendUrl as string);
      const a = await createConversation(client, { title: "Navigation A" });
      await createConversation(client, { title: "Navigation B" });

      render(
        <ConversationProvider client={client}>
          <AgentRunProvider client={client}>
            <Harness probeId={a.conversation_id} />
          </AgentRunProvider>
        </ConversationProvider>,
      );
      await waitFor(() => {
        expect(conversationItem(a.conversation_id)).toBeTruthy();
      });

      // Select A and start the long streaming response.
      fireEvent.click(conversationItem(a.conversation_id));
      await waitFor(() => {
        expect(conversationItem(a.conversation_id).getAttribute("aria-current")).toBe("true");
      });
      fireEvent.click(screen.getByRole("button", { name: "start-long-run" }));

      // Wait for real streamed partial content. The rendered bubble also holds
      // chrome (an inline spinner <style> plus action buttons), so content
      // identity is read from the cache probe and only *presence* in the
      // bubble is asserted from the DOM.
      await waitFor(
        () => {
          expect(probeContent().length).toBeGreaterThan(20);
        },
        { timeout: 120_000 },
      );
      const partialBeforeLeaving = probeContent();
      expect(
        (assistants()[0]?.textContent ?? "").includes(partialBeforeLeaving.slice(0, 20)),
      ).toBe(true);

      // Navigate to B while A is still streaming.
      const b = (
        await (await fetch(`${liveBackendUrl}/conversations`, {
          headers: { "content-type": "application/json" },
        })).json()
      ).conversations.find((item: { title: string }) => item.title === "Navigation B");
      fireEvent.click(conversationItem(b.conversation_id));
      await waitFor(() => {
        expect(conversationItem(b.conversation_id).getAttribute("aria-current")).toBe("true");
      });

      // A completes while hidden: its cache must advance without any fetch.
      await waitFor(
        () => {
          expect(probePhase()).toBe("completed");
        },
        { timeout: 180_000 },
      );
      const hiddenFinal = probeContent();
      // The hidden projection grew and stayed a prefix extension of what the
      // user last saw: same message identity, no restart, no truncation.
      expect(hiddenFinal.length).toBeGreaterThan(partialBeforeLeaving.length);
      expect(hiddenFinal.startsWith(partialBeforeLeaving)).toBe(true);

      // Return to A: the projection was already current before navigating, so
      // nothing needs to be fetched, refetched, or refreshed.
      fireEvent.click(conversationItem(a.conversation_id));
      expect(probeContent()).toBe(hiddenFinal);
      await waitFor(() => {
        expect(
          assistants().some((element) =>
            (element.textContent ?? "").includes(hiddenFinal.slice(0, 60)),
          ),
        ).toBe(true);
      });
      expect(assistants()).toHaveLength(1);
      expect(
        document.querySelector('[data-message-role="assistant"]')?.getAttribute("data-message-state"),
      ).toBe("complete");
    },
    300_000,
  );

  it(
    "shows the latest partial immediately when returning mid-stream",
    async () => {
      const client = liveClient(liveBackendUrl as string);
      const a = await createConversation(client, { title: "Partial A" });
      await createConversation(client, { title: "Partial B" });

      render(
        <ConversationProvider client={client}>
          <AgentRunProvider client={client}>
            <Harness probeId={a.conversation_id} />
          </AgentRunProvider>
        </ConversationProvider>,
      );
      await waitFor(() => {
        expect(conversationItem(a.conversation_id)).toBeTruthy();
      });
      fireEvent.click(conversationItem(a.conversation_id));
      await waitFor(() => {
        expect(conversationItem(a.conversation_id).getAttribute("aria-current")).toBe("true");
      });
      fireEvent.click(screen.getByRole("button", { name: "start-long-run" }));
      await waitFor(
        () => {
          expect(probeContent().length).toBeGreaterThan(20);
        },
        { timeout: 120_000 },
      );

      const b = (
        await (await fetch(`${liveBackendUrl}/conversations`, {
          headers: { "content-type": "application/json" },
        })).json()
      ).conversations.find((item: { title: string }) => item.title === "Partial B");
      fireEvent.click(conversationItem(b.conversation_id));
      await waitFor(() => {
        expect(conversationItem(b.conversation_id).getAttribute("aria-current")).toBe("true");
      });

      // Let the background observer accumulate a newer partial, then return.
      await waitFor(
        () => {
          expect(probeContent().length).toBeGreaterThan(40);
        },
        { timeout: 120_000 },
      );
      const hiddenPartial = probeContent();

      fireEvent.click(conversationItem(a.conversation_id));
      await waitFor(() => {
        expect(assistants()[0]?.textContent ?? "").toContain(hiddenPartial.slice(0, 40));
      });
      expect(assistants()).toHaveLength(1);
    },
    300_000,
  );
});