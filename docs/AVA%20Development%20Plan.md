# AVA Development Plan

## 1. Purpose

AVA is a reusable AI application platform designed to support:

- Web applications
- Desktop applications
- Mobile applications
- Python clients
- Databricks notebooks
- Locally hosted AI models
- Company-hosted AI models
- Authorized external AI providers
- Replaceable agent frameworks
- Document-centered AI workflows
- Engineering-focused AI capabilities

The architecture should allow AVA to evolve without permanently tying the application to a particular:

- UI framework
- Agent framework
- Model provider
- Database
- Cloud provider
- AI runtime
- Deployment platform

The long-term principle is:

> AVA is the application platform. AI models, agents, tools, databases, and user interfaces are replaceable components attached to AVA through stable contracts.

---

# 2. Development Priorities

Client development priority will be:

1. Web
2. Desktop
3. Mobile

The three applications should reuse as much code as practical.

Shared frontend functionality should include:

- API contracts
- API client
- Application state
- Hooks
- Validation
- Agent interaction logic
- Theme definitions
- Reusable UI components
- Document operation models
- Business logic

Platform-specific code should remain inside thin application shells.

---

# 3. Architectural Pattern

AVA will use the following primary architectural patterns:

- Multi-application monorepo
- Modular monolith
- Hexagonal Architecture
- Ports and Adapters
- Dependency Inversion
- Contract-first APIs
- Shared frontend packages
- Platform-specific application shells
- Replaceable infrastructure adapters

High-level architecture:

```text
                 AVA CLIENT PLATFORM
                         │
          ┌──────────────┼──────────────┐
          │              │              │
         Web          Desktop         Mobile
          │              │              │
          └──────────────┼──────────────┘
                         │
                Shared Frontend
                         │
                    API Client
                         │
                       HTTP
                         │
                      FastAPI
                         │
                  AVA Application
                         │
                    AVA Core
                         │
             Application-Owned Ports
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
    Agents            Models          Persistence
       │                 │                 │
    Adapters          Adapters           Adapters
```

---

# 4. Phase 1 — Repository and Application Foundation

## Objective

Establish the permanent project structure before implementing major AVA functionality.

## Tasks

### 4.1 Create the monorepo

Establish directories for:

- Backend
- Shared frontend packages
- Web application
- Desktop application
- Mobile application
- Python client
- Tests
- Documentation
- Development scripts

### 4.2 Establish Python backend

Create the framework-neutral Python application foundation.

Initial backend packages should include:

- API
- Core
- Contracts
- Services
- Configuration
- Agents
- Model providers
- Infrastructure

### 4.3 Establish frontend workspace

Create shared packages for:

- UI core
- API client
- Contracts
- Document core
- Agent UI

### 4.4 Establish application shells

Create initial projects for:

- Web
- Desktop
- Mobile

Only Web receives active feature development initially.

Desktop and Mobile remain prepared for later implementation.

### 4.5 Establish basic FastAPI application

Create:

```text
GET /health
```

Expected result:

```json
{
  "status": "healthy",
  "application": "AVA"
}
```

### 4.6 Connect Web to backend

The Web application must call the backend through the shared API client.

Dependency path:

```text
Web
 ↓
Shared API Client
 ↓
FastAPI
 ↓
AVA Contracts
 ↓
AVA Core
```

## Completion Criteria

- Repository builds correctly.
- Python application runs.
- Web application runs.
- Web application can call `/health`.
- Tests execute successfully.
- Desktop shell exists.
- Mobile shell exists.
- Shared frontend packages exist.
- AVA Core contains no provider-specific dependencies.

---

# 5. Phase 2 — Shared Contracts and Ports

## Objective

Define the stable interfaces that the rest of AVA will use.

These contracts should be created before implementing real AI providers.

## Contracts

Create application-owned models for:

- Requests
- Responses
- Runs
- Events
- Messages
- Capabilities
- Errors
- Attachments
- Citations
- Approvals
- Document operations
- Tool calls
- Tool results

Contracts must:

- Be JSON compatible
- Be versioned
- Remain framework neutral
- Remain provider neutral
- Avoid vendor SDK objects

---

# 6. Phase 3 — Agent Adapter Contract

## Objective

Allow AVA to use different agent frameworks without modifying the core application.

Define an AVA-owned Agent Adapter port.

An Agent Adapter should eventually support:

- Start run
- Continue run
- Cancel run
- Stream events
- Supply tools
- Receive tool results
- Pause for approval
- Resume after approval
- Report capabilities
- Normalize errors

Conceptually:

```text
AVA Core
   │
Agent Port
   │
   ├── Mock Agent
   ├── LangGraph Agent
   ├── AWS Agent
   ├── Databricks Agent
   └── Future Agent
```

