# AVA Sprint 1 — Foundation and Core Contracts

## Sprint Goal

Establish a stable, runnable AVA application foundation and define the first application-owned contracts that all future clients, agents, models, and adapters will depend upon.

At the end of Sprint 1, AVA should not yet be a functional AI application.

It should instead be a **correctly structured application platform ready for AI development**.

---

# Sprint Theme

> Build the foundation correctly before adding intelligence.

Sprint 1 focuses on:

- Repository structure
- Backend architecture
- Shared frontend structure
- Web application shell
- Backend communication
- Core contracts
- Agent port
- Model provider port
- Testing
- Documentation

---

# Sprint Scope

Sprint 1 includes:

1. Validate the monorepo structure.
2. Validate the Python backend.
3. Validate the shared frontend packages.
4. Run the Web application.
5. Connect Web to FastAPI.
6. Establish AVA contract conventions.
7. Define run contracts.
8. Define event contracts.
9. Define capability contracts.
10. Define normalized error contracts.
11. Define the Agent Adapter port.
12. Define the Model Provider port.
13. Add architecture tests.
14. Update documentation.

Sprint 1 does **not** include:

- Real AI inference
- LangChain
- LangGraph
- Ollama
- Granite integration
- Databases
- SQLAlchemy
- RAG
- Embeddings
- Tiptap
- Authentication
- AWS
- Databricks
- Corporate AI Gateway
- Plugins
- Desktop feature development
- Mobile feature development

---

# Workstream 1 — Validate Project Scaffold

## Objective

Confirm that the initial AVA monorepo created during project setup follows the intended architectural boundaries.

## Tasks

Review and validate:

```text
ava/
├── backend/
├── frontend/
│   ├── apps/
│   │   ├── web/
│   │   ├── desktop/
│   │   └── mobile/
│   │
│   └── packages/
│       ├── ui-core/
│       ├── api-client/
│       ├── contracts/
│       ├── document-core/
│       └── agent-ui/
│
├── clients/
│   └── python/
│
├── docs/
├── scripts/
└── tests/
```

Verify that:

- Web is the primary client.
- Desktop is scaffolded but not actively developed.
- Mobile is scaffolded but not actively developed.
- Shared frontend packages are independent of application shells.
- Backend code does not depend on frontend packages.
- AVA Core does not depend on provider-specific frameworks.

## Definition of Done

- Repository structure reviewed.
- Incorrect dependencies removed.
- Package boundaries documented.
- Repository builds successfully.

---

# Workstream 2 — Backend Application Validation

## Objective

Establish a reliable FastAPI application entry point.

## Tasks

Verify or implement:

```text
GET /health
```

Expected response:

```json
{
  "status": "healthy",
  "application": "AVA"
}
```

Confirm:

- FastAPI route remains thin.
- Response uses an AVA-owned contract.
- Business logic does not live in the route.
- Application startup is documented.
- CORS configuration supports local Web development where required.

## Definition of Done

The backend starts locally with one documented command and:

```text
GET /health
```

returns HTTP 200.

---

# Workstream 3 — Web-to-Backend Connection

## Objective

Prove the first end-to-end AVA client path.

Required flow:

```text
AVA Web
   ↓
Shared API Client
   ↓
FastAPI
   ↓
AVA Contract
```

## Tasks

Create or validate the shared frontend API client.

The Web application must not directly duplicate backend calls.

Implement:

```text
api-client
    ↓
health()
    ↓
GET /health
```

The Web application should display:

```text
AVA

Application Status: Healthy
```

when the API is available.

Display a useful failure state when the backend cannot be reached.

## Definition of Done

Starting Web and Backend locally demonstrates successful communication through the shared API client.

---

# Workstream 4 — Contract Foundation

## Objective

Establish the rules all AVA contracts must follow.

Create a documented contract standard.

Every public AVA contract should:

- Be application owned.
- Be JSON compatible.
- Be versionable.
- Avoid framework-specific objects.
- Avoid provider-specific objects.
- Prefer additive changes.
- Support safe handling of unknown optional fields.
- Use stable identifiers.
- Use explicit enums where appropriate.

Establish an initial contract version:

```text
v1
```

Do not design every future contract during Sprint 1.

Only define those needed to establish the architecture.

---

# Workstream 5 — Run Contracts

## Objective

