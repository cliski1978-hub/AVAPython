# Phase 5.49 — Conversation Rename UX Audit and Cleanup

## Existing rename path

The existing action surface is the overflow menu in
`frontend/packages/agent-ui/src/components/ConversationList.tsx`. Its inline
editor validates and trims the draft, Enter submits, and Escape cancels.
`createRenameConversationCommand` in
`frontend/packages/agent-ui/src/state/renameConversation.ts` calls the typed
`updateConversation` method from
`frontend/packages/api-client/src/conversations.ts` with a title-only PATCH.
`ConversationProvider` applies the returned title through the
`conversation:rename` reducer action; the reducer maps only the targeted item
and preserves its identity, transcript, run projection, and position.

The public route is `PATCH /conversations/{conversation_id}` in
`backend/src/ava/api/routes/conversations.py`, validated by
`UpdateConversationRequest` in `backend/src/ava/contracts/conversations.py`.
`ConversationService.update_title` trims and rejects blank titles, then calls
the repository's title-specific update. The in-memory store replaces only the
title and `updated_at`; the relational repository updates only those columns.
`created_at` is preserved. Existing `test_conversation_message_activation.py`
and `test_conversation_organization_persistence.py` verify restart durability.

## Audit findings and changes

The backend contract and persistence path were sound; no backend production
code changed. Two client UX/state gaps were found and fixed:

- A rename 404 previously displayed the generic rename error while retaining a
  conversation the server confirmed was absent. The provider now removes that
  stale local item, chooses a safe adjacent selection when needed, invalidates
  any pending message hydration for it, and the workspace clears its observer
  and recovery key.
- The editor previously closed as soon as a PATCH started, allowing the user to
  reopen it and issue another request before the first settled. It now remains
  open with its input disabled until the request completes, and an in-flight
  ref guards duplicate Enter submissions.

Generic rename failures retain the old authoritative title, current selection,
transcript, and run projection while showing AVA's safe error. The editor trims
submitted input; the backend independently trims and rejects `""` and
whitespace-only titles with 422. Escape cancels without a request. Rename and
Delete continue to use separate editor and confirmation state.

## Preserved semantics

Renaming the selected item changes its title without changing its selected id,
transcript, run state, or mounted view. Renaming an unselected item changes
only that list entry and does not affect the active conversation. Reducer
updates preserve list order. Background streaming continues when a hidden
conversation is renamed: its run remains active, its observer remains owned,
and subsequent content is still written to the originating conversation.

Backend regressions verify title-only updates preserve `is_pinned`,
`is_archived`, and `folder_id` in memory and relational repositories, preserve
conversation ordering, and survive repository/application restart. Existing
message, run, run-event, and attachment records are outside the title-only
update path. `updated_at` refreshes according to existing repository behavior;
no new timestamp policy was added.

No search, sorting, folder UI, Projects, archive filtering, or sidebar redesign
was introduced.

## Mutation proof

Temporarily changing the `conversation:rename` reducer case to return the prior
state caused all three focused selected, unselected, and background-streaming
rename integration tests to fail because the title never reconciled locally.
The reducer was restored and the full focused frontend checks passed.
