# AVA Sprint 2 Plan

## Sprint Title

**Sprint 2 — Core AI User Experience**

## Sprint Goal

Build the standard AVA AI application experience first.

AVA should look and operate like a modern AI assistant application so that users immediately understand how to interact with it. Specialized capabilities such as Tiptap document editing, engineering tools, RAG, and future plugins will be layered on top of this core AI interface rather than defining the primary application experience.

---

## 1. Core Product Principle

The base AVA interface must provide the common interaction patterns users expect from modern AI applications.

The primary experience is:

```text
Conversation History
        ↓
Active Conversation
        ↓
User / Assistant Messages
        ↓
Prompt Composer
        ↓
Run / Response Lifecycle
```

Additional AVA capabilities extend this experience:

```text
                    AVA Core AI Interface
                 /          |           \
                /           |            \
        Document Mode   Engineering    Knowledge / RAG
            |              Tools           |
          Tiptap         Tool Panels     Sources
```

---

## 2. Sprint 2 Primary Objectives

1. Build the reusable AVA application shell.
2. Build the standard AI conversation interface.
3. Build shared conversation and message UI components.
4. Establish frontend conversation/workspace state.
5. Implement a mock agent behind `AgentPort`.
6. Implement the first working run lifecycle.
7. Implement normalized run events between backend and frontend.
8. Add common AI interaction controls.
9. Build the first shared `agent-ui` components.
10. Establish the extension points where future AVA capabilities will attach.
11. Add Tiptap only after the core AI interface is functional.
12. Prove the full user interaction loop without requiring a real AI model.

---

## 3. Core Application Shell

Build the reusable AVA shell that Web and Desktop can share.

### Required UI Structure

- Application header / top navigation
- Collapsible conversation/history sidebar
- Main conversation workspace
- Prompt composer area
- Agent/run status area
- Extension/tool panel region
- Settings/navigation entry point
- Responsive layout
- Empty/loading/error states

### Architectural Rule

Platform shells remain thin.

```text
Web / Desktop
      ↓
Shared AVA UI Packages
      ↓
Shared API Client
      ↓
AVA Backend
```

---

## 4. Standard AI Conversation Experience

Implement the familiar core AI interaction model.

### Conversation Features

- New conversation
- Conversation list
- Select conversation
- Conversation title
- Active conversation state
- Empty conversation / welcome state

### Message Features

- User messages
- Assistant messages
- Message timestamps where appropriate
- Copy assistant response
- Retry/regenerate response
- Message loading state
- Message failure state
- Basic message action area

### Prompt Composer

- Multiline text input
- Send control
- Stop generation control
- Enter / Shift+Enter keyboard behavior
- Disabled state while appropriate
- Attachment affordance reserved for later implementation
- Clear visual indication of active processing

---

## 5. Run Lifecycle

Implement the first usable AVA run lifecycle.

Expected flow:

```text
User submits prompt
        ↓
Frontend creates run request
        ↓
RunService
        ↓
AVA creates run_id
        ↓
AgentPort
        ↓
Mock Agent
        ↓
Normalized Run Events
        ↓
Frontend updates conversation
```

### Required States

- Pending
- Running
- Completed
- Failed
- Cancelled
- Waiting for approval reserved for later workflows

---

## 6. Event System

Use the normalized AVA event contracts created during Sprint 1.

Initial event support should include the minimum required for the AI chat experience:

- `run_started`
- `message_started`
- `message_content`
- `run_completed`
- `run_cancelled`
- `run_failed`

Tool, approval, document-change, and artifact events remain available in the contract vocabulary but do not need full UI behavior yet.

---

## 7. Mock Agent

Implement the first concrete `AgentPort` adapter as a deterministic mock agent.

### Purpose

The mock agent allows AVA to prove the complete interaction architecture without introducing LangChain, LangGraph, Ollama, or a company AI gateway.

### Mock Agent Requirements

- Accept AVA `RunRequest`
- Receive AVA-owned `run_id`
- Return predictable assistant content
- Produce normalized AVA events
- Support cancellation where practical
- Advertise truthful capabilities
- Contain no external AI-provider dependency

---

## 8. Shared `agent-ui` Package

Begin implementing the reserved `frontend/packages/agent-ui` package.

Initial reusable components may include:

- Conversation view
- Message list
- User message
- Assistant message
- Prompt composer
- Run status indicator
- Error/retry display
- Conversation empty state

The package should remain provider-neutral.

It must not know about Ollama, OpenAI, LangGraph, Databricks, or other future adapters.

---

## 9. Frontend State Foundation

Establish a simple state structure for:

- Current conversation
- Conversation list
- Messages
- Current run
- Run status
- Errors
- UI panel state

Avoid adding a large state-management framework unless the actual complexity requires it.

Prefer React-native state patterns first.

---

## 10. API Expansion

Add only the API functionality required to support the Sprint 2 interaction loop.

