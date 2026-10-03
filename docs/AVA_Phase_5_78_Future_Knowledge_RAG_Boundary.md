# AVA Phase 5.78 — Future Knowledge/RAG Boundary

Phase 5.78 defines AVA-owned contracts for a future Project knowledge path. It does not implement ingestion, parsing, chunking, embeddings, vector indexing, retrieval behavior, background jobs, persistence, public APIs, UI, or execution integration. Project Files remain inert source resources.

## Resource and representation boundaries

```text
ProjectFileRecord (source metadata + content ownership)
    ↓ KnowledgeSourceRef
KnowledgeIngestionService                         [future orchestration]
    ↓ source abstraction / ProjectFileService / ProjectFileContentPort
Extractor / normalizer / chunker                  [future]
    ↓
EmbeddingProviderPort                             [future; port deferred]
    ↓
VectorIndexPort                                   [future; port deferred]
    ↓
KnowledgeRetrieverPort                            [defined; no implementation]
    ↓
Execution Context                                 [future; unchanged]
```

These remain separate concepts: `ProjectFile`, `KnowledgeSource`, `KnowledgeDocument`, `KnowledgeChunk`, `Embedding`, `VectorIndex`, `Retriever`, and execution-context injection. `ProjectFileRecord.id` is the canonical source identity. `project_file_source_ref()` maps it to `source_type="project_file"`, `scope_type="project"`, and the file's `project_id`; neither filename nor opaque content reference becomes a second source identity. Knowledge types reference Project Files in one direction; the Project File domain does not import Knowledge.

`KnowledgeSourceRef` is an immutable AVA-owned value with extensible string fields `source_type`, `source_id`, `scope_type`, and `scope_id`. Project Files are the only source type with a helper in this phase; the type does not prevent future attachment, document, web, SharePoint, repository, or database sources. No storage path is part of the reference.

`KnowledgeDocumentRecord` is a separate, minimal future representation containing only `id`, `source_ref`, `created_at`, and `updated_at`. It has no extracted text, parser, page, language, or persistence fields. No `KnowledgeChunkRecord` was added: current boundary contracts can preserve optional chunk provenance as a string `chunk_id` on a retrieval result without defining chunk storage prematurely.

## Ports and contracts

`KnowledgeIngestionPort` defines an abstract future `ingest(source_ref)` boundary. It has no implementation and performs no reading, extraction, normalization, chunking, embedding, indexing, or state recording. Future orchestration must read source content through an AVA source abstraction such as `ProjectFileService` / `ProjectFileContentPort`, never through a filesystem adapter or storage path.

`KnowledgeRetrieverPort` accepts `KnowledgeQuery` and returns provenance-bearing `KnowledgeRetrievalResult` values. A query contains query text, a tuple of explicit `KnowledgeScopeRef` values, and a provider-neutral positive result limit. An empty scope tuple is not global access. Results carry the source reference and knowledge document ID, with optional chunk ID and score. Score is opaque and provider-specific; AVA defines no distance, probability, or cross-provider comparison semantics. Provenance can support future source citations, but citation rendering is not implemented.

Dedicated `EmbeddingProviderPort` and `VectorIndexPort` contracts are deliberately deferred. Their future AVA-owned boundaries must remain independently swappable: an embedding provider may map text to vectors, and an index may upsert, delete by document, and search. No vectors, index records, indexing states, or vendor-facing types are defined here. `KnowledgeIngestionService` is also a future service concept, not a class or service implementation in Phase 5.78.

## Scope, authorization, and lifecycle invariants

All future Project File knowledge is scoped to its owning Project. A retrieval query must be constructed from current authorization and source ownership checks. A conversation linked to Project A may request Project A scope; a global conversation must not receive Project A knowledge implicitly. Project A knowledge must not leak into Project B. Knowledge availability does not widen tool/runtime permissions, and retrieval remains separate from Project access authorization.

Future lifecycle behavior must preserve these invariants:

- Deleting a Project File removes all future knowledge representations for that source.
- Deleting a Project removes its Project Files and all future Project knowledge.
- Replacing Project File content invalidates or rebuilds its knowledge representations.
- Repeating ingestion for the same source and same content version does not create duplicates.
- Content hash/revision identity needed to define that version remains unresolved; no version field was added to `ProjectFileRecord`.
- Indexing status remains a separate future concern and is not added to Project File metadata.

## Independence and deferred decisions

The contracts import only AVA-owned types and standard-library primitives. They do not import provider frameworks, model/runtime adapters, frontend, persistence, or filesystem adapters. Chat models and embedding models remain independently selectable; retrieval is independent of `native`, OpenHands, LangGraph, AWS AgentCore, and any other execution runtime. No knowledge is injected into prompts or execution in this phase.

No parser library, chunk strategy, embedding model/provider, vector database, retrieval ranking, hybrid search, reranker, query rewriting, or indexing job system was selected. These are future decisions for the future Knowledge/RAG phase (Phase 7 boundary), not work pulled into Phase 5. No TypeScript knowledge contract or Python client was added because no public knowledge API exists.

## Validation and scope result

Focused backend tests cover source/scope validation, extensible source type, canonical Project File ID mapping, minimal Knowledge Document identity, explicit query scope, retrieval provenance, abstract ports, provider/framework imports, and dependency direction. A mutation check verifies that reversing the Project File → Knowledge dependency fails the architecture guard.

No migration, repository adapter, table, background job, API route, frontend change, execution-context change, embedding implementation, vector database dependency, parser dependency, or retrieval behavior was added. Phase 5.78 defines the Knowledge/RAG boundary only; Knowledge/RAG implementation has not started. Phase 5.79 has not started.
