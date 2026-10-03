# Phase 5.50 — Conversation Search Backend and Typed Client

Phase 5.50 adds optional title search to the existing conversation list
endpoint and typed API client. `GET /conversations?search=...` performs a
case-insensitive substring match against conversation titles and returns the
existing `ConversationListResponse` shape in stable repository order. Missing,
empty, and whitespace-only terms retain the unfiltered list behavior.

The in-memory and SQLite repositories implement the filter; the service and
route pass the optional term through without changing response contracts.
SQLite escapes `LIKE` metacharacters so user terms are treated literally. The
typed client trims terms, omits blank queries, and encodes nonblank terms with
`URLSearchParams`.

Search deliberately covers conversation titles only. It includes archived and
pinned conversations, preserves their organization metadata, and does not
search message content or change ordering. No search UI, sorting, folder
behavior, Projects, or archive filtering was added.

Focused coverage verifies repository parity, case-insensitive substring
matching, stable order, blank and no-result terms, title-only behavior, metadata
preservation, rename/delete visibility, the unchanged response shape, and
client query encoding.

Mutation proof: temporarily removing search forwarding from the service caused
both provider-specific API search cases to fail (`2 failed`); restoring the
filter made the focused test suite pass again.
