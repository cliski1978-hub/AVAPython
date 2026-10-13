# 47 — Python Client Validation

Date: 2026-10-12  
Status: **#47 Python Client Validation — PASS**

## Package and environment

- Python client package: `/home/bizon/AvaUi/clients/python`
- Import package: `ava_client`
- Interpreter: `/home/bizon/AvaUi/clients/python/.venv/bin/python`, Python 3.12.14
- Environment: existing package virtualenv with pytest 9.1.1, Ruff, mypy, httpx and Pydantic installed. No dependency changes or upgrades were made.
- The system `python3` is Python 3.10.12 and is not used; there is no system `python` command. The package virtualenv is the established interpreter used by `scripts/test_all.sh`.

## Commands and results

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pytest` | **11 passed, 0 failed, 0 skipped** in 0.10 seconds; no xfailed or xpassed tests. |
| `.venv/bin/python -m ruff check src tests` | **PASS** — All checks passed. |
| `.venv/bin/python -m mypy src` | **PASS** — strict mode is configured in `pyproject.toml`; no issues in 3 source files. |
| `.venv/bin/python -c 'import ava_client; print("ok", ava_client.__version__)'` | **PASS** — printed `ok 0.1.0`. |
| `git diff --check` | **PASS**. |

## Contract compatibility

The client currently calls `/health`, `/capabilities`, `/model-providers`, `/models`, and `/workspaces`. The mirrored health, capability, provider discovery, model metadata, qualification, and workspace models match those backend response shapes. `ModelInfo.context_limit` is already represented, along with current provider/model identity, hosting, enabled state, capabilities, and qualification metadata. Workspace kinds (`local`, `ephemeral`) and capability names match the backend enums.

The review found a real additive contract mismatch in the supported `/models` path: the backend returns optional `default_model_id`, but `ModelDiscoveryResponse` did not declare it, so Pydantic silently discarded it. Added the optional field and regression coverage through both model deserialization and `AvaClient.list_models()`.

The existing Python request/response models for Runs also lagged the current backend shapes. They now retain Phase 5 conversation/source/assistant identities, cancellation timestamp, Project/runtime/model provenance, provider-connection/runtime-configuration IDs, the `auto` execution mode, workspace selection, retry source, and request contract version. These model updates do not add new HTTP client methods.

The Python client intentionally has no methods or typed resource models for conversation CRUD, run creation/status/events/inspection, attachments, Folder/Project operations, Project execution defaults, or CORE/System Prompts. This matches the documented boundary in `docs/AVA_Phase_5_53_Conversation_Folder_Domain.md` and `docs/AVA_Phase_5_56_Project_Domain.md`, which state the client has no organizational-resource contract layer. Run Inspector and context-window accounting are likewise not exposed as Python client features. No client APIs were added for those resources.

## Changes and classification

- **Fixed client model mismatch:** `ModelDiscoveryResponse.default_model_id` was being dropped. Added a focused regression test; the full test suite passes.
- **Run-model compatibility:** brought the existing RunRequest/RunResponse/RunExecutionSelection models into line with current backend fields and added serialization/deserialization assertions.
- **No remaining Phase 5 client regression identified.** Unsupported resources remain intentionally outside the current Python client surface; they are documented rather than treated as failed coverage.

Final status: **#47 Python Client Validation — PASS**.
