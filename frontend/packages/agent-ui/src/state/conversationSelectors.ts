import type { Conversation } from "../types";

/** Return the canonical conversations available in active navigation. */
export function selectActiveConversations(conversations: Conversation[]): Conversation[] {
  return conversations.filter((conversation) => !conversation.isArchived);
}

/** Return the archived subset without changing its canonical order or records. */
export function selectArchivedConversations(conversations: Conversation[]): Conversation[] {
  return conversations.filter((conversation) => conversation.isArchived === true);
}
