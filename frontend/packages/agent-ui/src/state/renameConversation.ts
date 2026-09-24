import { updateConversation, type ApiClient } from "@ava/api-client";
import type { Conversation } from "../types";
export function createRenameConversationCommand(options: { client: ApiClient; onSuccess: (conversation: Pick<Conversation, "id" | "title" | "createdAt"> & Partial<Conversation>) => void; onError: (error: unknown) => void }) {
  return async (id: string, title: string) => {
    try { const saved = await updateConversation(options.client, id, { title }); const conversation = { id: saved.conversation_id, title: saved.title, createdAt: saved.created_at }; options.onSuccess(conversation); return conversation; }
    catch (error) { options.onError(error); throw error; }
  };
}
