# Phase 5.53 — Conversation Folder Domain

## Folder boundary

A Conversation Folder is a flat, AVA-owned organizational grouping. **Folder is not Project.** It organizes conversations only; it does not define execution context, workspace, knowledge or instruction boundaries, model/runtime behavior, or file storage.

Folders have no parent relationship (`parent_folder_id` does not exist). Nested folders are out of scope unless a later product requirement establishes a need.

## Domain record and contracts

`ConversationFolderRecord` is the canonical backend snapshot:

```text
id: str
name: str
created_at: datetime
updated_at: datetime
```

`id` is an opaque, stable AVA-owned string. It follows the existing UUID4 convention for AVA-created resource IDs; the domain record does not generate identity. Timestamps are authoritative aware-UTC values. Creation will initialize `updated_at` to `created_at`; future rename/update behavior belongs to the write service and is not implemented here.

The public response mirrors those fields and includes AVA's `contract_version`. Create and update request contracts require a nonblank name. They reject empty and whitespace-only values but preserve surrounding whitespace; the future write service will normalize names consistently with conversation-title writes. Duplicate names are allowed because folder identity is its ID, not its display name.

## Conversation relationship

A conversation belongs to zero or one folder, represented only by the existing nullable `ConversationRecord.folder_id` and public `ConversationResponse.folder_id`. Conversation responses do not embed a folder object. Referential integrity is not enforced in this domain/contracts step.

Deleting a folder in a future step must not delete its conversations; the intended follow-up is to clear their `folder_id` values. No deletion behavior is implemented here.

## Scope boundary

This phase adds no storage or migration, repository, service, API route, conversation-folder assignment behavior, list ordering/grouping, search behavior, archive behavior, UI, drag/drop, or Python client model. The Python client currently mirrors workspace discovery and shared model/provider contracts, but has no conversation or organization-resource contract layer to extend.
