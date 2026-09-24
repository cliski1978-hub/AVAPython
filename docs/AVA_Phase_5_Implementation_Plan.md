# AVA Python — Phase 5 Implementation Plan

**Phase:** 5  
**Title:** Production Configuration, Conversation & Run Experience  
**Status:** Planning Complete — Implementation Not Started  
**Predecessor:** Phase 4 — Durable Application State  
**Source Authority:** AVA Canonical Architectural Implementation Plan + Phase 4 Closure/Handoff  
**Implementation Style:** One bounded step at a time, validate, document, STOP

---

# 1. Purpose

Phase 5 turns AVA's durable application foundation into a production-ready AI interaction platform.

Phase 4 established durable application state for:

- conversations
- messages
- runs
- run events
- documents
- document revisions
- attachment metadata

Phase 5 builds on that foundation in two tightly related areas:

1. **Production configuration of model providers, provider connections, models, agent runtimes, and execution defaults**
2. **Production conversation, context, run, streaming, reconnect, recovery, cancellation, and error behavior**

The configuration work must come first inside Phase 5 because the production conversation system should consume authoritative AVA-managed configuration rather than continue depending primarily on temporary environment-variable bootstrap assumptions.

Phase 5 does **not** change the roadmap numbering. It expands the existing Phase 5 scope to include the configuration foundation required by production conversation execution.

---

# 2. AVA Architectural North Star

AVA remains the application platform.

Models, runtimes, providers, tools, persistence technologies, user interfaces, and future knowledge systems are replaceable components behind AVA-owned contracts.

The following architectural invariants remain mandatory:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Model ≠ Inference Runtime
Provider ≠ Provider Connection
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

The stable execution boundary remains:

```text
RunService
    ↓
AgentPort
```

`RunService` must not directly depend on:

- concrete model providers
- concrete agent runtimes
- model registry implementation details
- model orchestrator implementation details
- GPU/resource-manager implementation details
- workspace resolution internals
- tool-policy internals
- inference-runtime SDKs

Model selection must never widen:

- filesystem authority
- workspace authority
- shell authority
- network authority
- tool permissions
- credentials

AVA owns all public application contracts.

Vendor/framework-specific types remain behind adapters.

Web and Desktop remain thin shells.

Shared frontend packages remain the implementation center.

No additional frontend state library is introduced.

---

# 3. Current State Entering Phase 5

Phase 4 is complete.

AVA currently has durable relational persistence using SQLite for local development and testing, with in-memory alternatives retained for tests/development.

Current persisted domains include:

```text
conversations
messages
runs
run_events
documents
document_revisions
attachments metadata
```

Attachment bytes remain independently stored through `AttachmentContentStore`.

Current relevant configuration is still primarily bootstrap-oriented and includes environment values such as:

```text
AVA_AGENT_PROVIDER
AVA_AGENT_RUNTIME
AVA_MODEL_PROVIDER
AVA_MODEL_NAME
AVA_MODEL_ID
AVA_MODEL_HOSTING_MODE
AVA_LOCAL_MODEL_BASE_URL
```

The canonical architecture already supports:

- model-provider abstraction
- agent-runtime abstraction
- stable `model_id`
- separate `provider_id`
- separate `provider_model_name`
- model registry
- deterministic orchestration
- model resource leases
- local model support
- controlled OpenHands integration
- Web and Desktop shells
- shared TypeScript packages
- persisted runs and events

The system also already supports multi-model inventories through composition seams and tests.

However, production provider/model/runtime configuration is not yet a first-class AVA-managed application capability.

---

# 4. Phase 5 Objective

The Phase 5 objective is:

> Build the production configuration and conversation execution backbone that all later AVA capabilities depend on.

At Phase 5 completion:

- users/admins can configure provider connections, models, runtimes, and defaults through AVA
- normal application execution no longer depends solely on static `.env` model/provider selection
- conversations can be reopened and continued reliably
- active runs can be reconciled after refresh/reconnect
- streaming output is durable and replayable
- partial assistant output is handled correctly
- cancellation is durable
- retry/regenerate works across persisted history
- stale events cannot corrupt visible state
- Web and Desktop observe the same authoritative backend state
- the system remains ready for later tools, RAG, identity, enterprise providers, voice, audit, and multi-model orchestration without architectural rework

---

# 5. Phase 5 Architecture

The target high-level architecture is:

