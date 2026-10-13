# AVA — MASTER CANONICAL DEVELOPMENT PLAN
## Current State to Product Completion

> [!CAUTION]
> **DO NOT CHANGE — OWNER-LOCKED MASTER PLAN**
>
> **Coding agents, subagents, and automated workflows MUST NOT edit, rewrite, renumber, replace, move, or delete this file without the project owner's explicit approval for the specific proposed change.**
>
> This document is the **single authoritative development roadmap** for AVA. Other files containing `canonical`, `roadmap`, `development plan`, or `phase plan` in their names are supporting historical, implementation, or architectural references—not competing forward roadmaps.
>
> An agent may read and cite this plan, maintain separate implementation documentation, or propose an amendment in a *separate* file. A proposed amendment does not take effect until the owner approves it and explicitly authorizes the edit. Do not interpret an ordinary implementation instruction, a phase handoff, or a tool-generated report as permission to modify this file.

**Plan status:** Proposed consolidated master — prepared for owner review and lock-in  
**Version:** 1.0-review  
**Prepared:** 2026-10-12  
**Current position:** Phase 5 implementation complete; validation exceptions tracked  
**Next phase:** Phase 6 — Normalized Tool and Approval Framework  
**Project root:** `/home/bizon/AvaUi`  
**Development principle:** Deliver verifiable end-user capability without sacrificing AVA-owned execution and security boundaries.

---

# 1. Authority and Change Control

1. **This file controls forward roadmap sequencing, scope, exit criteria, and product direction** after owner approval.
2. **Repository source code controls what is actually implemented.** Never present a roadmap's statement as proof that a runtime feature works; verify implementation and tests.
3. **Latest final implementation handoffs and test reports control milestone evidence**, including tracked gaps.
4. Architecture invariants in this file are binding; vendor SDKs and transient agent instructions cannot supersede them.
5. An older document's phase numbering is historical when it conflicts with this plan. Retain older documents for traceability; relabel them `HISTORICAL — NOT CURRENT ROADMAP` where practical, without silently deleting them.
6. If an agent discovers a conflict, **stop the conflicting work, report the discrepancy, and propose a separate amendment**; do not amend this file on its own initiative.
7. Owner-authorized amendments must record: date, exact changes, rationale, affected phase numbers, dependent documentation, and explicit approval. After approval, update the version and revision history.
8. This is a **procedural lock**, not a claim of filesystem immutability. Repository protection, permissions, and review rules should enforce it separately.

## 1.1 Required repository guidance

Add a short reference to this path from whichever root coding-agent instruction file is actually used by the repository (`AGENTS.md` or equivalent). That reference must say: read this document before planning; it is owner-locked; never change it without explicit permission. Do not create duplicate canonical roadmaps.

## 1.2 Source documents reconciled

- `AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION(1).md` — product-completion roadmap and detailed phases 1–23, superseded for forward numbering.
- `AVA_CANONICAL_ARCHITECTURAL_IMPLEMENTATION_PLAN(1).md` — permanent execution/model/workspace security boundaries and earlier 18-phase sequence, superseded for forward numbering.
- `AVA_CANONICAL_ARCHITECTURAL_IMPLEMENTATION_PLAN_UPDATED_2026-10-12.md` — current agreement that Phase 6 is normalized tools/approvals, Phase 7 RAG, Phase 8 configurable use cases, Phase 9 engineering workflows; used as sequencing input, not as a competing master.
- `AVA Python — Phase 5 Final Implementation & Handoff to Phase 6` (2026-10-12) — most recent Phase 5 implementation/validation evidence; inspect code for final implementation authority.

---

# 2. AVA Product Definition

**AVA is one configurable, use-case-driven AI application platform—not primarily a chatbot or an agent harness.** Its purpose is to deliver specific, verifiable outcomes through repeatable application workflows. Chat, agents, models, providers, tools, knowledge, and document handling are reusable infrastructure.

## 2.1 Standard and power-user experiences

- **Standard user:** a fixed, consistent AVA application shell that adapts minimally to a configured use case: identity/description, inputs, available actions, outputs, instructions, tool allowlist, execution behavior, and optional contextual chat.
- **Contextual assistant:** usually available within a use case to answer questions about selected authorized resources and results. It reuses Phase 5's conversation/run infrastructure; it is not a second chat system.
- **Power user:** full existing chat/agent workspace with advanced controls, subject to actual authorization. Switching experience modes does not grant privileges.
- **No general-purpose UI builder in the initial platform:** no drag/drop page design, arbitrary executable JavaScript in configuration, custom frontend generated from imported definitions, or separate hardcoded frontends per use case.

