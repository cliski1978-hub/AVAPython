# Module Development Plan

## 1. React application shell

- Main workspace layout
- Navigation and routing
- Resizable document and agent panels
- Loading, status, and error presentation
- Application configuration loading
- Shared theme and accessible component styles
- Declared extension points for future plugins

## 2. Document editor module

- Tiptap Core integration
- Rich-text toolbar
- Headings, paragraphs, lists, checklists, links, images, and tables
- Undo and redo
- Selection tracking
- Document loading and saving
- Read-only and editable modes
- HTML and structured JSON conversion
- Custom application document blocks
- Application-owned wrapper around Tiptap

## 3. Agent interface module

- Conversation panel
- Prompt input
- Streaming response display
- Run status and cancellation
- Tool-execution cards
- Source citations
- Approval requests
- Accept and reject actions
- Conversation history
- Application-owned wrapper around CopilotKit or its replacement

## 4. Document review module

- Proposed-change cards
- Original and proposed content comparison
- Accept or reject individual changes
- Batch review actions
- Change explanations
- Pending-change indicators
- Reversal of applied changes
- Review history

## 5. Document management module

- Document list
- Create, open, rename, and save operations
- File upload and export
- Document metadata
- Search and filtering
- Recent documents
- Version information
- Permission-aware actions

## 6. Shared contract module

- Agent request and response definitions
- Streaming event definitions
- Tool-call and tool-result definitions
- Approval definitions
- Document-operation definitions
- Document-selection definitions
- Citation and attachment definitions
- Error definitions
- Capability discovery definitions
- Contract versioning

## 7. Document adapter module

- Read the complete document
- Read the active selection
- Insert, replace, delete, and format content
- Apply custom blocks
- Validate proposed document operations
- Translate neutral operations into Tiptap commands
- Provide an editor-independent interface to the application

## 8. Frontend agent client

- Submit agent requests
- Receive streamed events
- Cancel runs
- Submit approvals and rejections
- Upload attachments
- Reconnect interrupted streams
- Handle authentication and expiration
- Discover backend capabilities
- Preserve conversation and run identifiers

## 9. Python application API

- Health and capability endpoints
- Agent-run endpoints
- Event-streaming endpoint
- Cancellation endpoint
- Document endpoints
- File-upload endpoint
- Approval endpoints
- Authentication handling
- Request validation
- Consistent error responses
- API versioning
- Audit context

## 10. Python application core

- Request coordination
- Agent-run lifecycle
- Conversation state
- Document operation coordination
- Pending approvals
- Agent-output validation
- Event publishing
- Business-policy enforcement
- Agent-adapter selection
- Framework-neutral internal models

## 11. Agent adapter contract

- Start, continue, and cancel an agent run
- Stream normalized events
- Supply document context and tool definitions
- Receive tool results
- Pause and resume for human approval
- Report capabilities
- Normalize framework errors
- Prevent framework-specific types from escaping the adapter

## 12. AWS agent adapter

- Approved AWS authentication
- Agent invocation
- Streaming response translation
- Tool invocation
- Session handling
- Security configuration
- Error normalization
- Mapping into shared application contracts

## 13. Databricks agent adapter

- Databricks authentication
- Deployed-agent invocation
- Model-serving invocation where required
- Unity Catalog tool integration
- MLflow-compatible integration where required
- Response and error normalization

## 14. Databricks notebook client

- Lightweight Python client package
- Application authentication
- Task and document submission
- Run-status retrieval
- Result retrieval
- Approval and rejection actions
- Notebook-friendly result tables
- Databricks secret integration
- Example notebooks

## 15. Mock agent module

- Offline and repeatable responses
- Simulated streaming
- Simulated tool calls
- Simulated document edits
- Simulated approval requests
- Simulated failures and delays
- Deterministic UI test scenarios

## 16. Tool registry

- Tool registration
- Input and result schemas
- Permission declarations
- Tool-to-adapter mapping
- Frontend renderer association
- Execution audit history
- Future plugin-provided tools

## 17. Authentication and authorization

- Pluggable identity provider
- User identity and roles
- Document permissions
- Agent and tool permissions
- Token validation
- Session expiration
- Audit identity
- Plugin permission declarations

## 18. Persistence

- Document repository
- Conversation repository
- Run and event repository
- Approval repository
- File metadata
- Application configuration
- Audit records
- Replaceable storage adapters

## 19. Observability

- Structured application logs
- Agent-run and tool-call tracing
- Request correlation identifiers
- Execution timing
- Usage metrics
- Error tracking
- Provider-specific telemetry adapters

## 20. Cordis plugin-management layer

- Cordis plugin host
- Application plugin manifest
- Plugin identifiers and versions
- Dependency declarations
- Lifecycle management
- Service and event registration
- Capability registration
- Configuration loading
- Compatibility validation
- Permission declarations
- Plugin isolation and cleanup

## 21. Initial planned plugins

- Tiptap document plugin
- Agent-interface plugin
- Document-review plugin
- File-browser plugin
- Citation-viewer plugin
- Tool-result renderer plugins
- AWS integration plugin
- Databricks integration plugin
- Corporate configuration plugin
- Personal-application configuration plugin

## 22. Testing and compliance

- Contract tests
- React component tests
- Document-operation tests
- Python API tests
- Adapter conformance tests
- Notebook integration tests
- Authentication and permission tests
- Plugin lifecycle tests
- End-to-end tests
- Dependency license scanning
- Software bill of materials generation

## 23. Model provider contract

- Provider-neutral request and response models
- Streaming model output
- Tool-calling capability declarations
- Model capability discovery
- Context-window and input-limit reporting
- Provider health checks
- Provider error normalization
- Configuration-based provider selection
- Provider fallback policy where explicitly enabled
- Prevention of provider-specific objects escaping into shared modules

## 24. Local model adapter

- Connection to a model runtime on the application machine
- Configurable local endpoint and model identifier
- Health and availability detection
- Streaming response support
- Tool-calling support when offered by the selected local model
- Clear reporting of unsupported capabilities
- Offline-operation mode
- Local-model performance and resource reporting
- No external transmission when local-only mode is selected

## 25. Company gateway adapter

- Approved company authentication
- Gateway endpoint configuration
- Company model discovery
- Request and streaming-response translation
- Security and monitoring integration
- Error and availability reporting
- Shared model-provider contract implementation

## 26. Authorized external model adapters

- Provider-specific authentication isolated inside each adapter
- Request and response translation
- Capability discovery
- Usage and error reporting
- Configuration and policy controls
- Shared model-provider contract implementation