```text
AVA Settings / Configuration
        │
        ├── Provider Connections
        ├── Models
        ├── Agent Runtimes
        └── Defaults
                │
                ▼
Execution Configuration Resolver
                │
                ▼
Conversation / Run Layer
                │
                ▼
RunService
                │
                ▼
AgentPort
                │
                ▼
ExecutionSelector
                │
                ▼
Model Orchestrator
                │
                ▼
Model Registry / Model Profile
                │
                ▼
Configured Model Binding
                │
                ▼
Runtime / Provider Execution
```

For live execution events:

```text
Runtime / Provider Events
        ↓
AVA Normalized Run Events
        ↓
Persistent Run Event Store
        ↓
Streaming Transport
        ↓
@ava/api-client
        ↓
agent-ui / workspace state
```

Backend state remains authoritative.

Frontend state remains interaction/cache state.

---

# 6. Configuration Architecture

## 6.1 Provider vs Provider Connection

AVA must explicitly distinguish a provider implementation from a configured connection.

Example:

```text
Provider Adapter
    OpenAI-compatible adapter

Provider Connections
    Local Ollama
    Bizon vLLM
    Stellantis AI Gateway
    Databricks Model Serving
```

One provider adapter may support multiple configured connections.

This distinction prevents endpoint, credential, or deployment configuration from becoming incorrectly embedded into provider identity.

---

## 6.2 Proposed Provider Connection Domain

A provider connection should conceptually include:

```text
ProviderConnection
    connection_id
    provider_id
    display_name
    endpoint / base_url
    enabled
    credential_reference
    connection configuration
    created_at
    updated_at
```

Exact contract fields must be finalized after inspecting the existing provider architecture.

Raw secrets should not be stored casually in ordinary settings records.

AVA should store a credential reference where possible.

Development may initially support environment-backed credential references.

Future enterprise secret backends may include:

- corporate secret stores
- AWS Secrets Manager
- Azure Key Vault
- Databricks secrets
- other approved enterprise credential systems

Secret storage technology must remain replaceable.

---

## 6.3 Model Configuration Domain

AVA already owns stable model identity.

A production model configuration should conceptually preserve:

```text
Model
    model_id
    provider_connection_id
    provider_model_name
    display_name
    hosting_mode
    enabled
    context_window
    capabilities
    metadata
```

The model record must remain distinct from:

```text
provider_id
provider_connection_id
provider_model_name
```

One provider connection may expose multiple models.

One provider type may have multiple provider connections.

---

## 6.4 Agent Runtime Configuration

Agent runtimes remain independent from model providers.

Conceptually:

```text
AgentRuntimeConfiguration
    runtime_id
    runtime_type
    display_name
    enabled
    configuration
```

Possible runtimes over the lifetime of AVA include:

- Native AVA
- OpenHands
- LangGraph
- AWS AgentCore
- future runtime adapters

Phase 5 does not require implementation of every future runtime.

It does require that the configuration architecture not statically tie any runtime to a model or provider.

---

## 6.5 Application Defaults

AVA should support persisted defaults such as:

```text
default_provider_connection_id
default_model_id
default_runtime_id
```

These defaults establish the standard execution profile used when no explicit user/runtime/model choice overrides them.

Defaults must reference valid enabled configuration.

Invalid or disabled references must not silently execute.

---

## 6.6 Environment Configuration Role

`.env` remains useful for:

- bootstrap
- local development
- emergency fallback
- initial database/storage setup
- secret references
- first-run configuration

It should not remain the long-term primary source of normal application model/provider/runtime configuration.

Target direction:

```text
Environment
    ↓
Bootstrap / fallback configuration

Persisted AVA Configuration
    ↓
Authoritative application execution configuration
```

---

# 7. Conversation and Context Architecture

## 7.1 Durable History vs Run Context

AVA must distinguish:

```text
Durable Conversation History
        ≠
Execution Context
```

A conversation may contain more durable history than a model can receive in one request.

Phase 5 should establish a context construction seam without pulling future RAG or advanced summarization into this phase.

Conceptually:

```text
Conversation
    ↓
Ordered durable messages
    ↓
Active-response selection
    ↓
Context policy
    ↓
Context budget
    ↓
Execution context
    ↓
Run
```

The implementation should remain deterministic.

Future RAG, summarization, voice, and orchestration can later contribute context through this seam.

---

## 7.2 Conversation / Run Relationships

Phase 5 must normalize the durable relationship among:

