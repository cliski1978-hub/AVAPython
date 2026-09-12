# Open-Source and Reuse Policy

## Purpose

The reusable platform should be suitable for corporate and personal applications without depending on source-restricted framework components.

## Preferred licenses

Dependencies should normally use permissive licenses such as:

- MIT
- Apache License 2.0
- BSD two-clause or three-clause
- PostgreSQL License
- Public domain or equivalent dedication

## Components currently under consideration

| Component | License position | Intended use |
| --- | --- | --- |
| React | MIT | Web application foundation |
| Tiptap Core | MIT | Document editor |
| CopilotKit open-source repository | MIT | Agent interface, subject to package-level verification |
| FastAPI | MIT | Python application API |
| Pydantic | MIT | Python validation and contracts |
| Cordis | MIT | Planned plugin-management layer |
| Strands Agents SDK | Apache 2.0 | Optional agent adapter implementation |

## Managed-service distinction

AWS and Databricks services can be used by adapters even though managed services are not open-source libraries. The reusable application must not require one managed service in order to function.

Examples include:

- Amazon Bedrock
- Amazon Bedrock Flows
- Amazon Bedrock AgentCore
- AWS Lambda
- Databricks Apps
- Databricks Model Serving
- Unity Catalog

These integrations belong behind replaceable adapters.

## Dependency acceptance rules

- Verify the exact package license, not only the vendor repository license.
- Record direct and transitive dependency licenses.
- Pin production dependency versions.
- Generate a software bill of materials for releases.
- Preserve required copyright and license notices.
- Avoid licensing ambiguity before adoption.
- Require review for AGPL, SSPL, BSL, source-available, or custom licenses.
- Do not assume that paid extensions share the core product's open-source license.

## Corporate and personal reuse boundary

Open-source dependencies permit reuse of those dependencies; they do not determine ownership of application code created for an employer.

The reusable foundation should therefore remain free of:

- Corporate source code
- Proprietary documents or data
- Corporate prompts and policies
- Internal service addresses
- Credentials and account identifiers
- Company-specific schemas and terminology
- Restricted branding and assets

Corporate functionality should be supplied through separately owned adapters, configuration, plugins, and deployment packages.

## Portability requirement

The platform must be able to run with:

- A mock local agent
- A locally hosted model running on the application machine
- An approved corporate agent
- An approved company AI gateway model
- A Databricks-hosted agent
- A personally selected model or agent provider

Changing providers must not require rewriting the document editor, agent interface, notebook client, or shared contracts.

Local model support is required for development, testing, demonstrations, offline operation, and potential explicitly configured fallback scenarios. The local option does not prevent the application from using company-hosted or authorized external models.
