# AVA — Canonical Development Plan
## Current State to Product Completion

**Status:** Canonical Forward Development Plan  
**Reoriented:** 2026-09-18  
**Current Position:** Phase 3 COMPLETE / PASS  
**Next Phase:** Phase 4 — Durable Application State  
**Development Principle:** Product capability first; infrastructure only when it directly enables the product.

---

# 1. Purpose

This document defines AVA's development path from its current verified state through completion of the first full production-capable AVA platform.

It replaces the drift that occurred when backend runtime/model architecture advanced significantly beyond the user-facing application.

The work completed in Phase 3 is retained. It is not rolled back or redesigned.

From this point forward, development returns to the original AVA product direction:

```text
Durable Application
        ↓
Complete AI User Experience
        ↓
Documents
        ↓
Agent-Driven Operations
        ↓
Human Review / Approval
        ↓
Tools
        ↓
Knowledge / RAG
        ↓
Engineering Workflows
        ↓
Enterprise Integration
        ↓
Production Operations
        ↓
Extensions / Mobile / Voice
        ↓
Advanced Model Intelligence
```

---

# 2. Definition of AVA Completion

For this roadmap, "AVA complete" means the reusable platform can support a real user from end to end across Web and Desktop with:

- persistent conversations and documents;
- real model-backed conversations;
- streaming and recoverable runs;
- safe agent tool use;
- agent-driven document changes;
- human review and approval;
- knowledge retrieval with citations;
- engineering workflows;
- authentication and authorization;
- local, company-hosted, and approved external models;
- multiple agent runtimes through AVA-owned abstractions;
- enterprise integrations;
- production observability and audit;
- extensibility through a controlled plugin architecture;
- mobile and voice-capable clients using the same platform;
- optional advanced multi-model orchestration.

Completion does **not** require all future AI research to be solved.

Model training, automated model evolution, highly adaptive routing, and experimental specialist-model research remain continuing research tracks after the core product is complete.

---

# 3. Completed Development

## Phase 1 — Foundation
**Status: ✅ COMPLETE**

Completed:

- monorepo;
- Python modular-monolith backend;
- FastAPI application;
- Hexagonal Architecture / Ports and Adapters;
- shared TypeScript frontend packages;
- Web shell;
- Desktop shell;
- Mobile placeholder;
- Python client;
- versioned AVA contracts;
- configuration foundation;
- backend/frontend validation infrastructure.

---

## Phase 2 — Core AI UX and Workspace Foundation
**Status: ✅ COMPLETE**

Completed:

- ChatGPT/Claude-style application shell foundation;
- conversation/message UI;
- prompt composer;
- conversation state;
- run lifecycle;
- normalized run events;
- cancellation;
- retry/regenerate foundation;
- shared Web/Desktop UI;
- Tiptap-backed document workspace;
- create/select/rename/update/save-state/close document flows;
- shared document abstraction;
- shared API client.

Important limitation carried forward:

```text
conversation state = primarily in memory
document state     = primarily in memory
run/event state    = primarily in memory
```

---

## Phase 3 — Runtime, Model, Workspace, and Security Foundation
**Status: ✅ COMPLETE / PASS**

Verified completion includes:

- Native runtime;
- OpenHands runtime;
- runtime registry/resolver;
- provider registry/resolver;
- runtime/provider independence;
- workspace discovery/resolution;
- controlled OpenHands file access;
- workspace path containment;
- controlled command-execution boundary;
- Bubblewrap integration where available;
- runtime/tool security hardening;
- stable AVA `model_id`;
- provider/model cardinality separation;
- hosting-mode classification;
- Model Registry v1;
- qualification metadata;
- deterministic ModelOrchestrator;
- ModelResourceManager;
- explicit model leases;
- multi-model execution identity proof.

Canonical invariants:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Model ≠ Inference Runtime
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

Stable application boundary:

```text
RunService
    ↓
AgentPort
```

`RunService` must remain insulated from runtime/model/provider/resource/workspace internals.

---

# 4. Development Rules From This Point Forward

Every new phase must follow these rules:

1. Prefer visible product capability over speculative infrastructure.
2. Implement one bounded step at a time.
3. Do not redesign Phase 3 seams unless real evidence requires it.
4. AVA owns all public contracts.
5. Vendor/framework objects remain behind adapters.
6. Web and Desktop share behavior by default.
7. Client input never grants permissions.
8. Runtime capability never equals authorization.
9. Model selection never widens workspace/tool/network authority.
10. Provider identity never substitutes for model identity.
11. Persistence remains behind AVA-owned repositories.
12. Knowledge/RAG remains runtime-independent.
13. Corporate integrations remain adapters.
14. Advanced model routing waits until the application produces useful telemetry.
15. Every step receives targeted tests and full regression validation.
16. A contract alone does not mean a feature is complete; the real path must work.
17. Update this plan when a phase is completed or deliberately rescheduled.

---

# 5. Phase 4 — Durable Application State

**Priority:** IMMEDIATE  
**Status:** ⬜ NOT STARTED

## Objective

Replace the application's important in-memory state with durable storage while preserving the existing AVA architecture.

## 4.1 Repository contracts

Create or finalize AVA-owned repository interfaces for:

```text
ConversationRepository
MessageRepository
RunRepository
RunEventRepository
DocumentRepository
AttachmentRepository
ApprovalRepository
ApplicationConfigurationRepository
AuditRepository
```

Do not expose SQL/database implementation objects to application/core code.

## 4.2 Relational persistence

Introduce the first concrete relational persistence adapter.

Requirements:

- version-controlled migrations;
- local development database;
- isolated test database support;
- explicit transactions;
- backend-neutral repository interfaces;
- in-memory adapters retained for deterministic tests.

## 4.3 Conversation persistence

Persist:

- conversation ID;
- title;
- timestamps;
- messages;
- message roles/status;
- associated run IDs.

## 4.4 Run persistence

Persist:

- runs;
- run status;
- normalized events;
- selected execution metadata already exposed by AVA;
- terminal state;
- cancellation state.

## 4.5 Document persistence

Persist:

- document identity;
- title;
- content;
- timestamps;
- dirty/saved revision state;
- document metadata.

## Phase 4 exit criteria

- restart backend → conversations remain;
- restart backend → documents remain;
- restart backend → runs/events remain;
- Web and Desktop reopen persisted state;
- existing mock/in-memory tests remain possible;
- no persistence technology leaks into AVA Core;
- full validation remains green.

---

# 6. Phase 5 — Production Conversation, Context, and Run Experience

**Status:** ⬜ NOT STARTED

## Objective

Turn the existing conversation UI into a durable, live, recoverable AI experience.

## 5.1 Conversation history

Implement:

- persisted conversation list;
- reopen conversation;
- rename conversation;
- delete/archive policy;
- timestamps;
- latest-message preview;
- conversation ordering.

## 5.2 Real streaming

Add a normalized AVA streaming transport.

Desired flow:

```text
Runtime / Provider
        ↓
AVA Run Events
        ↓
Persistent RunEvent Store
        ↓
Streaming API
        ↓
@ava/api-client
        ↓
@ava/agent-ui
```

Support:

- partial assistant output;
- progress;
- tool activity;
- terminal state;
- failure;
- cancellation.

## 5.3 Reconnect and recovery

Support:

- browser refresh during run;
- Desktop reconnect;
- reconnect after temporary API interruption;
- event replay from last known event;
- reconciliation between client state and backend run state.

## 5.4 Attachments

Add normal chat attachment support using controlled references rather than repeatedly embedding large files.

## 5.5 Context Orchestration Service

Introduce an AVA-owned context layer.

Each conversation remains its own independent contextual thread.

The context service may retrieve from:

```text
current conversation
other permitted conversations
documents
workspace state
approved user/application context
knowledge sources
```

The service must distinguish:

```text
thread-local context
cross-thread context
retrieved knowledge
temporary run context
```

No channel should maintain a separate stale copy of conversational truth.

## 5.6 Voice-ready context architecture

Future voice is treated as another client/channel over the same conversation/context platform.

```text
Text UI ──────┐
              │
Voice UI ─────┼──→ Conversation / Context Service
              │             ↓
Mobile UI ────┘         RunService
```

Voice must be able to access the current live conversation state, including changes that occurred moments earlier in text.