```text
Conversation
User Message
Run
Assistant Message
Run Events
```

The architecture should be able to answer:

- which user message caused a run?
- which run produced an assistant response?
- which assistant responses belong to the same turn?
- which response is currently active?
- which run superseded another run?
- which events belong to which run?

The exact minimal schema change should be determined during the architecture audit.

Do not add redundant foreign keys unless they are needed.

---

## 7.3 Regenerate History

Existing Phase 4 behavior must be preserved.

Durable history may contain:

```text
U1
A1
A2
A3
```

while the normal transcript shows:

```text
U1
A3
```

Historical regenerate responses remain durable.

Do not delete durable history merely to simplify rendering.

---

# 8. Streaming Architecture

Streaming must flow through AVA-owned normalized run events.

Do not create direct runtime-to-React streaming paths.

Target architecture:

```text
Runtime / Provider
        ↓
Normalized AVA Run Event
        ↓
Persistent Event Store
        ↓
Streaming Transport
        ↓
API Client
        ↓
Frontend State
        ↓
Visible Partial Response
```

This allows:

- event replay
- reconnect
- refresh recovery
- future audit
- future voice
- Web/Desktop consistency
- runtime independence

---

## 8.1 Event Ordering

Run events need stable deterministic ordering.

Conceptually:

```text
run_id
sequence_number
event_id
event_type
timestamp
payload
```

Exact implementation may differ depending on the current persisted event schema.

A reconnecting client must be able to request or resume after a known event position.

---

## 8.2 Partial Assistant Responses

The frontend must distinguish between:

```text
partial assistant response
completed assistant response
failed assistant response
cancelled assistant response
```

Partial output must not be falsely treated as completed durable conversation history until the backend state says it is complete.

The backend remains authoritative.

---

# 9. Run Lifecycle

Phase 5 should define and test a normalized run lifecycle.

Minimum expected states:

```text
CREATED
RUNNING
COMPLETED
FAILED
CANCELLED
```

If cancellation is asynchronous, an intermediate state such as:

```text
CANCELLING
```

may be warranted.

The audit should determine whether such a state is actually needed.

Cancellation must be durable state, not merely a transient UI command.

---

# 10. Recovery and Reconciliation

Phase 5 must define behavior for:

- UI refresh during a run
- temporary network disconnect
- browser reconnect
- Desktop restart
- backend restart
- late run event arrival
- stale run completion
- regenerate while prior history exists
- conversation reopen
- multiple clients viewing the same conversation
- provider failure
- runtime failure
- connection endpoint failure

The backend remains the source of truth.

Clients must reconcile by stable IDs and event ordering.

Do not deduplicate messages by text.

---

# 11. Connectivity Semantics

Preserve the Phase 4 rule:

Transport failure:

```text
fetch failure
connection refused
timeout
backend unreachable
```

means:

```text
Disconnected / Unavailable
```

Ordinary HTTP responses:

```text
400
404
409
500
```

mean the backend was reachable even though the request failed.

A later successful backend request restores Connected state.

`@ava/api-client` classifies transport/result state.

The application/workspace layer owns visible connectivity state.

---

# 12. Concurrency Policy

Phase 5 must explicitly define conversation-level run concurrency.

Recommended initial rule:

```text
One active run per conversation
```

Different conversations may run concurrently.

If a user attempts to submit another prompt while a conversation already has an active run, AVA should behave deterministically.

The exact UX may be:

- reject with visible state
- disable send until completion
- optionally support stop/cancel

Do not introduce queued or parallel runs inside one conversation unless a validated requirement exists.

Parallel execution within one conversation may be added later if needed.

---

# 13. Phase 5 Non-Goals

Do not pull the following into Phase 5 unless an implementation blocker proves they are required:

- full normalized tool framework
- approval framework
- RAG/vector database
- engineering knowledge ingestion
- engineering workflows
- authentication
- enterprise SSO
- per-user ownership
- enterprise authorization
- full LangGraph integration
- full AWS AgentCore integration
- Databricks persistence adapter
- SQL Server persistence adapter
- production audit platform
- full observability platform
- phase-aware multi-model execution
- adaptive routing
- learned routing
- model qualification platform
- specialist-model training
- plugin marketplace
- mobile production work
- voice UI
- advanced automatic summarization
- microservice decomposition

Phase 5 may create seams that future phases use, but it must not implement those future phases prematurely.

---

# 14. Phase 5 Implementation Sequence