---

# 7. Phase 4 — Mock Agent

## Objective

Build deterministic AI-like behavior before introducing a real model.

The Mock Agent should support:

- Predictable responses
- Simulated streaming
- Simulated tool calls
- Simulated document changes
- Simulated approvals
- Simulated errors
- Deterministic test scenarios

This gives Web, Desktop, document, and workflow development a predictable backend.

## Completion Criteria

A client can:

1. Start a run.
2. Receive normalized AVA events.
3. Receive a completed result.
4. Test failure scenarios without using a real model.

---

# 8. Phase 5 — Model Provider Contract

## Objective

Separate model execution from agent execution.

Create an AVA-owned Model Provider port.

Providers should expose:

- Model identity
- Model capabilities
- Health
- Availability
- Text requests
- Structured requests
- Streaming
- Tool calling support
- Context limits
- Input limits
- Cancellation
- Usage information
- Normalized errors

Conceptually:

```text
AVA
 │
Model Provider Port
 │
 ├── Local Model Provider
 ├── Company Gateway Provider
 └── Authorized External Provider
```

Changing providers must be controlled by configuration rather than application rewrites.

---

# 9. Phase 6 — Local Model Support

## Objective

Allow AVA development to proceed without company AI gateway access.

The first real provider should be a locally hosted model.

## Initial Responsibilities

Create:

- Local provider adapter
- Local endpoint configuration
- Model configuration
- Health checks
- Capability checks
- Availability reporting
- Streaming support where available
- Local-only mode
- Resource reporting

## Initial Model Candidate

Begin evaluation using:

```text
Granite 4.2 3B Q4_K_M
```

Alternative:

```text
Ministral 3 3B Q4_K_M
```

The exact artifact must be validated before corporate distribution.

## Local Model Principle

Models should run from verified files stored on local storage.

Future corporate distribution pattern:

```text
Approved Model Registry
        ↓
Read-Only Network Share
        ↓
Local Model Manager
        ↓
Checksum / License Validation
        ↓
Local SSD Cache
        ↓
Local Runtime
```

Do not run model weights directly from a network share.

---

# 10. Phase 7 — Web Application Foundation

## Objective

Begin active development of the primary AVA interface.

Build the Web application shell.

Initial modules:

- Navigation
- Workspace
- Application layout
- Status indicators
- Error handling
- Shared theme
- Configuration
- Agent panel shell
- Document area shell

At this point the Web application should communicate with:

- Mock Agent
- Local model provider
- Capability endpoints

---

# 11. Phase 8 — Document Workspace

## Objective

Introduce AVA's first major user workspace.

Implement the document module.

Planned technology:

```text
Tiptap
```

Wrap Tiptap behind an AVA-owned document interface.

## Capabilities

Implement:

- Open document
- Edit document
- Save document
- Rich-text formatting
- Headings
- Paragraphs
- Lists
- Checklists
- Links
- Images
- Tables
- Undo
- Redo
- Selection tracking
- Structured document representation

Tiptap-specific commands must not escape into AVA Core.

---

# 12. Phase 9 — Agent Interface

## Objective

Allow the user to interact naturally with AVA.

Implement:

- Conversation panel
- Prompt input
- Streaming responses
- Run state
- Cancel run
- Conversation history
- Tool execution display
- Citations
- Error display
- Approval requests

The Agent UI should consume AVA events rather than framework-specific events.

---

# 13. Phase 10 — Agent-Driven Document Operations

## Objective

Allow AI to propose changes to documents safely.

Agents must not directly manipulate the editor.

Instead they produce neutral AVA operations.

Operations should support:

- Insert
- Replace
- Delete
- Format
- Add structured block
- Comment
- Annotation
- Multiple operations in one change set

Flow:

```text
Agent
 ↓
AVA Document Operation
 ↓
Validation
 ↓
User Review
 ↓
Accept / Reject
 ↓
Document Adapter
 ↓
Editor
```

---

# 14. Phase 11 — Review and Approval System

## Objective

Keep humans in control of consequential AI actions.

Implement:

- Proposed-change cards
- Before/after comparison
- Accept
- Reject
- Batch review
- Explanations
- Pending indicators
- Undo
- Review history

Every approval should eventually record:

- User
- Run
- Operation
- Decision
- Time

---

# 15. Phase 12 — Tool Framework

## Objective

Allow agents to perform controlled operations beyond text generation.

Create the AVA Tool Registry.

Each tool should define:

- Tool ID
- Description
- Input schema
- Output schema
- Permissions
- Execution handler
- Audit behavior
- UI renderer association

Potential future engineering tools:

