# Phase 5.52 — Conversation Sorting

## Scope

This phase defines the single canonical order for conversation listings and title-search results. It adds no selectable sorting UI, archive filter, folder grouping, Projects behavior, or alternate ordering mode.

## Canonical order

All list surfaces use these keys in order:

1. `is_pinned DESC` — pinned conversations first.
2. `updated_at DESC` — most recently updated first within each pin group.
3. `created_at DESC` — newest creation first when update timestamps tie.
4. `conversation_id ASC` — stable deterministic order when all timestamps and pin state tie.

The in-memory repository uses stable sorting with the same keys. SQLite uses an explicit `ORDER BY` with the same keys. Search filters the conversation title population and retains this relative order. The service and API return repository order without re-sorting. The sidebar displays server order for the initial list, search results, and after create or rename refreshes.

Archive and folder metadata do not filter or group conversations. Archived and filed conversations remain in the same ordered list.

## Timestamp behavior

Creation initializes `created_at` and `updated_at` to the same current UTC timestamp. A successful rename refreshes `updated_at`. Pin and archive writes preserve both timestamps. Message creation does not currently change conversation `updated_at`; Phase 5.52 deliberately preserves that existing behavior rather than redefining “activity.”

## Validation

`backend/tests/test_conversation_sorting.py` uses fixed dates and metadata to prove exact order, equal-timestamp identity tie-breaking, memory/SQLite parity, filtered search order, API order, pin-group transitions, rename recency, and that messages do not refresh conversation activity. Existing list, organization, pin, archive, search, and delete tests were updated to assert the canonical contract.

Frontend tests verify the normal list and search results preserve server order and that creating a conversation reconciles to the server-returned order. Transcript state, active selection, and run state are maintained independently of list ordering.

## Status

Phase 5.52 — Conversation Sorting: complete.

Phase 5.53: not started.