Each step must follow this workflow:

1. inspect current implementation
2. make only the bounded change
3. run targeted tests
4. update relevant documentation
5. report results
6. STOP

Do not automatically continue into the next numbered step.

---

## 5.1 — Provider / Model / Runtime Architecture Audit

### Goal

Inspect all current provider, model, runtime, orchestration, registry, and configuration paths before defining new settings contracts.

### Inspect

- application settings/configuration
- model-provider ports
- provider adapters
- model registry
- model profiles
- stable model identity
- execution selector
- model orchestrator
- configured model binding
- model resource manager
- runtime registry/selection
- Native AVA runtime
- OpenHands integration
- `/models`
- `/model-providers`
- `/runtimes`
- `/execution-profiles`
- current frontend selectors/configuration
- bootstrap/environment composition

### Deliverable

A current-state dependency map.

### Acceptance Criteria

- existing configuration path documented
- ownership of model/provider/runtime config identified
- no duplicate concept introduced
- gaps identified before contract changes

### STOP

---

## 5.2 — Define Provider Connection Domain

### Goal

Introduce AVA-owned provider connection semantics.

### Determine

- provider vs provider connection ownership
- connection identity
- endpoint ownership
- connection-specific configuration
- enabled state
- credential-reference handling
- validation rules

### Likely Areas

- backend domain/contracts
- configuration/application ports
- persistence contracts
- shared API contracts

### Tests

- domain validation
- identity uniqueness
- disabled connection behavior
- invalid endpoint/config handling

### Acceptance Criteria

Provider connections can be represented without embedding vendor SDK types or raw secrets in Core contracts.

### STOP

---

## 5.3 — Persist Provider Connections

### Goal

Add durable provider connection storage.

### Requirements

- repository port
- in-memory repository
- relational repository
- schema migration
- deterministic ordering
- restart durability

### Tests

- repository contract tests
- SQLite integration tests
- migration tests
- restart persistence

### Acceptance Criteria

Provider connections survive backend restart and services remain database-neutral.

### STOP

---

## 5.4 — Define Persisted Model Configuration

### Goal

Move production model inventory toward AVA-managed configuration.

### Preserve

```text
model_id
provider_connection_id
provider_model_name
hosting_mode
```

### Consider

- display name
- enabled
- capabilities
- context window
- metadata

### Do Not

- collapse provider and model identity
- use provider model name as AVA model identity

### Tests

- provider connection association
- stable ID behavior
- disabled model behavior
- duplicate validation

### STOP

---

## 5.5 — Persist Model Configuration

### Goal

Add durable model inventory storage.

### Requirements

- repository port
- memory implementation
- relational implementation
- migration
- bootstrap compatibility

### Acceptance Criteria

Configured models survive restart and existing environment bootstrap remains usable.

### STOP

---

## 5.6 — Runtime Configuration Domain

### Goal

Represent AVA agent runtime configuration independently from model/provider configuration.

### Requirements

- runtime identity
- runtime type
- display name
- enabled state
- runtime-specific configuration behind AVA-owned contracts

### Acceptance Criteria

No runtime configuration statically binds a runtime to a particular model/provider.

### STOP

---

## 5.7 — Persist Runtime Configuration

### Goal

Make runtime configuration durable.

### Requirements

- repository abstraction
- memory implementation
- relational implementation
- migration
- restart durability

### STOP

---

## 5.8 — Application Execution Defaults

### Goal

Persist default execution selections.

### Initial Defaults

```text
default_provider_connection_id
default_model_id
default_runtime_id
```

### Rules

- references must exist
- referenced config must be enabled
- invalid defaults fail visibly
- bootstrap fallback is deterministic

### STOP

---

## 5.9 — Credential Reference Strategy

### Goal

Prevent provider secrets from becoming ordinary persisted settings.

### Phase 5 Scope

Define and implement the minimal supported credential-reference mechanism.

Possible initial approach:

```text
credential_reference = environment variable key
```

Future secret-store support remains pluggable.

### Acceptance Criteria

- no secret value is exposed through normal settings APIs
- no secret value is sent to frontend
- no secret value appears in ordinary persisted configuration

### STOP

---

## 5.10 — Settings API

### Goal

Expose AVA-owned configuration management through backend APIs.

### Capabilities

- list provider connections
- create provider connection
- update provider connection
- enable/disable provider connection
- list models
- create/update model configuration
- enable/disable model
- list runtime configs
- create/update runtime config
- enable/disable runtime
- get/update defaults
- validate configuration
- test provider connection where supported