Define how AVA identifies and represents work being executed.

Create initial concepts such as:

```text
RunRequest
RunResponse
RunStatus
RunId
```

Suggested RunStatus values:

```text
pending
running
waiting_for_approval
completed
cancelled
failed
```

A run should have enough information to eventually correlate:

- Request
- Conversation
- Agent
- Model
- Events
- Tools
- Approvals
- Results

Do not implement persistence yet.

---

# Workstream 6 — Event Contracts

## Objective

Create AVA's normalized event model.

Future clients must react to AVA events rather than LangChain, AWS, Databricks, or provider-specific events.

Initial event categories should include:

```text
run_started
message_started
message_content
tool_started
tool_progress
tool_completed
approval_requested
document_change_proposed
artifact_created
run_completed
run_cancelled
run_failed
```

Every event should have common information such as:

```text
event_id
run_id
event_type
timestamp
payload
contract_version
```

Exact implementation should remain simple during Sprint 1.

---

# Workstream 7 — Capability Contracts

## Objective

Give clients and workflows a standard way to discover what AVA currently supports.

Define concepts for capabilities such as:

```text
streaming
tool_calling
structured_output
cancellation
document_operations
approvals
local_execution
```

Capability discovery will eventually be used for:

- Agents
- Models
- Tools
- Clients
- Plugins

Create a backend endpoint:

```text
GET /capabilities
```

Initially it may return only basic application capabilities.

Example:

```json
{
  "contract_version": "v1",
  "application": "AVA",
  "capabilities": {
    "health": true,
    "runs": false,
    "streaming": false,
    "tool_calling": false,
    "local_model": false
  }
}
```

The false values are intentional.

AVA should report what actually exists rather than pretending future functionality is available.

---

# Workstream 8 — Normalized Error Contract

## Objective

Prevent clients from depending on framework-specific errors.

Create an AVA error structure containing concepts such as:

```text
error_code
category
message
recoverable
details
correlation_id
```

Initial categories could include:

```text
validation
configuration
unavailable
timeout
cancelled
provider
agent
internal
```

Do not expose stack traces or sensitive implementation information through public contracts.

---

# Workstream 9 — Agent Adapter Port

## Objective

Define the boundary between AVA Core and future agent implementations.

Create an AVA-owned Agent Adapter abstraction.

Conceptually:

```text
AVA Core
   │
Agent Adapter Port
   │
   ├── Mock Agent
   ├── LangGraph
   ├── AWS
   ├── Databricks
   └── Future Agent
```

The contract should define future operations such as:

```text
start_run()
cancel_run()
get_capabilities()
```

Streaming/event behavior should use AVA event contracts.

Do not implement a real agent.

A placeholder/mock implementation may exist only where required for architecture testing.

---

# Workstream 10 — Model Provider Port

## Objective

Define the boundary between AVA and model runtimes/providers.

Create an AVA-owned Model Provider abstraction.

Conceptually:

```text
AVA Core
    │
Model Provider Port
    │
    ├── Local
    ├── Company Gateway
    └── External
```

Define capabilities such as:

```text
health()
get_model_info()
get_capabilities()
generate()
```

The abstraction should eventually accommodate:

- Text generation
- Streaming
- Structured output
- Tool calling
- Context limits
- Cancellation
- Usage information

Do not connect a real model in Sprint 1.

---

# Workstream 11 — Configuration Foundation

## Objective

Prepare AVA for future provider selection without implementing providers yet.

Create configuration concepts for:

```text
application
environment
agent
model_provider
api
logging
```

Future configuration should support:

```text
model_provider = local
```

or:

```text
model_provider = company_gateway
```

without changing AVA Core.

Do not add credentials for services that do not yet exist.

---

# Workstream 12 — Architecture Tests

## Objective

Begin automatically protecting AVA's architectural boundaries.

Create tests that help prevent accidental dependencies.

At minimum verify:

- Core does not import FastAPI.
- Core does not import provider SDKs.
- Contracts do not import FastAPI.
- Contracts do not import agent frameworks.
- Contracts remain serializable.
- `/health` returns the defined response.
- `/capabilities` returns the defined response.

Testing should remain lightweight during Sprint 1.

---

# Workstream 13 — Development Environment

## Objective

Make AVA easy to start on a developer machine.

Document commands for:

### Backend

```text
create environment
install dependencies
start FastAPI
run tests
```