Do not build a separate "voice memory" architecture.

## Phase 5 exit criteria

A user can:

- close/reopen AVA and continue a conversation;
- watch real streamed output;
- refresh during/after a run and recover correctly;
- attach supported files;
- continue context reliably;
- use the same context model from Web and Desktop;
- expose the same context service later to voice.

---

# 7. Phase 6 — Complete Document Platform

**Status:** ⬜ FOUNDATION EXISTS

## Objective

Turn the Tiptap workspace from an in-session editor into a real AVA document platform.

## 6.1 Backend document API

Add AVA endpoints/services for:

- list documents;
- get document;
- create;
- update;
- rename;
- close/archive;
- delete according to policy;
- metadata;
- version information.

## 6.2 Import

Support controlled import of priority formats:

- plain text;
- Markdown;
- Word where appropriate;
- PDF as a source/read-only artifact where editing fidelity is not supported.

## 6.3 Export

Support safe export of supported document forms.

## 6.4 Multi-document workspace

Enable persistent:

- multiple documents;
- active document selection;
- recent documents;
- search/filter;
- metadata.

## 6.5 Version history

Introduce document versions/revisions sufficient for:

- comparing agent changes;
- restoring previous content;
- audit/history;
- review workflows.

## Phase 6 exit criteria

A user can create, import, edit, save, close, reopen, search, and version documents across application restarts.

---

# 8. Phase 7 — Agent-Driven Document Operations

**Status:** ⬜ NOT PRODUCTIZED

## Objective

Allow agents to propose structured document changes without giving a model direct control of Tiptap.

## 7.1 Neutral document operations

Complete AVA-owned operations for:

```text
insert
replace
delete
format
structured block
comment
annotation
change set
```

Every operation includes:

- operation ID;
- document ID;
- stable target/range;
- source run;
- operation type;
- content;
- validation state.

## 7.2 Validation

Validate proposed operations before they reach the editor.

## 7.3 Document adapter

Translate validated AVA operations into Tiptap commands inside the editor adapter only.

## 7.4 Proposed-change UI

Show agent changes visually before application.

## Phase 7 exit criteria

An agent can propose a real document edit, AVA validates it, the UI presents it, and the editor can apply it without the agent emitting raw Tiptap commands.

---

# 9. Phase 8 — Review and Approval System

**Status:** ⬜ NOT STARTED

## Objective

Give users explicit control over consequential AI actions.

## 8.1 Review UI

Implement:

- proposed-change cards;
- before/after comparison;
- explanations;
- pending indicators;
- change grouping.

## 8.2 Decisions

Support:

- accept;
- reject;
- batch accept/reject;
- undo/reversal where possible.

## 8.3 Approval contracts

Normalize:

```text
ApprovalRequest
ApprovalDecision
ApprovalStatus
ApprovalReason
```

## 8.4 Durable approval history

Record:

- user;
- run;
- action/operation;
- decision;
- timestamp;
- resulting artifact/version.

## Phase 8 exit criteria

Agent-generated document modifications and privileged actions can pause for review and cannot proceed without the required AVA-owned approval decision.

---

# 10. Phase 9 — AVA Tool Framework

**Status:** ⬜ SECURITY FOUNDATION EXISTS

## Objective

Generalize the safe tool behavior proven during Phase 3 into AVA's reusable tool platform.

## 9.1 Tool registry

Introduce:

```text
ToolRegistry
ToolDefinition
ToolRequest
ToolResult
ToolExecutionContext
ToolPolicy
```

Each tool defines:

- stable tool ID;
- description;
- input schema;
- output schema;
- required permissions;
- execution handler;
- audit behavior;
- UI renderer metadata.

## 9.2 Normalize existing capabilities

Bring existing controlled capabilities under the framework:

- file read;
- file write/edit;
- controlled command execution.

## 9.3 Tool lifecycle events

Normalize:

```text
tool_requested
tool_approval_required
tool_started
tool_progress
tool_completed
tool_failed
```

## 9.4 Tool result UI

Provide reusable UI cards for:

- command results;
- file changes;
- structured data;
- errors;
- generated artifacts.

## 9.5 Runtime independence