### Requirements

- vendor-neutral public contracts
- deterministic validation
- no raw secret exposure

### STOP

---

## 5.11 — Settings UI Foundation

### Goal

Add a first-class Settings experience shared by Web and Desktop.

### Initial Sections

```text
Settings
├── Providers / Connections
├── Models
├── Runtimes
└── Defaults
```

### Requirements

- shared package implementation
- thin Web/Desktop shells
- no additional state library
- clear save/error/loading states
- connection-test feedback
- disabled-state visibility

### STOP

---

## 5.12 — Provider Connection Management UI

### Goal

Allow creation and editing of provider connections.

### UX

- provider type
- display name
- endpoint/base URL
- credential reference
- enabled state
- connection test
- status/result feedback

### STOP

---

## 5.13 — Model Management UI

### Goal

Allow configuration of models available through provider connections.

### UX

- model display name
- stable AVA model ID
- provider connection
- provider model name
- hosting mode
- enabled
- context/capability metadata where supported

### STOP

---

## 5.14 — Runtime Management UI

### Goal

Allow runtime configuration without coupling runtime choice to model/provider choice.

### STOP

---

## 5.15 — Defaults UI

### Goal

Allow selection of default:

- provider connection
- model
- runtime

### Validation

Prevent selection of incompatible, missing, or disabled entries.

### STOP

---

## 5.16 — Execution Configuration Resolver

### Goal

Create the application-layer mechanism that resolves authoritative execution configuration before execution.

Conceptual path:

```text
Run Request
    ↓
Execution Configuration Resolver
    ↓
Runtime configuration
Model configuration
Provider connection
    ↓
existing execution architecture
    ↓
RunService → AgentPort
```

### Critical Rule

Do not inject provider/runtime/model dependencies into `RunService`.

### STOP

---

## 5.17 — Configuration Bootstrap / Migration Compatibility

### Goal

Ensure existing `.env` development setups still work.

### Required Behavior

If no persisted configuration exists:

```text
environment bootstrap
    ↓
construct initial usable configuration
```

The exact behavior should be deterministic and documented.

### STOP

---

## 5.18 — Production Conversation Architecture Audit

### Goal

Now that execution configuration is authoritative, inspect the conversation/run path.

### Inspect

- conversation domain
- message domain
- run domain
- run event domain
- RunService
- AgentPort
- frontend conversation state
- run state/provider
- API client
- run/event endpoints
- MockAgentAdapter
- current context assembly
- current message/run associations
- persistence repositories
- recovery behavior
- current streaming support

### Deliverable

Production conversation gap map.

### STOP

---

## 5.19 — Normalize Conversation / Run Relationships

### Goal

Establish explicit durable execution causality.

### Determine Minimal Relationships

```text
Conversation
    ↓
User Message
    ↓
Run
    ↓
Assistant Response
```

### Requirements

- preserve existing regenerate history
- minimize schema duplication
- stable relationships after restart
- frontend should not need fragile inference where backend can provide truth

### STOP

---

## 5.20 — Message Status Normalization

### Goal

Define stable message lifecycle/state semantics.

Possible concepts:

```text
pending
streaming
completed
failed
cancelled
superseded
```

Do not adopt states unless required by actual behavior.

### STOP

---

## 5.21 — Context Construction Service

### Goal

Make context assembly an explicit AVA-owned application concern.

### Conceptual Inputs

- conversation
- ordered messages
- active assistant-response selection
- model context limits
- deterministic context policy

### Non-Goals

- RAG
- semantic retrieval
- advanced learned summarization

### STOP

---

## 5.22 — Context Window Management

### Goal

Prevent durable conversation history from being blindly equated with model input context.

### Requirements

- deterministic budget calculation
- preserve recent relevant conversation turns
- predictable truncation behavior
- model-specific context capacity support
- no hidden data loss from persisted conversation history

### STOP

---

## 5.23 — Run Lifecycle Normalization

### Goal

Formalize durable run-state transitions.

### Minimum

```text
CREATED
RUNNING
COMPLETED
FAILED
CANCELLED
```

Determine whether `CANCELLING` is necessary.

### Tests

- legal transitions
- illegal transitions
- restart behavior
- stale transition rejection

### STOP

---

## 5.24 — Durable Run Cancellation

### Goal

