/** Transcript derivation helpers.
 *
 * The backend message store is append-only: regenerating a turn persists the
 * NEW assistant response as an additional row, so a conversation can contain
 * several assistant rows for one user turn (A1, A2, …). These helpers derive
 * the *normal transcript* from that history by stable identity/order only —
 * never by comparing message text.
 */

import type { ConversationMessage } from "../types";

/**
 * Normal transcript selection. For each user turn (a user message followed by
 * one or more assistant responses), only the LAST assistant response in that
 * run is rendered as the active one; earlier regenerated responses are
 * superseded and hidden from the normal conversation transcript.
 *
 * Collapsing uses the assistant's source user-message identity. A regenerated
 * response is appended to durable history after later turns may already exist,
 * so adjacency alone would replace the latest assistant rather than the
 * assistant response that owns the regenerated turn. User and system messages
 * are never hidden or reordered.
 */
export function selectTranscriptMessages(
  messages: ConversationMessage[],
): ConversationMessage[] {
  const active: ConversationMessage[] = [];
  for (const message of messages) {
    if (message.role === "assistant" && message.sourceUserMessageId != null) {
      let priorIndex = -1;
      for (let index = active.length - 1; index >= 0; index -= 1) {
        const candidate = active[index];
        if (
          candidate.role === "assistant" &&
          candidate.sourceUserMessageId === message.sourceUserMessageId
        ) {
          priorIndex = index;
          break;
        }
      }
      if (priorIndex >= 0) {
        active[priorIndex] = message;
        continue;
      }
    }
    if (
      message.role === "assistant" &&
      active.length > 0 &&
      active[active.length - 1].role === "assistant"
    ) {
      active[active.length - 1] = message;
      continue;
    }
    active.push(message);
  }
  return active;
}

/**
 * Backfill the ``sourceUserMessageId`` association for assistant messages
 * that hydrated without it (the field is frontend-owned and not persisted on
 * the message row). An assistant message's originating user message is the
 * nearest PRECEDING user message — deterministic from server append order
 * (the identity AVA relies on when a run reuses "the original user message"),
 * not from text or from assuming the previous array element.
 *
 * Returns the same array when every assistant message is already associated;
 * otherwise a new array with the missing associations filled in.
 */
export function associateAssistantMessages(
  messages: ConversationMessage[],
): ConversationMessage[] {
  let lastUserMessageId: string | null = null;
  let changed = false;
  const associated = messages.map((message) => {
    if (message.role === "user") {
      lastUserMessageId = message.id;
      return message;
    }
    if (message.role !== "assistant") return message;
    if (message.sourceUserMessageId != null) return message;
    if (lastUserMessageId != null) {
      changed = true;
      return { ...message, sourceUserMessageId: lastUserMessageId };
    }
    return message;
  });
  return changed ? associated : messages;
}
