# Phase 5.47 — Public Conversation DELETE API

`DELETE /conversations/{conversation_id}` is the public transport for the
Phase 5.46 hard-delete service. The route delegates to
`ConversationService.delete_conversation`; it contains no cascade or storage
cleanup logic and accepts no request body.

A successful delete returns `204 No Content`. An unknown or already-deleted
conversation returns the standard `404 conversation_not_found` response. If an
active run prevents deletion, the route returns `409` with the existing
`conversation_run_active` validation error. The conversation and run remain
available after that refusal.

The operation permits deleting normal, archived, pinned, and folder-associated
conversations. Pin and archive remain reversible until explicit deletion.

The typed API client exports `deleteConversation(client, conversationId)` and
resolves `void` for a successful `204`. HTTP errors continue through the shared
`ApiError` path. No delete UI, confirmation flow, navigation behavior, or list
filtering was added; those remain for Phase 5.48.

## Validation

Before implementation, the focused Phase 5.42–5.46 backend integration set
passed **256 tests**. Conversation API-client tests passed **87 tests** and
contract tests passed **28 tests**. After implementation, the focused backend
suite, including Phase 5.47 route tests, passed **263 tests**; API-client tests
passed **90 tests** and contract tests passed **28 tests**.

A mutation check replaced the route behavior with a fake-success `204` that did
not call the service. All **7** route tests failed, including active-run
rejection and the success cases' follow-up GET checks. Restoring service
delegation returned the focused route suite to green.

Phase 5.48 is not started.
