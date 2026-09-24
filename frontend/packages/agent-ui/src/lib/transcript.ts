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
 * Collapsing is positional and identity-based: an assistant message replaces
 * the previous assistant message when they belong to the same turn (they are
 * consecutive — regenerate reuses the original user message, so every
 * regeneration of a turn appends directly after that turn's user message).
 * User and system messages are never hidden or reordered.
 */
export function selectTranscriptMessages(
  messages: ConversationMessage[],
): ConversationMessage[] {
  const active: ConversationMessage[] = [];
  for (const message of messages) {
    if (
      message.role === "assistant" &&
      active.length > 0 &&
      active[active.length - 1].role === "assistant"
    ) {
      active[active.length - 1] = message;
    } else {
      active.push(message);
    }
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