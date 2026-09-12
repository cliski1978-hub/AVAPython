# Development Roadmap

## Phase 1: Foundation

### Deliverables

- Repository and package structure
- Shared contract definitions
- Python application core skeleton
- FastAPI application shell
- Mock agent adapter
- Model provider contract
- Local model adapter
- Local model health and capability checks
- Health and capability checks
- Initial architecture tests

### Completion criteria

- The Python application runs locally.
- A test client can start a mock run and receive normalized results.
- No agent-framework dependency exists in the shared core.
- The application can select and reach a locally hosted model without company gateway access.

## Phase 2: Basic document workspace

### Deliverables

- React application shell
- Tiptap document editor
- Basic formatting toolbar
- Document selection tracking
- Agent sidebar shell
- Frontend-to-Python connection

### Completion criteria

- A user can open and edit a document.
- The UI can call the mock Python application.
- Mock responses appear in the agent panel.

## Phase 3: Agent-driven document operations

### Deliverables

- Neutral document operations
- Tiptap document adapter
- Proposed-change display
- Accept and reject workflow
- Operation validation
- Undo support

### Completion criteria

- The mock agent can propose a document change.
- The user can accept or reject it.
- The agent never sends raw editor commands.

## Phase 4: Databricks notebook integration

### Deliverables

- Notebook client package
- Authentication integration
- Task submission and status retrieval
- Structured notebook results
- Example document-analysis notebook
- Notebook integration tests

### Completion criteria

- A Databricks notebook can call the Python application.
- The notebook can obtain a completed result without loading the React UI.
- Notebook and browser requests use the same versioned contract.

## Phase 5: First corporate agent adapter

### Deliverables

- Adapter for the approved AWS or corporate agent platform
- Company AI gateway model adapter
- Streaming-event translation
- Tool and session integration
- Corporate authentication and permissions
- Provider error handling

### Completion criteria

- The approved agent can replace the mock adapter through configuration.
- The UI and notebook client require no framework-specific changes.
- The model can change from local to the company gateway through configuration without rewriting the workflow.

## Phase 6: Persistence and operational controls

### Deliverables

- Document, conversation, run, event, and approval repositories
- Audit logging
- Role and permission enforcement
- Retry, timeout, and cancellation policies
- Observability integration

### Completion criteria

- Runs and approvals are auditable.
- Interrupted clients can recover run status.
- Sensitive operations require server-side authorization.

## Phase 7: Cordis plugin management

### Deliverables

- Stable plugin contract
- Cordis host integration
- Plugin manifests and dependency handling
- Plugin configuration and lifecycle
- Conversion of selected existing UI modules into plugins
- Plugin compatibility and failure tests

### Completion criteria

- A plugin can be enabled or disabled through configuration.
- A plugin can register a UI capability without changing the application shell.
- Disabling one optional plugin does not break unrelated modules.

## Phase 8: Reusable application profiles

### Deliverables

- Corporate application profile
- Personal application profile
- Separate branding and configuration
- Replaceable identity and storage adapters
- Second agent-framework adapter
- Packaging and deployment documentation

### Completion criteria

- The same reusable foundation supports two applications.
- Corporate code and configuration remain isolated.
- Agent frameworks can be changed without rewriting the UI.

## Recommended first milestone

The first milestone should demonstrate one narrow end-to-end scenario:

1. Open a document in the React application.
2. Select a paragraph.
3. Submit an analysis request.
4. Receive a mock proposed revision from the Python application.
5. Review and accept or reject the revision.
6. Submit the same type of request from a Databricks notebook.

This milestone validates the important boundaries before connecting a real agent platform.
