# Phase 5.48 — Conversation Delete UI and Post-Delete Navigation

## Scope

Phase 5.48 adds permanent deletion to the existing conversation overflow menu.
It uses the typed `deleteConversation(client, conversationId)` API-client
method and the shared `@ava/ui-core` `Modal`. No backend production code,
archive behavior, filtering, folders, search, sorting, or Projects changed.

## User behavior

The existing conversation action menu now offers **Delete** alongside
**Rename**. Selecting Delete opens a confirmation named for the conversation:

> Delete “{conversation title}” permanently?

The dialog explains that the conversation and its messages will be removed from
AVA and that deletion cannot be undone. **Cancel** or Escape closes the dialog
without a request. The shared modal provides focus trapping and restoration;
its destructive submit is disabled while a request is in flight, and repeated
submits are guarded in the handler.

Only confirmed deletion calls the API. On success, the local conversation entry
and its embedded transcript/run projection are removed. Deleting an unselected
conversation leaves the current selection and transcript untouched. Deleting
the selected conversation chooses the next item at the deleted position in the
existing order, or the previous last item if there was no next item. Deleting
the final conversation clears selection and shows the existing empty
conversation state.

## Failure reconciliation

- `409 conversation_run_active`: keep the conversation, selection, and dialog;
  explain that the active response must be stopped before deletion.
- `404 conversation_not_found`: treat the durable record as already absent,
  remove the stale local item, and choose a safe selection using the same
  ordering rule as a successful delete.
- Other failures: keep local state and selection unchanged, retain the dialog,
  and show a generic safe error without exposing transport text.

## Client-side cleanup

The conversation reducer removes the complete conversation projection, so its
messages and run state cannot reappear on navigation. The provider invalidates
message hydration outstanding for a deleted selected conversation. After the
provider accepts success or a 404 reconciliation, the workspace aborts only
that conversation's owned stream observer and removes its recovery key. Other
conversation observers are unaffected. The backend continues to reject
deletion during an active run.

Archive remains reversible and distinct from permanent Delete. No other
conversation organization behavior changed in this step.
