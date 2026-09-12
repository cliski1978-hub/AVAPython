# Integration Contracts

## Objective

Application-owned contracts keep clients, editors, agent frameworks, model providers, and deployment platforms replaceable. Contracts must be versioned, documented, testable, and independent of vendor SDK types.

## Client-to-application contract

Used by both the React application and Databricks notebooks.

The contract must cover:

- Starting and identifying a run
- Supplying messages, instructions, document references, and attachments
- Reporting client identity and capabilities
- Receiving current run status
- Cancelling a run
- Approving or rejecting a pending action
- Retrieving final results and artifacts

## Application event contract

The Python application emits normalized events such as:

- Run started
- Message started
- Message content received
- Tool started
- Tool progress updated
- Tool completed
- Document change proposed
- Approval requested
- Artifact created
- Run completed
- Run cancelled
- Run failed

Clients may present events differently, but their meaning must remain stable.

## Document operation contract

Agents propose neutral document operations. They never issue raw Tiptap commands.

Supported operation categories should include:

- Insert content
- Replace a selection or range
- Delete a range
- Apply formatting
- Add a structured document block
- Add a comment or annotation
- Propose multiple operations as one reviewable change set

Each operation must include a document identifier, a stable target, content type, operation identifier, source run, and validation status.

## Agent adapter contract

Every adapter must:

- Accept the application request model
- Return normalized application events
- Support cancellation or report that cancellation is unavailable
- Declare supported tools and capabilities
- Preserve run correlation
- Translate errors into application error categories
- Keep credentials and vendor-specific configuration inside the adapter
- Avoid exposing provider-specific objects to clients

## Model provider contract

Every model provider must expose a common application-facing contract covering:

- Model identity and capabilities
- Text and structured requests
- Streaming responses
- Tool-call support
- Context and input limits
- Availability and health status
- Cancellation support
- Usage metadata when available
- Normalized errors

The initial provider categories are a locally hosted model, the approved company AI gateway, and an authorized external provider. Provider selection is controlled through application configuration. Agent workflows consume the shared contract and do not import provider SDKs directly.

## Document editor contract

The document UI wrapper must:

- Load and return document content
- Report the current selection
- Validate and apply neutral operations
- Report operation success or failure
- Support undo where possible
- Expose editor capabilities
- Hide Tiptap-specific commands from the rest of the application

## Plugin contract

The future Cordis plugin layer must support:

- Plugin identity and semantic version
- Required platform version
- Dependencies and optional dependencies
- Capabilities provided and consumed
- Startup and shutdown lifecycle
- Registered services and events
- Configuration schema
- Permission declarations
- UI extension locations
- Cleanup of subscriptions and resources

## Compatibility rules

- Contracts use standard JSON-compatible data.
- Every public contract includes a version.
- Additive changes are preferred over breaking changes.
- Unknown optional properties are ignored safely.
- Required capability negotiation occurs before a run begins.
- Vendor names do not appear in shared operation types.
- Changing the selected model provider requires configuration, not workflow modification.
- Credentials never appear in document or event payloads.
- Large files are passed by controlled references rather than embedded repeatedly.

## Security rules

- The client cannot declare itself authorized for an operation.
- The Python application validates every requested and agent-proposed action.
- Document operations are checked before reaching the editor.
- Tool permissions are enforced by the application or server-side integration.
- Every approval records the user, action, run, and time.
- Sensitive content is excluded from logs unless explicitly approved.