## 2.2 Initial use-case targets (NOT hardcoded implementations)

1. **Specification Intelligence and Change Advisory:** answer and cite specification knowledge; compare revisions; advise engineering teams; propose and review improvements; manage controlled updates and ownership.
2. **Robotics Intelligence:** cycle-time analysis; path and zoning improvement recommendations; predictive-maintenance analysis using servo loads, robot cycle counts, temperature, alarms, and emergency-stop patterns; identify conditions meriting gearbox/reducer investigation. Predictions require validated evidence and cannot treat e-stop correlation as proof of mechanical failure.
3. **Engineering Document Assurance:** batch process engineering documents, initially robot payload documents; extract and check relevant mass, center-of-gravity, and inertia data against applicable references; report exceptions, missing information, and unverified checks. Do not equate incomplete evidence with a pass.

These are **reference use cases**, configured using the same framework that must accommodate future domains. Availability of a configuration does not imply its domain-specific tool or data integration already exists.

## 2.3 Definition of platform-complete

A production-capable AVA platform supports: durable conversations, documents, and artifacts; meaningful user-facing use-case workflows; contextual assistance; real model execution; safe agentic/deterministic/hybrid tools; approvals; traceable knowledge retrieval; engineering validation; authenticated/authorized multi-user operation; Web/Desktop and supported clients; enterprise integrations; observability and audit; documented deployment profiles; controlled extensions. Advanced training/evolution and adaptive model research are post-core optimization tracks.

---

# 3. Permanent Architectural Invariants

```text
Agent Runtime != Model Provider
Model Provider != Model
Provider != Provider Connection
Model != Inference Runtime
Workspace != Runtime
Tool Permission != Runtime Capability
Conversation Folder != Agent Workspace
Project File != Agent Workspace File
Execution Mode != Runtime or Model
Workspace Selection != Tool Permission

Stable agent execution boundary: RunService -> AgentPort
```

- AVA owns stable public contracts, policies, tool semantics, and normalized lifecycle events. Vendor types and SDKs remain behind adapters.
- Models, providers, runtimes, inference engines, repositories, knowledge stores, and UI shells are independently replaceable.
- Runtime or model selection may **never** expand filesystem, workspace, shell, network, credential, tool, or approval authority.
- The backend authorizes every privileged operation. A frontend feature switch controls configuration and discoverability, **not** the security boundary; clients cannot self-grant rights.
- Web and Desktop remain thin shells over shared frontend packages and backend APIs. Do not add a state-management library without a proven need.
- Keep Tiptap internal to `@ava/document-core`, and persistence behind AVA-owned repositories.
- Preserve resolved execution precedence: `Explicit Run Override -> Project Default -> Application Default -> Bootstrap Fallback`. Persisted configuration, once validly configured, is authoritative; invalid persisted settings must not silently downgrade to bootstrap.
- Preserve the logical context order: AVA Root -> CORE prompts -> Project Instructions -> Conversation Summary -> Recent History -> Conversation Attachment Context -> Current User Message. Attachment contents are **untrusted data**, not system instruction.
- Preserve persisted historical execution truth: later deletion or configuration changes must not rewrite what a historical run actually used.
- Full conversation history survives context compaction; summaries, documents, Project files, conversation attachments, and agent workspace files have separate ownership semantics.
- Deterministic engineering checks remain authoritative for their calculations; LLM reasoning can interpret evidence but cannot invent validation results.
- One AVA product for personal and enterprise engineering work; configure through adapters/profiles, do not fork the application.

---

# 4. Verified Historical Baseline

| Phase | Baseline status | Core achievement |
|---|---|---|
| 1 | Complete | Monorepo, modular Python/FastAPI backend, Ports & Adapters, shared frontend/contracts, Web/Desktop foundation, Python client |
| 2 | Complete | Chat/conversation and run UI foundation, Tiptap document workspace foundation, normalized frontend packages |
| 3 | Complete / verified | Native and OpenHands runtime paths, model/provider separation, stable model identity, orchestration, workspace/tool security, resource-manager architecture |
| 4 | Complete | Durable relational repositories, versioned migrations, persisted conversations/messages/runs/events/documents/revisions/attachments |
| 5 | Implementation complete; validation exceptions | Durable conversation/run/context UX, Projects/Folders, CORE prompts, execution defaults, attachment text context, context budgeting/compaction, Run Inspector, Web/Desktop UI hardening |