### Frontend

```text
install pnpm dependencies
start Web
build Web
run frontend tests
```

Where practical, create convenience scripts such as:

```text
dev_backend
dev_web
test_all
```

Do not create complicated DevOps infrastructure yet.

---

# Workstream 14 — Documentation

## Objective

Ensure AVA architecture evolves alongside the implementation.

Update the documentation library with:

```text
AVA Development Plan.md
Architecture.md
Repository Structure.md
Contract Standards.md
Agent Adapter.md
Model Provider.md
Local Development.md
```

Record major architecture decisions.

Future decisions that materially affect the platform should be captured as Architecture Decision Records.

Suggested future folder:

```text
docs/
└── decisions/
    ├── ADR-001-monorepo.md
    ├── ADR-002-hexagonal-backend.md
    └── ADR-003-shared-frontend.md
```

ADR creation may begin in this sprint if useful but is not required for Sprint 1 completion.

---

# Sprint 1 Execution Order

Follow this order:

```text
1. Validate repository
        ↓
2. Run backend
        ↓
3. Run Web
        ↓
4. Verify health endpoint
        ↓
5. Verify shared API client
        ↓
6. Connect Web → Backend
        ↓
7. Establish contract standard
        ↓
8. Create Run contracts
        ↓
9. Create Event contracts
        ↓
10. Create Capability contracts
        ↓
11. Create Error contracts
        ↓
12. Define Agent Adapter port
        ↓
13. Define Model Provider port
        ↓
14. Add configuration foundation
        ↓
15. Add architecture tests
        ↓
16. Update documentation
```

---

# Sprint 1 Deliverables

Sprint 1 should produce:

- Working AVA monorepo
- Working Python backend
- Working Web shell
- Shared frontend packages
- Shared API client
- `/health`
- `/capabilities`
- Contract versioning convention
- Run contracts
- Event contracts
- Capability contracts
- Error contracts
- Agent Adapter port
- Model Provider port
- Configuration foundation
- Backend tests
- Architecture tests
- Development documentation

---

# Sprint 1 Acceptance Test

A developer should be able to clone AVA and perform:

```text
Start Backend
      ↓
Start Web
      ↓
Open AVA Web
      ↓
Web calls shared API client
      ↓
API calls FastAPI
      ↓
GET /health
      ↓
Healthy
```

The developer should also be able to call:

```text
GET /capabilities
```

and receive AVA's current capabilities.

The codebase should already contain:

```text
AgentAdapter
ModelProvider
Run Contracts
Event Contracts
Error Contracts
Capability Contracts
```

without requiring a real AI model.

---

# Sprint 1 Definition of Done

Sprint 1 is complete when:

- [ ] Monorepo structure is validated.
- [ ] Backend runs locally.
- [ ] Web runs locally.
- [ ] Web communicates with Backend.
- [ ] Shared API client is used.
- [ ] `/health` works.
- [ ] `/capabilities` works.
- [ ] Contract versioning is established.
- [ ] Run contracts exist.
- [ ] Event contracts exist.
- [ ] Error contracts exist.
- [ ] Capability contracts exist.
- [ ] Agent Adapter port exists.
- [ ] Model Provider port exists.
- [ ] Configuration foundation exists.
- [ ] Architecture tests pass.
- [ ] Backend tests pass.
- [ ] Development startup process is documented.
- [ ] Architecture documentation reflects the actual implementation.
- [ ] No real AI provider has been unnecessarily introduced.
- [ ] No database has been unnecessarily introduced.
- [ ] No vendor framework has leaked into AVA Core.

---

# What Sprint 1 Enables

Sprint 1 establishes:

```text
                  AVA Core
                     │
          ┌──────────┴──────────┐
          │                     │
      Agent Port            Model Port
          │                     │
          ?                     ?
```

The `?` is intentional.

Sprint 1 defines the sockets.

Sprint 2 begins plugging real components into them.

The logical next development sequence becomes:

```text
Sprint 1
Foundation + Contracts
        ↓
Sprint 2
Mock Agent + Run Lifecycle
        ↓
Sprint 3
Local Model Provider
        ↓
Sprint 4
AVA Workspace / Agent UI
```

This preserves the primary architectural rule:

> AVA depends on its own contracts. External frameworks depend on AVA's boundaries—not the other way around.