Likely endpoints/contracts include:

- Start run
- Cancel run
- Retrieve run state if necessary
- Deliver run events
- Conversation APIs only if needed for the chosen in-memory Sprint 2 design

Keep routes thin:

```text
FastAPI Route
      ↓
Application Service
      ↓
AVA Port / Core
```

---

## 11. Tiptap Integration

Tiptap comes **after the core AI interface works**.

Tiptap is not the primary AVA interface.

It becomes an additional workspace capability layered onto the AI application.

Initial goal:

- Add document workspace region
- Embed Tiptap editor
- Establish `document-core` abstraction
- Allow AVA to display/edit a document alongside the conversation
- Keep Tiptap-specific types out of AVA Core contracts

Conceptual layout:

```text
AVA
├── Conversation Sidebar
├── Main AI Conversation
├── Prompt Composer
└── Optional Workspace Panel
      └── Document Editor
            └── Tiptap
```

---

## 12. Basic Document Operations

After Tiptap is integrated, establish only the minimum document-operation foundation required for future agent workflows.

Examples:

- Read current document content
- Replace content
- Insert content
- Apply a proposed text change
- Represent proposed changes through AVA-owned document operations

Do not build advanced document-agent workflows yet.

---

## 13. User Experience Requirements

AVA should feel familiar to users of modern AI applications.

Sprint 2 UI should prioritize:

- Clear hierarchy
- Minimal visual clutter
- Familiar chat layout
- Fast keyboard interaction
- Responsive design
- Clear processing states
- Clear errors
- Easy conversation switching
- Consistent components
- Accessibility-friendly controls
- Web-first design that also works in Desktop

Do not clone another product visually. Use familiar interaction patterns while establishing AVA's own design identity.

---

## 14. External Libraries

### Already Present

- React
- TypeScript
- Vite
- FastAPI
- Pydantic
- Uvicorn
- Tauri
- pnpm

### New Major Sprint 2 Dependency

- **Tiptap** — document editor/workspace capability

### Do Not Add Yet

- CopilotKit
- LangChain
- LangGraph
- Ollama
- OpenAI SDK
- Anthropic SDK
- SQLAlchemy
- RAG frameworks
- Vector databases
- Cordis
- Strands Agents

The mock AVA architecture should prove the interaction model before these are introduced.

---

## 15. Testing Requirements

Sprint 2 should add tests for:

### Backend

- Start run
- Run ID ownership
- Mock Agent execution
- Event generation
- Cancellation
- Run failure behavior
- Capability changes

### Frontend

- Conversation rendering
- User message rendering
- Assistant message rendering
- Prompt submission
- Run loading states
- Run errors
- Stop/cancel behavior
- Shared agent-ui components
- Document workspace when Tiptap is introduced

### Architecture

Continue enforcing:

- Core framework neutrality
- Provider-neutral ports
- Shared contract boundaries
- No provider SDK leakage
- Web/Desktop use shared API/client components

---

## 16. Sprint 2 Acceptance Criteria

Sprint 2 is complete when a user can:

1. Open AVA.
2. See a familiar AI application interface.
3. Start a new conversation.
4. Enter a prompt.
5. Submit the prompt.
6. See AVA transition through the run lifecycle.
7. Receive a mock assistant response.
8. See normalized status/error behavior.
9. Cancel a running request where supported.
10. Switch between conversation UI states.
11. Use the same core interface in Web and Desktop.
12. Open the document workspace.
13. Edit a document through Tiptap.
14. Demonstrate that document editing is an extension of the AI interface rather than the primary application architecture.

---

## 17. Explicitly Out of Scope

Sprint 2 does not require:

- Real LLM inference
- Local-model execution
- Company AI gateway
- AWS/Databricks AI integration
- LangChain/LangGraph
- RAG
- Embeddings
- Vector databases
- Persistent conversation database
- Authentication
- Advanced approval workflows
- Tool execution framework
- Engineering-specific agents
- Plugin architecture
- Mobile implementation
- Production deployment

---

## 18. Recommended Implementation Sequence

```text
1. Core UI Shell
        ↓
2. Shared UI Components
        ↓
3. Conversation / Message UI
        ↓
4. Prompt Composer
        ↓
5. Frontend Conversation State
        ↓
6. Mock Agent
        ↓
7. Run API
        ↓
8. Run/Event Lifecycle
        ↓
9. Agent UI Integration
        ↓
10. Cancel / Retry / Error UX
        ↓
11. Web + Desktop Validation
        ↓
12. Tiptap Integration
        ↓
13. document-core Foundation
        ↓
14. Basic Document Operations
        ↓
15. Sprint 2 Validation & Sign-Off
```

---

## 19. Sprint 2 Guiding Rule

> **Build AVA as an AI application first. Everything specialized is an extension of that experience.**

The standard conversation experience must remain useful even when no document, engineering tool, RAG source, or plugin is active.