- Search specification
- Analyze engineering document
- Compare requirements
- Read project data
- Analyze PLC export
- Query OPC UA data
- Generate report
- Search engineering standards

---

# 16. Phase 13 — Persistence

## Objective

Introduce durable application state.

Persistence must remain behind AVA-owned repository interfaces.

Initial storage domains:

- Documents
- Conversations
- Messages
- Runs
- Events
- Approvals
- Attachments
- Configuration
- Audit records

The initial implementation may use a local database while preserving the ability to replace storage later.

Persistence technology should not leak into AVA Core.

---

# 17. Phase 14 — Desktop Application

## Objective

Create the second production client after the Web interface becomes stable.

Preferred desktop shell:

```text
Tauri
```

Desktop should reuse:

- React UI
- Shared frontend packages
- API client
- Contracts
- Agent components
- Document components
- Theme
- Application state

Desktop-specific functionality may later include:

- Local filesystem access
- Native dialogs
- Local model management
- Desktop notifications
- Offline operation
- Local application integration

---

# 18. Phase 15 — Databricks Python Client

## Objective

Allow notebooks and Python applications to use AVA without running the browser UI.

Create a lightweight Python package:

```text
ava_client
```

Capabilities:

- Submit request
- Start run
- Check run status
- Retrieve results
- Submit document content
- Retrieve artifacts
- Approve action
- Reject action

Databricks notebooks should use the same contracts as the Web application.

---

# 19. Phase 16 — Corporate Agent and Model Adapters

## Objective

Connect AVA to approved corporate services without changing the application core.

Possible adapters:

- Company AI Gateway
- AWS agent platform
- Databricks agent
- Databricks Model Serving
- Authorized external AI provider

All provider authentication and vendor SDK usage stays inside adapters.

AVA Core must remain unchanged when providers change.

---

# 20. Phase 17 — Authentication and Authorization

## Objective

Introduce application security and user permissions.

Capabilities:

- Identity provider abstraction
- User identity
- Roles
- Document permissions
- Tool permissions
- Agent permissions
- Token validation
- Session expiration
- Approval identity
- Audit identity

The client must never be trusted to declare authorization.

Authorization is enforced by the backend.

---

# 21. Phase 18 — Observability and Reliability

## Objective

Make AVA suitable for long-running and production workloads.

Implement:

- Structured logs
- Request correlation IDs
- Agent tracing
- Tool tracing
- Execution timing
- Error reporting
- Retry policies
- Timeout policies
- Cancellation
- Usage metrics
- Provider health reporting

---

# 22. Phase 19 — Plugin Architecture

## Objective

Allow capabilities to be added without modifying the AVA application shell.

Planned plugin management layer:

```text
Cordis
```

Plugin capabilities may eventually include:

- UI modules
- Tools
- Renderers
- Integration adapters
- Configuration modules
- Document capabilities
- Application-specific functionality

Initial possible plugins:

- Document plugin
- Agent UI plugin
- Review plugin
- File browser plugin
- Citation viewer
- Tool result renderers
- AWS integration
- Databricks integration
- Corporate configuration

Plugin development should begin only after core contracts are stable.

---

# 23. Phase 20 — Mobile Application

## Objective

Create the third AVA client after Web and Desktop architecture are mature.

Mobile should maximize reuse of:

- API contracts
- API client
- State
- Hooks
- Validation
- Agent logic
- Business logic
- Theme tokens

Mobile-specific UI should be created only where platform differences require it.

Potential mobile capabilities:

- Agent conversations
- Document review
- Approval workflows
- Notifications
- Lightweight document access
- Engineering lookup
- Remote task monitoring

Full desktop-style document editing may not be required on mobile.

---

# 24. Phase 21 — First Engineering Workflow

## Objective

Move AVA from a general platform into a useful engineering AI system.

Recommended first workflow:

# Requirements Review Agent

Example:

```text
Engineering Document
        +
Applicable Standards
        ↓
AVA
        ↓
Retrieve Relevant Requirements
        ↓
Compare Requirements
        ↓
Identify Conflicts / Missing Items
        ↓
Generate Proposed Findings
        ↓
Engineer Review
        ↓
Accept / Reject
```

This workflow should validate:

- Documents
- RAG
- Agent orchestration
- Tools
- Citations
- Approvals
- Structured results

---

# 25. Phase 22 — Knowledge and RAG

## Objective

Provide AVA access to controlled engineering knowledge.

Capabilities:

- File ingestion
- Text extraction
- Chunking
- Embeddings
- Search
- Retrieval
- Citations
- Source tracking
- Metadata
- Document permissions

RAG infrastructure must remain replaceable.

AVA should not permanently depend on one vector database.

---

# 26. Phase 23 — Model Routing

## Objective

Allow AVA to select the best model for a task.