A tool's public AVA contract must not change because the selected runtime changes.

## Phase 9 exit criteria

At least one normalized AVA tool executes through more than one supported execution path without changing its client-visible contract.

---

# 11. Phase 10 — Knowledge and RAG Platform

**Status:** ⬜ NOT STARTED

## Objective

Give AVA controlled access to reusable knowledge independent of agent runtime.

## 10.1 Ingestion

Build pipeline:

```text
Source
 ↓
Extraction
 ↓
Normalization
 ↓
Chunking
 ↓
Metadata
 ↓
Indexing
```

Initial sources:

- Word documents;
- PDF documents;
- engineering specifications;
- structured records;
- approved files.

## 10.2 Storage separation

Use storage according to need:

```text
Relational database → metadata / structured relationships
Object/document store → source artifacts
Vector store → semantic retrieval
Graph store → only where relationship complexity justifies it
```

Do not make AVA permanently dependent on one vector database.

## 10.3 Retrieval service

Create AVA-owned retrieval contracts/services.

## 10.4 Citations and provenance

Every retrieved fact used in user-visible output should preserve:

- source identity;
- source location;
- chunk/section where available;
- version;
- retrieval metadata.

## 10.5 Permissions

Design retrieval so later user/document authorization can filter sources without redesigning RAG.

## Phase 10 exit criteria

AVA can ingest approved documents, retrieve relevant passages, answer through a selected runtime/model, and return traceable citations to the source material.

---

# 12. Phase 11 — First Engineering Workflow

**Status:** ⬜ NOT STARTED

## Objective

Prove that the general AVA platform can deliver a complete engineering use case without creating a separate application.

## Initial workflow

### Engineering Requirements / Specification Review

```text
Engineering Document
        +
Applicable Standards / Knowledge
        ↓
AVA Retrieval
        ↓
Requirement Comparison
        ↓
Missing / Conflicting Requirements
        ↓
Structured Findings
        ↓
Citations
        ↓
Engineer Review
        ↓
Accept / Reject
        ↓
Document / Report Output
```

## Required integration

This workflow must exercise:

- documents;
- context;
- RAG;
- tools;
- model/runtime execution;
- citations;
- approvals;
- structured outputs;
- persistence;
- audit.

## Phase 11 exit criteria

A real engineering document can be analyzed against controlled source material and produce reviewable, cited findings through the normal AVA application.

---

# 13. Phase 12 — Authentication and Authorization

**Status:** ⬜ NOT STARTED

## Objective

Move AVA from local/single-user assumptions to secure multi-user operation.

## 12.1 Identity abstraction

Introduce:

```text
IdentityPort
User
Session
Role
Permission
AuthorizationPolicy
```

## 12.2 Authorization domains

Control:

- conversation access;
- document access;
- workspace access;
- knowledge-source access;
- tool access;
- runtime access;
- model/provider access;
- configuration;
- approval authority;
- administrative actions.

## 12.3 Client rule

The client may request an action.

The client may never assert that it is authorized for that action.

## Phase 12 exit criteria

All protected operations are authorized server-side against authenticated identity and explicit policy.

---

# 14. Phase 13 — Python / Databricks Production Client

**Status:** ⬜ BASIC PYTHON CLIENT EXISTS

## Objective

Complete AVA's non-UI client path.

## Scope

Support:

- authentication;
- conversation/task submission;
- document submission;
- run status;
- event/result retrieval;
- artifact retrieval;
- approvals;
- citations;
- notebook-friendly structured output;
- example Databricks notebooks.

## Principle

Databricks is a client/integration of AVA, not a separate AVA architecture.

Browser, Desktop, Python, and Databricks use the same AVA contracts.

## Phase 13 exit criteria

A notebook can execute the same supported workflow as the UI without loading the React application.

---

# 15. Phase 14 — Corporate / Enterprise Integrations

**Status:** ⬜ NOT PRODUCTIZED

## Objective

Connect AVA to approved enterprise AI systems without modifying AVA Core.

## Adapter targets

As approved/required:

- company AI gateway;
- Databricks Model Serving;
- Databricks agent platform;
- AWS AgentCore;
- LangGraph runtime;
- authorized external providers.

## Requirements