Ensure cancellation survives UI refresh/restart and is reflected in authoritative state.

### Requirements

- cancel API semantics
- persisted cancellation state
- runtime cancellation forwarding
- frontend state reconciliation
- late completion suppression

### STOP

---

## 5.25 — Streaming Transport Contract

### Goal

Define AVA's streaming transport without bypassing persistent events.

### Requirements

- normalized event stream
- stable event ordering
- reconnect cursor/position
- API client support
- runtime-neutral transport contract

### Technology Choice

Select SSE, WebSocket, or another suitable transport only after inspecting current implementation.

The architecture matters more than the specific transport.

### STOP

---

## 5.26 — Persisted Event Sequence / Replay

### Goal

Make event history replayable after reconnect.

### Requirements

- stable event order
- client resume point
- replay after reconnect
- no duplicate visible output
- no missing completed output

### STOP

---

## 5.27 — Partial Assistant Response Rendering

### Goal

Render streaming assistant output safely.

### Requirements

- partial response visible
- partial response reconciled with backend
- completion finalizes response
- failure does not fabricate completed assistant history
- refresh/reconnect reconstructs correct visible state

### STOP

---

## 5.28 — Reconnect / Resume

### Goal

Recover live conversation state after temporary transport interruption.

### Scenarios

- network interruption
- browser tab sleep/wake
- UI refresh
- Desktop reconnect

### Requirements

- determine current run state
- replay missed events
- resume visible response
- avoid duplicate output
- update connectivity state correctly

### STOP

---

## 5.29 — Run Recovery After Refresh

### Goal

Allow UI refresh while a run exists.

### Required Outcome

After reload AVA can determine whether the run:

- completed
- failed
- cancelled
- remains active
- needs event replay

### STOP

---

## 5.30 — Backend Restart Recovery Semantics

### Goal

Define what happens to runs that were active when the backend process stops.

### Required Decision

AVA must explicitly classify unrecoverable in-progress executions rather than leave them indefinitely RUNNING.

Possible strategy:

```text
RUNNING at startup
    ↓
mark interrupted / failed
```

The exact status model should come from the audit.

### STOP

---

## 5.31 — Retry / Regenerate Across Persisted Runs

### Goal

Prove regenerate behavior continues to work with the finalized run/message/event model.

### Preserve

```text
Durable:
U1 → A1 → A2 → A3

Visible:
U1 → A3
```

### Tests

- regenerate live
- regenerate after refresh
- regenerate after restart
- multiple regenerates
- stale prior completion
- event replay

### STOP

---

## 5.32 — Stale Event Protection

### Goal

Generalize stale-run protection beyond the current regenerate-specific cases.

### Requirements

Late events from a superseded or no-longer-active run must not overwrite the currently active visible response.

### STOP

---

## 5.33 — Conversation-Level Concurrency Rules

### Goal

Enforce deterministic run concurrency.

### Initial Rule

```text
one active run per conversation
```

### Tests

- duplicate send attempts
- rapid user submits
- cancellation followed by new run
- different conversations executing concurrently

### STOP

---

## 5.34 — Failure and Error UX

### Goal

Ensure production-grade visible handling of:

- provider unavailable
- provider authentication failure
- invalid model config
- runtime failure
- model unavailable
- stream interruption
- backend transport failure
- cancellation failure
- context-construction failure
- replay failure

### Rules

- no fabricated assistant response
- no false success
- preserve recoverable user input
- transport status remains accurate
- backend error details remain appropriately normalized

### STOP

---

## 5.35 — Configuration Failure Integration

### Goal

Tie provider/model/runtime configuration health into normal run execution.

### Examples

If default model is disabled:

```text
run does not silently fall back
```

unless an explicit deterministic fallback policy exists.

If provider connection is invalid:

```text
run fails visibly with configuration-related error
```

Do not hide configuration defects through undocumented routing.

### STOP

---

## 5.36 — Web Acceptance

### Goal

Manually validate the complete production interaction path in Web.

### Verify

- Settings management
- connection testing
- model selection/defaults
- conversation creation
- streaming
- cancellation
- retry/regenerate
- refresh recovery
- reconnect
- restart durability
- error states
- no console regressions

### STOP

---

## 5.37 — Desktop Acceptance

### Goal

Confirm the Desktop shell observes identical backend truth.

### Verify

- same settings
- same provider/model/runtime inventory
- same conversations
- same run state
- same event history
- same recovery behavior
- same errors
- same durability