Initial routing may use software rules.

Example:

```text
User Request
      ↓
AVA Router
      ↓
Classify Request
      ↓
 ┌────┼──────────┐
 │    │          │
Code General Engineering
 │    │          │
Model Model    Expert Model
```

Model capability metadata should influence routing decisions.

---

# 27. Phase 24 — Specialist Model Architecture

## Objective

Explore the long-term AVA architecture based on multiple specialized models.

Concept:

```text
                      AVA Router
                          │
          ┌───────────────┼───────────────┐
          │               │               │
       General          Coding        Engineering
                                          │
                              ┌───────────┼───────────┐
                              │           │           │
                             PLC        Specs      Robotics
```

The goal is not necessarily one enormous general-purpose model.

AVA may eventually coordinate a hierarchy of smaller expert models.

---

# 28. Phase 25 — Model Evaluation and Training Research

## Objective

Create an experimental environment for evaluating and eventually producing specialized AVA models.

Research areas:

- Small language models
- Quantization
- Domain fine-tuning
- Model evaluation
- Router models
- Expert models
- Model benchmarking
- Automated test generation
- Training-data generation
- Synthetic data
- Model comparison
- Capability scoring

This phase is experimental and should remain isolated from AVA production architecture.

---

# 29. Phase 26 — Automated Model Evolution Research

## Objective

Explore whether AVA can assist with creating, testing, and improving specialized models.

Potential research loop:

```text
Baseline Model
      ↓
AVA Research Agent
      ↓
Generate Modification / Training Experiment
      ↓
Sandbox
      ↓
Evaluate
      ↓
Compare Against Baseline
      ↓
Accept / Reject Experiment
      ↓
Next Iteration
```

This is a long-term research direction and not part of the initial AVA production scope.

---

# 30. Development Rules

Throughout development:

1. Build one architectural layer at a time.
2. Keep AVA Core framework-neutral.
3. Keep provider code inside adapters.
4. Keep contracts owned by AVA.
5. Prefer configuration over hard-coded provider choices.
6. Favor permissive open-source dependencies.
7. Pin production dependency versions.
8. Record dependency licenses.
9. Do not introduce infrastructure before it is needed.
10. Avoid premature microservices.
11. Keep the backend a modular monolith until there is a demonstrated reason to split services.
12. Share frontend code whenever practical.
13. Do not force platform-specific behavior into shared packages.
14. Validate all AI-proposed actions.
15. Keep humans in control of consequential actions.
16. Maintain automated tests as each boundary is introduced.
17. Document major architectural decisions.

---

# 31. Development Sequence Summary

```text
01  Repository / Monorepo
 ↓
02  Backend Skeleton
 ↓
03  Frontend Shared Packages
 ↓
04  Web Shell
 ↓
05  Contracts
 ↓
06  Agent Port
 ↓
07  Mock Agent
 ↓
08  Model Provider Port
 ↓
09  Local Model
 ↓
10  Web Workspace
 ↓
11  Document Editor
 ↓
12  Agent Interface
 ↓
13  Document Operations
 ↓
14  Review / Approval
 ↓
15  Tools
 ↓
16  Persistence
 ↓
17  Desktop Application
 ↓
18  Python / Databricks Client
 ↓
19  Corporate Providers
 ↓
20  Authentication / Authorization
 ↓
21  Observability
 ↓
22  Plugin Architecture
 ↓
23  Mobile Application
 ↓
24  Engineering Workflow
 ↓
25  Knowledge / RAG
 ↓
26  Model Routing
 ↓
27  Specialist Models
 ↓
28  Model Research / Evaluation
 ↓
29  Automated Model Evolution Research
```

---

# 32. Immediate Development Target

The immediate objective is intentionally small:

```text
AVA Repository
      ↓
Monorepo Structure
      ↓
Python Backend
      ↓
FastAPI
      ↓
Shared Contracts
      ↓
Shared API Client
      ↓
Web Application
      ↓
Health Check
```

Once this foundation is validated, development proceeds to:

```text
Contracts
    ↓
Agent Port
    ↓
Mock Agent
    ↓
Model Provider Port
    ↓
Local Model
```

Only after these boundaries are working should major AVA user functionality begin.

---

# 33. Definition of Success

AVA succeeds architecturally when:

- The Web, Desktop, Mobile, and Python clients can use the same backend.
- A model can be replaced without rewriting AVA.
- An agent framework can be replaced without rewriting AVA.
- A database can be replaced without rewriting AVA Core.
- Corporate integrations remain isolated.
- Local development works without company infrastructure.
- Documents and tools remain controlled by AVA rather than by the model.
- New engineering capabilities can be added incrementally.
- The architecture supports both general AI functionality and specialized expert systems.