**Phase 5 evidence and caveats (2026-10-12):** focused backend 166 passes; migration tests 31 passes; Python client 11 passes; frontend 1,112 passes; Web and Desktop frontend builds pass; Ruff/mypy/architecture guards pass; schema version 23. Full backend suite and aggregate harness were blocked by an isolated TestClient/AnyIO portal stall. Native Tauri desktop GUI E2E harness was implemented but not run due to unavailable X display/Xvfb. These are **open acceptance-environment gaps**, not proven product defects, and must not be silently marked PASS. The earlier development plan's Phase 5 (5.41) complete/PASS validation was a previous checkpoint, not the final October 12 status.

**Carry-forward architecture debt:** Some context-window budgeting responsibility remains in `NativeAgentAdapter`; do not deepen adapter-specific prompt preparation. Move toward AVA-owned normalized preparation when naturally touching the execution boundary; do not initiate an unrelated massive refactor.

---

# 5. Master Development Sequence

The core sequence **Phase 6 → 7 → 8 → 9** is explicitly agreed. The preservation phases **10 onward** consolidate capabilities found in the longer original product roadmap rather than silently deleting them. Their ordering should remain fixed unless the owner approves a formal amendment.

| Phase | Name | Primary deliverable |
|---|---|---|
| 6 | **Normalized Tool and Approval Framework** | Secure runtime-neutral tools, UI-managed gates, tool policy, workspace authority and durable approvals |
| 7 | **Knowledge / RAG Platform** | Source ingestion, extraction, indexing, retrieval, provenance and citations |
| 8 | **Configurable Use Case Application Framework** | Minimal use-case configuration, standard interface, optional contextual assistant, per-use-case tool allowlists |
| 9 | **Engineering Workflow Foundation** | Implement first real reference engineering workflow(s) using configured framework |
| 10 | **Complete Document Platform** | Mature document API, import/export, multi-document UX, revision history |
| 11 | **Agent-Driven Document Operations & Review** | AVA-neutral document edits, change sets, visual differences and controlled acceptance |
| 12 | **Enterprise Identity and Authorization** | Identity, sessions, roles, permissions and backend-enforced multi-user access |
| 13 | **Corporate Providers & Enterprise Runtime Integration** | Approved company gateways, Databricks, AWS AgentCore, LangGraph and provider adapters |
| 14 | **Production Observability, Reliability & Audit** | Tracing, metrics, incident recovery and auditable execution history |
| 15 | **Python / Databricks Production Client** | Fully supported programmatic/notebook workflow surface |
| 16 | **Application Profiles & Deployment** | Local, offline, corporate and connected deployment configurations |
| 17 | **Plugin / Extension Architecture** | Versioned installable capabilities behind permissions and stable interfaces |
| 18 | **Mobile & Voice Clients** | Shared conversation/context and approvals across additional clients |
| 19 | **Production Multi-Model Inventory & Resource Control** | Real model inventory, model cache/load/unload and measured resources |
| 20 | **Phase-Aware Multi-Model Execution** | More than one model per coherent user-visible run |
| 21 | **Model Qualification & Adaptive Routing Platform** | AVA workload benchmarks, persisted evidence and controlled routing |
| 22 | **Specialist Engineering Models** | Qualified domain specialist models where measured benefit exists |
| 23 | **Advanced Model Evolution Research** | SFT, LoRA/QLoRA, distillation, synthetic data and bounded experiments |

**Dependency rule:** Phase numbers are the planning sequence, not a license to ship incomplete dependencies. If the Phase 9 engineering workflow requires a missing Phase 10 document capability, implement only the minimal justified dependency as an explicitly documented bounded prerequisite; the comprehensive document platform remains Phase 10 unless owner-approved replanning changes it. This tension was inherited from reconciling the two historical roadmaps and must be visible rather than hidden.

---

# 6. Phase 6 — Normalized Tool and Approval Framework (NEXT)

**Objective:** Give AVA one secure, replaceable, runtime-neutral mechanism to discover, request, authorize, approve, execute, persist, and inspect tools. Design it for both future standard-use-case buttons and Power User agent tool calls **without implementing any actual use cases in Phase 6**.

## Deliverables

