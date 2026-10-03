# Phase 5.51 — Conversation Search UI

The conversation sidebar now has an accessible **Search conversations** field
above the existing list. It is owned by `ConversationProvider`, which keeps
the query temporary and separate from run state and transcript selection.

Nonblank queries are trimmed and debounced for 250 ms before the existing
typed `listConversations(client, { search })` API is called. Blank and
whitespace-only input immediately restores the normal unfiltered list. A clear
button and Escape both clear the query. Search results come from the backend;
the UI does not filter message content or duplicate title matching.

While a request is active, existing results remain visible and a small
“Searching…” status is shown. A successful empty response displays a
query-specific “No conversations found” message. A failed request displays
“Unable to search conversations.” and keeps the last safe list available for a
retry or clear.

Each search request uses a monotonically increasing generation. Only the
current generation may update the visible results, so an older response cannot
replace a newer query. Search results retain loaded transcript/run state for
matching conversations and include the returned pin, archive, and folder
metadata. Search changes only the sidebar list: it does not change selection,
remount the transcript, navigate when the selected item is hidden, or stop
background run observers. Selecting a result uses the existing conversation
selection path. Successful renames trigger a server refresh of the active
search; deletes remove the deleted item while retaining the query.

Archived conversations remain eligible, and pin state does not reorder
results. No sorting, folder UI, Projects, archive filtering, URL state, or
message full-text search was added.