- vendor SDKs remain inside adapters;
- corporate credentials never enter shared UI contracts;
- corporate configuration stays outside reusable core;
- model/runtime independence remains intact;
- current local path continues to work.

## Phase 14 exit criteria

At least one approved enterprise model/provider and one enterprise runtime/integration can be selected through AVA without changing core application logic or frontend contracts.

---

# 16. Phase 15 — Production Observability, Reliability, and Audit

**Status:** ⬜ PARTIAL FOUNDATIONS ONLY

## Objective

Make AVA operable and supportable in production.

## Observability

Implement:

- structured logs;
- request IDs;
- correlation IDs;
- run tracing;
- runtime tracing;
- model-selection tracing;
- model invocation timing;
- provider timing;
- tool timing;
- retry/timeout metrics;
- resource state;
- usage metrics;
- errors.

## Reliability

Add explicit policy for:

- retries;
- timeouts;
- cancellation;
- provider failure;
- runtime failure;
- reconnect;
- resource cleanup;
- graceful degradation.

## Audit

Persist:

- identity;
- run;
- model/runtime/provider;
- workspace;
- tools;
- file/document changes;
- approvals;
- knowledge sources;
- routing decisions;
- configuration changes.

Do not log sensitive prompt/tool content by default.

## Phase 15 exit criteria

An administrator/developer can reconstruct what AVA did, why it did it, who authorized it, and where a failure occurred without exposing protected content unnecessarily.

---

# 17. Phase 16 — Application Profiles and Deployment

**Status:** ⬜ NOT STARTED

## Objective

Prove one AVA codebase can support personal and corporate deployments.

## Profiles

Create structured application profiles such as:

```text
Personal Local
Corporate Engineering
Enterprise Connected
Offline / Restricted
```

Profiles may configure:

- branding;
- available runtimes;
- available providers/models;
- identity adapter;
- persistence adapter;
- approved tools;
- knowledge sources;
- workspace policy;
- enterprise integrations.

Profiles are configuration, not forks.

## Deployment

Document/package supported deployment patterns for:

- local developer workstation;
- Desktop + local backend;
- Web + remote backend;
- approved AWS environment;
- Databricks-connected deployment;
- corporate deployment.

## Phase 16 exit criteria

The same source foundation can run in at least two meaningfully different profiles without branching the application architecture.

---

# 18. Phase 17 — Plugin / Extension Architecture

**Status:** ⬜ NOT STARTED

## Objective

Allow new capabilities to extend AVA without modifying the core application shell.

## Plugin contract

Support:

- identity/version;
- platform compatibility;
- dependencies;
- startup/shutdown;
- service registration;
- event registration;
- configuration schema;
- capability declarations;
- permissions;
- UI extension locations;
- cleanup.

## Candidate plugin domains

- document capabilities;
- tool renderers;
- engineering modules;
- integrations;
- knowledge connectors;
- corporate configuration;
- specialized UI surfaces.

## Security requirement

Plugins may request permissions.

Plugins may never bypass AVA authorization, workspace policy, tool policy, or contract boundaries.

## Phase 17 exit criteria

A non-core capability can be installed/enabled/disabled without modifying AVA's application shell or weakening security boundaries.

---

# 19. Phase 18 — Mobile and Voice Clients

**Status:** ⬜ MOBILE PLACEHOLDER / VOICE ARCHITECTURE ONLY

## Objective

Extend AVA to additional interaction channels without creating separate conversation architectures.

## Mobile

Prioritize:

- conversations;
- engineering lookup;
- approvals;
- notifications;
- document review;
- remote task monitoring.

Full desktop-style editing is optional.

## Voice

Voice uses:

```text
same Conversation
same Context Orchestration Service
same RunService
same tools/policies
same authorization
same knowledge
```

Voice-specific components handle:

- speech input;
- speech output;
- interruption;
- live turn handling.

They do not own separate long-term context.

## Phase 18 exit criteria

Mobile and/or voice can participate in the same durable AVA conversation state as Web/Desktop without context drift between channels.

---

# 20. Phase 19 — Production Multi-Model Inventory and Resource Control

**Status:** ⬜ ARCHITECTURE FOUNDATION COMPLETE

## Objective