1. Inspect current Native/OpenHands/file/command mechanisms; classify AVA reusable semantics versus adapter details.
2. Introduce stable AVA-owned `ToolRegistry`, `ToolDefinition`, `ToolRequest`, `ToolResult`, `ToolExecutionContext`, `ToolPolicy`, `ApprovalRequest`, and `ApprovalDecision` contracts. Support stable IDs and versioned input/output schemas.
3. Start narrowly with safe file read, create/write, targeted edit, policy-restricted delete, and controlled command execution. Do **not** normalize all OpenHands features.
4. Maintain workspace resolution and explicit authority independent of UI Project/Folder membership and selected models/runtimes.
5. Build durable request/approval/action state, revocation, cancellation, timeout, restart behavior and normalized events: requested, approval-required, approved/denied, started, completed/failed/cancelled. Exact approved payload/scope must be bound to the approval.
6. **Frontend-managed feature gate Settings UI**: master tool-system availability, individual registered tools, approval policy visibility, workspace access management, and activity/history. Persist centrally; backend denies unavailable or unauthorized execution, including direct API bypass. Safety-critical approval enforcement and historical records cannot simply be switched off.
7. Provide a **future per-use-case tool allowlist seam**, not `UseCaseDefinition` or a use-case registry. Effective permissions later are intersection of platform gates, caller/tool allowlist, workspace/resource authority and approval policy.
8. Tool execution must not require a chat conversation as its sole entry point; define an AVA application-service invocation path that can later accept structured UI actions. Agent execution still preserves `RunService -> AgentPort`.
9. Surface normalized tool requests/results/approvals in shared UI and historical Run Inspector.
10. Prove at least one AVA tool contract through Native AVA and one additional execution path, with positive/negative policy tests.

## Phase 6 excluded

No Specification Agent, Robotics Intelligence, Payload Assurance, `UseCaseDefinition`, configurable application shell, context-bound use-case chat, RAG, plugin marketplace, enterprise identity, live robot mutation, or broad document-platform reimplementation.

## Phase 6 exit

A UI-disabled or unauthorized tool cannot execute even through a direct API or alternate runtime; approved tool operations are durable, resumable/reconcilable as specified, traceable, and policy-controlled; one public tool contract works across at least two paths; Phase 5 regressions are absent and existing validation gaps honestly tracked.

---

# 7. Phase 7 — Knowledge / RAG Platform

**Objective:** Build AVA-owned, runtime-independent knowledge ingestion and retrieval with traceable citations and source authorization seams.

Pipeline: source -> extraction -> normalization -> chunking -> metadata -> embeddings/indexing -> vector/structured stores -> authorized retrieval -> knowledge service -> selected model/runtime. Use replaceable vector storage, relational metadata and object/source document storage. Sources prioritize engineering specifications, PDFs, Word, structured data and approved files. Preserve source/version/page/section provenance. Retrieval must not bypass document authorization. **Do not implement specialized use-case apps here.**

**Exit:** An approved document can be ingested and queried, returning grounded passages/citations through a selected runtime/model, with negative tests for inaccessible sources.

---

# 8. Phase 8 — Configurable Use Case Application Framework

**Objective:** Provide a simple, reusable application experience driven by minimal configuration—**not** a visual low-code builder or hardcoded apps.

**Fixed standard UI:** use-case navigation, header, input/resource area, action controls, structured results, optional collapsible contextual AVA assistant. Retain the full chat/agent workspace for Power Users. Experience mode does not confer authority.

**Minimal versioned definition:** identity, description, supported input types, registered actions, output presentation, instructions, deterministic/agentic/hybrid execution style, allowed registered tools, optional assistant and context scope. Model/runtime defaults are inherited unless an explicit supported preference fits the existing precedence. Persist configuration and per-version historical execution identity.

**Management UI:** simple Settings screens to create/duplicate/edit/validate/publish/enable/disable definitions and select allowed tools. No drag-and-drop editor, arbitrary script definitions or user-supplied React. Tool allowlists cannot expand platform authorization.

**Acceptance:** one generic configured screen renders at least three distinct example definitions (specification advisory, robotics analytics, payload assurance) without separate hardcoded UI screens. One available simple action executes through Phase 6 security, shows results, and optional embedded chat uses authorized selected context. Unimplemented domain connectors show 'unavailable', not fabricated results.

---

# 9. Phase 9 — Engineering Workflow Foundation

**Objective:** Prove AVA can deliver useful manufacturing-engineering workflows through the Phase 8 generic application experience.

**First integration priority:** controlled requirements/specification review with retrieval, source comparison, structured findings, citations, proposed changes, engineer review and report output. Introduce additional reference workflows as their data and connectors become real: robot cycle-time/path/zoning optimization; telemetry-based predictive maintenance; folder-based robot payload assurance.