### STOP

---

## 5.38 — Restart / Durability Integration Test

### Goal

Prove persisted configuration and conversation/run state survive restart together.

### Test

1. configure provider/model/runtime/defaults
2. create conversation
3. execute run
4. restart backend
5. reopen conversation
6. confirm configuration still exists
7. confirm run/message/event history
8. execute new run
9. restart again
10. confirm all state

### STOP

---

## 5.39 — Race / Concurrency Hardening

### Goal

Exercise edge cases intentionally.

### Cases

- cancel while final event arrives
- refresh during stream
- reconnect during stream
- regenerate while prior events arrive
- provider failure mid-stream
- backend restart mid-run
- two clients open same conversation
- rapid settings update followed by run
- model disabled while another conversation is using it
- duplicate replay request
- stale connectivity update

### STOP

---

## 5.40 — Full Validation

Run:

```text
Backend tests
Ruff
mypy

Python client tests
Python client Ruff
Python client strict mypy

Frontend package tests
TypeScript validation

Web build
Desktop build

./scripts/test_all.sh
git diff --check
```

Phase-specific integration tests must pass.

### STOP

---

## 5.41 — Phase 5 Documentation / Closure

### Produce

- Phase 5 implementation log
- Phase 5 developer guide
- Phase 5 architecture diagrams
- configuration model documentation
- conversation/run lifecycle documentation
- streaming/reconnect documentation
- migration notes
- manual acceptance report
- updated canonical architectural plan

### STOP

Phase 5 is complete only after documentation and validation are complete.

---

# 15. Phase 5 Test Strategy

## 15.1 Unit Tests

Cover:

- provider connection validation
- model identity
- model/provider association
- runtime configuration validation
- defaults validation
- execution configuration resolution
- context construction
- context-window budgeting
- run-state transitions
- event ordering
- active-response selection
- stale-event rejection
- cancellation
- connectivity classification

---

## 15.2 Repository Tests

For each new persisted configuration domain:

- memory implementation
- relational implementation
- shared contract behavior
- deterministic ordering
- create/get/list/update
- invalid state behavior
- restart persistence

---

## 15.3 API Tests

Cover:

- configuration CRUD
- defaults
- validation
- connection tests
- run creation
- cancellation
- run status
- events
- streaming
- reconnect/replay
- errors

---

## 15.4 Persistence / Restart Tests

Verify:

- settings survive restart
- provider connections survive restart
- models survive restart
- runtime settings survive restart
- defaults survive restart
- conversations survive restart
- messages survive restart
- runs survive restart
- events survive restart
- regenerate history survives restart

---

## 15.5 Streaming Tests

Verify:

- ordered events
- partial output
- completion
- failure
- cancellation
- reconnect
- missed-event replay
- duplicate-event protection
- stale-event protection

---

## 15.6 Concurrency Tests

Verify:

- one active run per conversation
- different conversations can execute concurrently
- duplicate send prevention
- cancel/start race
- completion/cancel race
- regenerate/stale event race

---

## 15.7 UI Acceptance

Validate on Web and Desktop:

- settings
- provider connection configuration
- model configuration
- runtime configuration
- defaults
- connection test
- new conversation
- reopen conversation
- streaming
- cancellation
- retry
- regenerate
- offline behavior
- reconnect
- refresh
- backend restart
- error recovery

---

# 16. Schema / Migration Expectations

Phase 5 will likely require schema changes for:

- provider connections
- model configuration
- runtime configuration
- application execution defaults
- possible run/message relationship normalization
- possible event sequence/replay metadata
- possible normalized run state/status additions

Do not create all tables upfront without confirming the exact domain model during each bounded implementation step.

Every migration must be:

- version controlled
- forward deterministic
- testable against empty database
- testable against Phase 4 database
- compatible with restart behavior

---

# 17. Security Requirements

Phase 5 configuration introduces additional security considerations.

Mandatory rules:

- raw credentials are not returned to clients
- provider secrets are not logged
- provider secrets are not normal model metadata
- connection testing must not leak secret values
- model selection does not widen permissions
- runtime selection does not widen permissions
- configuration does not bypass workspace or tool policy
- vendor SDK objects do not enter AVA public contracts

Enterprise authorization remains a later phase.

Phase 5 should not prematurely implement multi-user permissions.

---

# 18. Future Compatibility Requirements

Phase 5 must leave clean seams for:

## Tool / Approval Framework