Productize the Phase 3 multi-model seams only after the application produces real workloads worth optimizing.

## 19.1 Multi-model configuration

Introduce structured model inventory configuration or persisted administration.

Do not build a large environment-variable DSL.

## 19.2 Local model manager

Support:

```text
approved model source
        ↓
download/copy
        ↓
checksum/license verification
        ↓
local SSD cache
        ↓
inference runtime
```

## 19.3 Real resource adapters

Add truthful engine-specific resource adapters where useful:

- Ollama;
- llama.cpp;
- vLLM;
- SGLang.

Possible responsibilities:

- load;
- unload;
- keep-alive;
- readiness;
- context settings;
- GPU layer settings;
- measured memory/resource status.

## Phase 19 exit criteria

AVA can manage a real configured local model inventory and safely make the selected model operational without pretending provider-managed resources are under AVA control.

---

# 21. Phase 20 — Phase-Aware Multi-Model Execution

**Status:** ⬜ NOT STARTED

## Objective

Allow one user-visible run to use different models for meaningful execution phases.

## Execution hierarchy

```text
Run
└── Phase
    └── Model Invocation
```

Potential phases:

- planning;
- retrieval;
- repository inspection;
- coding;
- validation;
- document analysis;
- final response.

## Requirements

- preserve one user-visible run;
- preserve workspace/tool permissions across model changes;
- record model per invocation;
- account for model-switch cost;
- prefer model reuse when differences are marginal;
- no token-by-token switching.

## Phase 20 exit criteria

One AVA run can intentionally use at least two different stable `model_id` values for separate observable phases while preserving one coherent run lifecycle.

---

# 22. Phase 21 — Model Qualification and Routing Platform

**Status:** ⬜ RESEARCH FOUNDATION EXISTS

## Objective

Turn Phase 3 qualification concepts into persisted operational evidence.

## Qualification

Measure real AVA workloads such as:

- tool selection;
- schema-valid tool calls;
- read-before-edit;
- edit-test-repair;
- repository navigation;
- document analysis;
- citation quality;
- failure recovery;
- long-loop stability;
- cancellation;
- workspace compliance;
- prompt-injection resistance.

Persist results by stable model identity and environment.

## Routing evolution

Maintain stages:

```text
deterministic rules
    ↓
weighted measured scoring
    ↓
performance-aware routing
    ↓
controlled adaptive routing
```

The deterministic router always remains available for explainability, rollback, and testing.

## Phase 21 exit criteria

AVA can select models using persisted AVA-specific evidence while explaining the eligibility and routing decision.

---

# 23. Phase 22 — Specialist Engineering Models

**Status:** ⬜ EXPERIMENTAL

## Objective

Add domain-specialized models only where measured evidence shows they improve AVA workloads.

Candidate domains:

- engineering specifications;
- manufacturing requirements;
- PLC;
- robotics;
- code;
- document analysis;
- root-cause analysis;
- vision.

Possible methods:

- LoRA;
- QLoRA;
- SFT;
- distillation where appropriate.

Promotion requires qualification against the normal AVA platform.

## Phase 22 exit criteria

At least one specialist demonstrates measured improvement over the general baseline for a defined AVA task without weakening reliability, policy, or tool behavior.

---

# 24. Phase 23 — Advanced Model Evolution Research

**Status:** ⬜ CONTINUING RESEARCH

## Objective

Explore advanced model improvement without making the production platform depend on unproven research.

Potential research:

- synthetic training-data generation;
- automated benchmark generation;
- LoRA/QLoRA optimization;
- expert-model creation;
- routing models;
- self-evaluation;
- controlled model-improvement loops.

The earlier Step 35 work belongs here.

Research failure is evidence, not a platform failure.

This phase is never allowed to block the completed product.

---

# 25. Completion Sequence

The canonical sequence from the current state is:

```text
✅ Phase 1   Foundation
✅ Phase 2   Core AI UX / Workspace Foundation
✅ Phase 3   Runtime / Model / Security Foundation

⬜ Phase 4   Durable Application State
⬜ Phase 5   Production Conversation / Context / Runs
⬜ Phase 6   Complete Document Platform
⬜ Phase 7   Agent-Driven Document Operations
⬜ Phase 8   Review and Approval
⬜ Phase 9   AVA Tool Framework
⬜ Phase 10  Knowledge / RAG
⬜ Phase 11  First Engineering Workflow
⬜ Phase 12  Authentication / Authorization
⬜ Phase 13  Python / Databricks Production Client
⬜ Phase 14  Corporate / Enterprise Integrations
⬜ Phase 15  Observability / Reliability / Audit
⬜ Phase 16  Application Profiles / Deployment
⬜ Phase 17  Plugin / Extension Architecture
⬜ Phase 18  Mobile / Voice
⬜ Phase 19  Production Multi-Model Resource Control
⬜ Phase 20  Phase-Aware Multi-Model Execution
⬜ Phase 21  Qualification / Routing Platform
⬜ Phase 22  Specialist Engineering Models
⬜ Phase 23  Advanced Model Evolution Research
```

---

# 26. Product Completion Gate

AVA reaches the primary **product-complete** milestone at the end of Phase 18.

At that point AVA should be:

- durable;
- usable;
- document-capable;
- agentic;
- human-governed;
- tool-capable;
- RAG-enabled;
- engineering-capable;
- authenticated;
- enterprise-connectable;
- observable;
- configurable;
- extensible;
- cross-client;
- voice/mobile ready.

Phases 19–23 are advanced optimization and intelligence phases.

They improve the platform but are not prerequisites for AVA to be considered a complete usable product.

---

# 27. Immediate Next Development Phase

## Phase 4 — Durable Application State

The first bounded implementation step should be:

```text
Define AVA-owned repository ports and persistence ownership
```

Start with the domains already present in memory:

```text
Conversation
Message
Run
RunEvent
Document
```

Then add the first concrete persistence adapter.

Do **not** begin RAG, adaptive routing, additional runtimes, model training, or enterprise integration during this step.

---

# 28. Standard Implementation Method

Every implementation step should use the proven controlled-development pattern:

```text
1. Inspect current code and documentation.
2. Implement ONE narrowly scoped step.
3. Preserve architectural boundaries.
4. Add targeted tests.
5. Run affected tests.
6. Run full validation.
7. Update implementation documentation.
8. Produce completion report.
9. STOP.
10. Review before beginning the next step.
```

Coder agents must not implement future steps simply because they appear in this roadmap.

---

# 29. Validation Gate for Every Phase

At minimum:

```text
Backend tests
Backend Ruff
Backend strict mypy
Python client tests
Python client Ruff
Python client strict mypy
Frontend package tests
TypeScript checks
Web production build
Desktop production build
scripts/test_all.sh
```

Additional phase-specific end-to-end tests are required.

A phase is not complete because types, ports, or UI placeholders exist.

The actual user-facing or execution path must be proven.

---

# 30. Architectural North Star

```text
                           AVA CLIENTS
                ┌──────────────┼──────────────┐
                │              │              │
               Web          Desktop        Mobile
                │              │              │
                └──────────────┼──────────────┘
                               │
                   Conversation / Context
                               │
                       AVA Application
                               │
                         RunService
                               │
                          AgentPort
                               │
                   Execution / Runtime Layer
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
       Native             OpenHands          Future Runtimes
                                                    │
                                      LangGraph / AgentCore
                               │
                       Model Orchestrator
                               │
                       Model Registry
                               │
                    Model Resource Manager
                               │
                 Model Provider / Inference
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
        Local          Company Hosted           External
```

Cross-cutting platform services:

```text
Persistence
Workspace Security
Tool Policy
Approval
Knowledge / RAG
Authentication
Authorization
Audit
Observability
Qualification
Plugin System
```

User-facing specialization:

```text
General AI
Software Engineering
Document Workflows
Engineering Standards
Manufacturing Workflows
Future Specialist Applications
```

All of these remain capabilities of **one AVA platform**.

---

# 31. Final Direction

The architectural foundation is now strong enough.

The priority is no longer to prove that AVA can support future models and runtimes.

The priority is to make AVA a complete application.

From Phase 4 forward, every major infrastructure change should answer one question:

> **What user-facing AVA capability does this enable now?**

If there is no strong answer, the work should normally remain deferred.
