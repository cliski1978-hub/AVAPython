import { createMessage, type ApiClient } from "@ava/api-client";
import type { ConversationMessage } from "../types";

export function createPersistAssistantMessageCommand(options: {
  client: ApiClient;
  replaceMessage: (conversationId: string, placeholderId: string, message: ConversationMessage) => void;
}) {
  return async (conversationId: string, placeholderId: string, content: string, sourceUserMessageId?: string) => {
    const saved = await createMessage(options.client, conversationId, { role: "assistant", content });
    options.replaceMessage(conversationId, placeholderId, { id: saved.message_id, role: saved.role, status: saved.status, content: saved.content, createdAt: saved.created_at, sourceUserMessageId });
    return saved;
  };
}