Future tools consume run/context infrastructure without changing configuration identity.

## Knowledge / RAG

Future retrieved context enters through the context-construction layer rather than bypassing it.

## Engineering Workflows

Future engineering workflows remain capabilities inside AVA, not separate applications.

## Authentication / Authorization

Future users and permissions can scope access to:

- provider connections
- models
- runtimes
- workspaces
- tools
- documents
- configuration

## Corporate Providers

Company gateways, Databricks, and future enterprise providers plug into provider adapters and provider connections.

## Observability / Audit

Run events and configuration identity remain suitable for later tracing/audit.

## Multi-Model Execution

Future phase-aware model switching can select from the same model/provider configuration system.

## Voice

Voice should consume the same authoritative conversation/context/run state rather than maintain a separate stale copy.

---

# 19. Phase 5 Exit Criteria

Phase 5 is complete only when all of the following are true.

## Configuration

```text
✓ Provider connections are AVA-managed and durable
✓ Models are AVA-managed and durable
✓ Agent runtime configuration is AVA-managed and durable
✓ Defaults are persisted
✓ Provider and provider connection are distinct concepts
✓ Model ID remains separate from provider model name
✓ Runtime remains independent from provider/model
✓ Normal settings APIs do not expose raw secrets
✓ Settings UI works in Web and Desktop
✓ Connection/configuration failures are visible
✓ Existing environment bootstrap remains supported
```

## Conversation / Context

```text
✓ Conversation history remains durable
✓ Conversation reopening works
✓ Context construction is explicit
✓ Context-window policy is deterministic
✓ Regenerate history remains durable
✓ Active response is reconstructed correctly
```

## Runs

```text
✓ Run/message relationships are authoritative
✓ Run lifecycle is normalized
✓ Cancellation is durable
✓ Run recovery after refresh works
✓ Active-run backend restart behavior is defined
✓ One-active-run-per-conversation policy is enforced
```

## Streaming / Events

```text
✓ Streaming transport uses AVA normalized events
✓ Events remain persisted
✓ Partial assistant output renders correctly
✓ Event replay works
✓ Reconnect works
✓ Missed events can be recovered
✓ Duplicate visible output is prevented
✓ Stale events cannot overwrite current state
```

## Failure Handling

```text
✓ Transport failure updates connectivity correctly
✓ HTTP errors do not falsely mark backend disconnected
✓ Provider failure is visible
✓ Runtime failure is visible
✓ Model configuration failure is visible
✓ No fabricated assistant responses
✓ User state is preserved when recovery is possible
```

## Platform

```text
✓ Web passes acceptance
✓ Desktop passes acceptance
✓ Web/Desktop share the same backend truth
✓ Backend restart durability passes
✓ Full validation passes
✓ Documentation is updated
✓ Canonical architectural plan is updated
```

---

# 20. Explicit Phase 5 Completion Statement

Phase 5 should not be declared complete merely because:

- settings contracts exist
- a Settings screen exists
- streaming works in one happy-path demo
- events are persisted
- a cancel button exists

Phase 5 is complete only when the **real execution path** has been proven end-to-end:

```text
Configured Provider / Model / Runtime
        ↓
Execution Configuration Resolution
        ↓
Conversation Context
        ↓
Run
        ↓
AgentPort
        ↓
Runtime / Provider / Model
        ↓
Normalized Events
        ↓
Persistence
        ↓
Streaming
        ↓
Web / Desktop
        ↓
Refresh / Reconnect / Restart Recovery
```

with all architecture boundaries preserved.

---

# 21. Implementation Discipline

During Phase 5:

- inspect before editing
- implement one bounded step at a time
- run targeted tests after each step
- do not automatically proceed to the next step
- avoid broad refactors
- preserve Phase 4 persistence contracts unless a specific Phase 5 requirement proves change is necessary
- do not introduce a frontend state library
- do not couple runtime to provider/model
- do not bypass AVA contracts
- do not leak vendor-specific types into Core/public contracts
- do not pull future roadmap phases forward
- update documentation as architecture changes become real

---

# 22. Immediate Next Action

The first implementation action for Phase 5 should be:

```text
5.1 — Provider / Model / Runtime Architecture Audit
```

No production code should be written until the current configuration, provider, model, runtime, registry, orchestration, and bootstrap paths have been fully mapped.

The audit should determine the exact minimal set of new contracts and persistence records required before proceeding to `5.2`.

