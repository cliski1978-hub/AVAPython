"""Run inspection snapshots are durable, historical run-owned facts."""

from ava.contracts.conversations import ContextMessage, ExecutionPromptLayers, MessageRole
from ava.contracts.run_inspection import RunInspectionSnapshot
from ava.infrastructure.persistence import create_relational_repositories
from ava.services.run_service import sanitize_inspection


def test_inspection_redacts_credentials_without_hiding_prompt_or_request_text() -> None:
    snapshot = RunInspectionSnapshot.model_validate({
        "prompt_layers": {
            "root_system_prompt": "Root prompt text",
            "resolved_core_prompts": [],
            "project_instructions": None,
        },
        "normalized_request": [{"role": "user", "content": "please do this"}],
        "runtime_request": {
            "model_request": {"messages": [{"role": "user", "content": "please do this"}]},
            "api_key": "sensitive",
            "headers": {"Authorization": "Bearer sensitive"},
        },
    })

    safe = sanitize_inspection(snapshot)

    assert safe.prompt_layers.root_system_prompt == "Root prompt text"
    assert safe.normalized_request[0].content == "please do this"
    assert safe.runtime_request["api_key"] == "[REDACTED]"
    assert safe.runtime_request["headers"] == "[REDACTED]"


def test_relational_repository_persists_and_lists_captured_run_snapshots(tmp_path) -> None:
    path = tmp_path / "run-inspection.sqlite3"
    repositories = create_relational_repositories(str(path))
    run_repository = repositories.run_repository
    record = run_repository.create("run-one", conversation_id="conversation-one")
    snapshot = RunInspectionSnapshot(
        prompt_layers=ExecutionPromptLayers(root_system_prompt="Prompt version A"),
        normalized_request=[ContextMessage(role=MessageRole.USER, content="hello", message_id="message-one")],
    )
    run_repository.set_inspection_snapshot(record.run_id, snapshot)
    repositories.dispose()

    reopened = create_relational_repositories(str(path))
    try:
        stored = reopened.run_repository.get("run-one")
        assert stored is not None
        assert stored.inspection_snapshot is not None
        assert stored.inspection_snapshot.prompt_layers.root_system_prompt == "Prompt version A"
        assert stored.inspection_snapshot.normalized_request[0].message_id == "message-one"
        runs = reopened.run_repository.list_for_conversation("conversation-one")
        assert [item.run_id for item in runs] == ["run-one"]
    finally:
        reopened.dispose()