**Safety:** robotics recommendations are advisory and require offline validation; no uncontrolled live robot movement, safety-zone updates or production-controller mutation. Gearbox failure predictions must be measured against maintenance outcomes. Document validation distinguishes pass/fail/unverified. Do not claim engineering assurance from an LLM alone.

**Exit:** at least one real end-to-end engineering workflow produces verified, inspectable, cited and reviewable results through the generic UI and preserves every tool/knowledge permission boundary.

---

# 10. Phase 10 — Complete Document Platform

Mature the existing Tiptap-backed platform (do not rebuild its foundation). Complete AVA-owned document lifecycle/API, controlled import (text/Markdown/Word/PDF-read-only where appropriate), safe export, persistent multi-document workspace, search/selection, metadata and revision/version history, comparison and restoration. Keep Tiptap behind `@ava/document-core` and persistence behind repositories.

**Exit:** create/import/edit/save/close/reopen/search/version documents across restarts, with reliable client/server consistency.

---

# 11. Phase 11 — Agent-Driven Document Operations and Review

Complete neutral operations such as insert, replace, delete, format, structured block, comment, annotation and change set. Validate target range/revision and source run, translate into Tiptap inside the editor adapter only, show before/after changes, provide accept/reject/batch decisions and reversal where feasible. Integrate with Phase 6 approvals and durable history; don't create a second approval engine.

**Exit:** an agent proposes a document edit in AVA-neutral form; user reviews it; AVA validates/approves/applies it with a reversible or version-traceable result.

---

# 12. Phase 12 — Enterprise Identity and Authorization

Implement identity ports, sessions, roles, permissions and backend-enforced authorization covering conversations, documents, knowledge, tools, workspaces, runtimes, models, configuration and approvals. The frontend is never a security authority. Preserve least privilege and audit-ready identity provenance.

**Exit:** authenticated identities and explicit policies govern all protected operations, including direct API calls.

---

# 13. Phase 13 — Corporate Providers and Enterprise Runtime Integration

Connect approved company AI gateway, Databricks Model Serving/agent options, AWS AgentCore, LangGraph and external models through adapters. Keep local implementations functioning, stable model identity distinct from provider identity and model selection separate from runtime selection.

**Exit:** an approved enterprise provider and runtime/integration operate without changing AVA public contracts.

---

# 14. Phase 14 — Production Observability, Reliability and Audit

Structured request/run tracing, model/runtime/provider/tool timing, retries, timeouts, model-resource state, meaningful logging and reliable cleanup. Durable audit of actors, workspace, operations, source artifacts, approvals and configuration changes. Do not log sensitive prompt/tool contents by default.

**Exit:** administrators can reconstruct what happened, why, by whom, and what failed without unsafe information exposure.

---

# 15. Phase 15 — Python / Databricks Production Client

Finish notebook/automation client parity for authentication, workflow/task and document submission, runs/events, artifacts, citations, structured outputs and approvals. Databricks is a client/integration, not a separate application.

**Exit:** a notebook can run the same supported use-case workflow as the UI using AVA contracts.

---

# 16. Phase 16 — Application Profiles and Deployment

Define structured personal-local, corporate-engineering, enterprise-connected, offline/restricted profiles controlling branding, available runtimes/providers, auth adapter, storage, tool/knowledge availability and workspace policy. Document local Desktop, remote Web, approved AWS and Databricks-connected deployments. Profiles configure one product; no forks.

**Exit:** same AVA codebase runs in two meaningfully distinct supported profiles.

---

# 17. Phase 17 — Plugin / Extension Architecture

Define versioned installed capability manifests, compatibility, dependencies, lifecycle, configuration schema, declared permissions, registration/cleanup and bounded UI integration. Plugin capabilities may be installed/enabled/disabled but never bypass core security. Phase 8 use-case configuration can consume approved registered extensions after installation.

**Exit:** an independently packaged capability extends AVA without modifying core shell or bypassing authorization.

---

# 18. Phase 18 — Mobile and Voice Clients

Make mobile and voice thin additional channels over the same conversation, context, run, tools, and authorization services. Voice needs live cross-channel context and interruption handling, but **no separate voice memory**. Mobile prioritizes lookup, approvals, notifications, review and remote monitoring.

**Exit:** a mobile or voice session participates coherently in the same durable state as Web/Desktop.

**Core product completion gate:** at completion of Phase 18, evaluate durable, usable, secure, extensible product readiness against real end-user use cases. Phases 19–23 are advanced capability and optimization tracks, not prerequisites for first product completeness.

---

# 19. Phase 19 — Production Multi-Model Inventory and Resource Control

Structured inventory and model download/cache verification; truthfully support engine-specific load/unload/keep-alive/readiness for Ollama, llama.cpp, vLLM, SGLang where justified. Actual GPU/VRAM state and lease scheduling must reflect real measurements; avoid pretending remote provider resources are locally managed.

**Exit:** AVA manages real local models/resources under configured inventory without misleading status or breaking model/provider identity.

---

# 20. Phase 20 — Phase-Aware Multi-Model Execution

One run may contain ordered phases/model invocations with distinct stable model identities and auditable selection. Account for swaps/latency, prefer coherent phase-level changes, preserve tool/workspace authority, avoid token-by-token model switching.

**Exit:** one visible run uses two distinct model IDs across traceable phases safely.

---

# 21. Phase 21 — Model Qualification and Adaptive Routing Platform

Make workload-specific model qualification repeatable: tool choice/schema, read-before-edit, test-repair, citation quality, context stability, cancellation, sandbox compliance and prompt injection resistance. Persist scores and environment/model metadata. Routing evolves deterministically through weighted measured and later adaptive approaches, keeping rollback/deterministic fallback.

**Exit:** AVA selects qualified models using defensible evidence and explains routing decisions.

---

# 22. Phase 22 — Specialist Engineering Models

Evaluate LoRA/QLoRA/SFT/distillation for specification, robotics, PLC, code, document and manufacturing RCA tasks only where evidence shows improvement. Specialist models must pass AVA qualification before production promotion.

**Exit:** at least one specialist shows reproducible improvement without weakening security or reliability.

---

# 23. Phase 23 — Advanced Model Evolution Research

Separate ongoing research into synthetic datasets, benchmarking, expert-model design, self-evaluation, distillation and bounded improvement loops. The previously deferred specialization/training Step 35 belongs here. Research does not block core product completion and cannot silently alter production behavior.

---

# 24. Implementation Discipline and Evidence

For each bounded step:

1. Read this locked plan, current repository and latest implementation handoff.
2. Identify the **single approved** step and its dependencies.
3. Inspect before editing; preserve existing architecture.
4. Implement a bounded, testable increment; add architecture guard(s) when new critical dependencies arise.
5. Test actual execution and negative authorization paths—not only DTO existence.
6. Run affected tests, Ruff, strict mypy, Python client checks, frontend tests/typechecking, Web/Desktop builds and `./scripts/test_all.sh` where environment permits.
7. Document environmental exceptions accurately; do not label unexecuted acceptance tests PASS.
8. Write implementation report and proposed follow-up in separate phase documents.
9. **STOP for review.** Never auto-advance to the next bounded step or next phase.
10. **Never edit this master plan unless owner explicitly authorizes the specific revision.**

---

# 25. Open Planning Tensions — Explicitly Recorded

These are not invitations for agents to decide on their own:

- The fuller original product roadmap made a complete Document Platform an early prerequisite (former Phase 6); the newer agreed roadmap prioritizes Phase 6 tools, Phase 7 RAG, Phase 8 use-case UI and Phase 9 first engineering workflows. This consolidation preserves full Document Platform as Phase 10; any earlier document dependencies must be handled narrowly or resolved by owner-approved resequencing.
- The original roadmap separated approval UI and tools into different phases. The agreed Phase 6 combines foundational tool approvals; Phase 11 retains **document-specific review UX** and must reuse Phase 6's approval contracts.
- Enterprise Identity remains later work; Phase 6 must enforce local/workspace/tool authority independently and must not claim that enterprise multi-user authorization is already implemented.
- The historical Phase 5 PASS checkpoint and final October 12 PARTIAL acceptance results reflect different test windows. Most recent tested evidence wins; full suite and desktop native GUI remain tracked gaps.
- Phase 8 configures use cases; the underlying capabilities needed by individual use cases arrive through Phase 7, Phase 9 and later integrations. No placeholder can be advertised as a validated domain capability.

---

# 26. Revision History

| Version | Date | Status | Notes |
|---|---|---|---|
| 1.0-review | 2026-10-12 | **Prepared, pending owner approval** | Consolidated detailed product roadmap with current tool/RAG/use-case phase decisions and latest Phase 5 handoff; marked owner-locked to coding agents. |

**Owner approval record:** Pending. Once explicitly approved, change status to `LOCKED / AUTHORITATIVE` under owner direction; do not treat the creation of this review artifact as automatic approval.
