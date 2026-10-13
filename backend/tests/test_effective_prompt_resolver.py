"""Phase 5.70 deterministic read-only CORE prompt resolution."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ava.contracts.core_prompts import CreateCorePromptRequest
from ava.infrastructure.persistence import SqliteDatabase
from ava.infrastructure.persistence.repositories.conversation_folder_repository import (
    RelationalConversationFolderRepository,
)
from ava.infrastructure.persistence.repositories.conversation_repository import RelationalConversationRepository
from ava.infrastructure.persistence.repositories.core_prompt_assignment_repository import (
    RelationalCorePromptAssignmentRepository,
)
from ava.infrastructure.persistence.repositories.core_prompt_repository import RelationalCorePromptRepository
from ava.infrastructure.persistence.repositories.project_repository import RelationalProjectRepository
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.core_prompt import CorePromptCategory
from ava.repositories.core_prompt_assignment import CorePromptScopeType
from ava.repositories.project import ProjectRecord
from ava.services.conversation_folder_store import ConversationFolderStore
from ava.services.conversation_store import ConversationStore
from ava.services.core_prompt_assignment_service import CorePromptAssignmentService
from ava.services.core_prompt_assignment_store import CorePromptAssignmentStore
from ava.services.core_prompt_service import CorePromptService
from ava.services.core_prompt_store import CorePromptStore
from ava.services.effective_prompt_resolver import (
    EffectivePromptResolver,
    PromptResolutionContext,
    PromptResolutionError,
)
from ava.services.project_store import ProjectStore


@pytest.fixture(params=["memory", "sqlite"])
def world(request: pytest.FixtureRequest, tmp_path: Path):
    database = None
    if request.param == "memory":
        conversations = ConversationStore()
        folders = ConversationFolderStore(conversations)
        assignments = CorePromptAssignmentStore()
        prompts = CorePromptStore(assignments)
        projects = ProjectStore(conversations, assignments)
    else:
        database = SqliteDatabase(str(tmp_path / "resolver.sqlite3"))
        conversations = RelationalConversationRepository(database=database)
        folders = RelationalConversationFolderRepository(database=database)
        assignments = RelationalCorePromptAssignmentRepository(database=database)
        prompts = RelationalCorePromptRepository(database=database)
        projects = RelationalProjectRepository(database=database)
    prompt_service = CorePromptService(core_prompt_repository=prompts)
    assignment_service = CorePromptAssignmentService(
        assignments=assignments,
        prompts=prompts,
        projects=projects,
        folders=folders,
        conversations=conversations,
        runtime_ids=("native", "openhands"),
    )
    resolver = EffectivePromptResolver(
        prompts=prompts,
        assignments=assignments,
        conversations=conversations,
        runtime_ids=("native", "openhands"),
    )
    yield prompt_service, assignment_service, resolver, conversations, projects, folders, assignments, prompts, database
    if database is not None:
        database.dispose()


def _create(world, name: str, category: CorePromptCategory = CorePromptCategory.CORE):
    return world[0].create_core_prompt(
        CreateCorePromptRequest(name=name, prompt_text=f"text:{name}", category=category)
    )


def _assign(world, prompt_id: str, scope: CorePromptScopeType, scope_id: str | None, state: str):
    return world[1].set_assignment(prompt_id, scope, scope_id, state)


def test_nearest_scope_wins_with_project_folder_and_conversation(world) -> None:
    global_prompt = _create(world, "Global")
    reenabled = _create(world, "Conversation Re-enable")
    no_assignment = _create(world, "Never assigned")
    now = datetime.now(UTC)
    world[4].create(ProjectRecord("project-a", "Project", now, now))
    world[5].create(ConversationFolderRecord("folder-a", "Folder", now, now))
    world[3].create("conversation-a", title="Chat", project_id="project-a")
    world[3].set_folder("conversation-a", "folder-a")

    for prompt in (global_prompt, reenabled):
        _assign(world, prompt.id, CorePromptScopeType.GLOBAL, None, "enable")
    _assign(world, global_prompt.id, CorePromptScopeType.PROJECT, "project-a", "enable")
    _assign(world, global_prompt.id, CorePromptScopeType.FOLDER, "folder-a", "disable")
    _assign(world, reenabled.id, CorePromptScopeType.PROJECT, "project-a", "disable")
    _assign(world, reenabled.id, CorePromptScopeType.CONVERSATION, "conversation-a", "enable")

    result = world[2].resolve(PromptResolutionContext(conversation_id="conversation-a"))
    assert result.context.project_id == "project-a" and result.context.folder_id == "folder-a"
    assert [p.core_prompt_id for p in result.enabled_prompts] == [no_assignment.id, reenabled.id]
    excluded = {p.core_prompt_id: p for p in result.excluded_prompts}
    assert excluded[global_prompt.id].reason == "explicit_disable"
    assert excluded[global_prompt.id].winning_scope_type == CorePromptScopeType.FOLDER
    inherited = next(item for item in result.enabled_prompts if item.core_prompt_id == no_assignment.id)
    assert inherited.reason == "inherited_global"
    assert inherited.winning_assignment_id is None
    reenabled_result = next(item for item in result.enabled_prompts if item.core_prompt_id == reenabled.id)
    assert reenabled_result.winning_scope_type == CorePromptScopeType.CONVERSATION


def test_unassigned_enabled_core_prompts_are_inherited_by_plain_project_and_folder_conversations(world) -> None:
    first = _create(world, "AVA PRIME DIRECTIVES")
    second = _create(world, "Always Include")
    now = datetime.now(UTC)
    world[4].create(ProjectRecord("project-a", "Project", now, now))
    world[5].create(ConversationFolderRecord("folder-a", "Folder", now, now))
    world[3].create("plain", title="Plain")
    world[3].create("project", title="Project", project_id="project-a")
    world[3].create("folder", title="Folder", folder_id="folder-a")

    expected_ids = {first.id, second.id}
    results = [
        world[2].resolve(PromptResolutionContext(conversation_id=conversation_id))
        for conversation_id in ("plain", "project", "folder")
    ]
    assert results[0].context.project_id is None and results[0].context.folder_id is None
    assert results[1].context.project_id == "project-a" and results[1].context.folder_id is None
    assert results[2].context.project_id is None and results[2].context.folder_id == "folder-a"
    for result in results:
        assert {item.core_prompt_id for item in result.enabled_prompts} == expected_ids
        assert all(item.winning_scope_type == CorePromptScopeType.GLOBAL for item in result.enabled_prompts)
        assert all(item.winning_assignment_id is None for item in result.enabled_prompts)


def test_folder_assignment_move_changes_only_folder_prompt_scope(world) -> None:
    folder_prompt = _create(world, "Folder-scoped")
    now = datetime.now(UTC)
    world[4].create(ProjectRecord("project-a", "Project", now, now))
    world[5].create(ConversationFolderRecord("folder-a", "Folder A", now, now))
    world[5].create(ConversationFolderRecord("folder-b", "Folder B", now, now))
    world[3].create("conversation-a", title="Chat", project_id="project-a")
    _assign(world, folder_prompt.id, CorePromptScopeType.GLOBAL, None, "disable")
    _assign(world, folder_prompt.id, CorePromptScopeType.FOLDER, "folder-a", "enable")

    world[3].set_folder("conversation-a", "folder-a")
    in_folder = world[2].resolve(PromptResolutionContext(conversation_id="conversation-a"))
    assert in_folder.context.project_id == "project-a" and in_folder.context.folder_id == "folder-a"
    assert [prompt.core_prompt_id for prompt in in_folder.enabled_prompts] == [folder_prompt.id]

    world[3].set_folder("conversation-a", "folder-b")
    in_other_folder = world[2].resolve(PromptResolutionContext(conversation_id="conversation-a"))
    assert in_other_folder.context.project_id == "project-a" and in_other_folder.context.folder_id == "folder-b"
    assert folder_prompt.id not in {prompt.core_prompt_id for prompt in in_other_folder.enabled_prompts}

    world[3].set_folder("conversation-a", None)
    ungrouped = world[2].resolve(PromptResolutionContext(conversation_id="conversation-a"))
    assert ungrouped.context.project_id == "project-a" and ungrouped.context.folder_id is None
    assert folder_prompt.id not in {prompt.core_prompt_id for prompt in ungrouped.enabled_prompts}


def test_runtime_capability_conflicts_disabled_definition_and_absent_targets(world) -> None:
    runtime = _create(world, "Runtime then project")
    capability = _create(world, "Capabilities")
    disabled = _create(world, "Disabled definition")
    _assign(world, runtime.id, CorePromptScopeType.GLOBAL, None, "enable")
    _assign(world, runtime.id, CorePromptScopeType.RUNTIME, "native", "disable")
    now = datetime.now(UTC)
    world[4].create(ProjectRecord("project-a", "Project", now, now))
    world[3].create("conversation-a", title="Chat", project_id="project-a")
    _assign(world, runtime.id, CorePromptScopeType.PROJECT, "project-a", "enable")
    # Two active capability targets share a tier; disable wins regardless of request set order.
    _assign(world, capability.id, CorePromptScopeType.CAPABILITY, "runs", "enable")
    _assign(world, capability.id, CorePromptScopeType.CAPABILITY, "tool_calling", "disable")
    _assign(world, disabled.id, CorePromptScopeType.GLOBAL, None, "enable")
    world[0].set_enabled(disabled.id, False)

    without_context = world[2].resolve(PromptResolutionContext())
    assert (
        next(item for item in without_context.enabled_prompts if item.core_prompt_id == runtime.id).winning_scope_type
        == CorePromptScopeType.GLOBAL
    )
    with_context = world[2].resolve(
        PromptResolutionContext(
            conversation_id="conversation-a", runtime_key="native", capabilities=frozenset({"runs", "tool_calling"})
        )
    )
    enabled = {p.core_prompt_id: p for p in with_context.enabled_prompts}
    excluded = {p.core_prompt_id: p for p in with_context.excluded_prompts}
    assert enabled[runtime.id].winning_scope_type == CorePromptScopeType.PROJECT
    assert excluded[capability.id].winning_scope_id == "tool_calling"
    assert excluded[disabled.id].reason == "definition_disabled"
    world[0].set_enabled(disabled.id, True)
    assert any(p.core_prompt_id == disabled.id for p in world[2].resolve(PromptResolutionContext()).enabled_prompts)


def test_no_conversation_membership_and_invalid_context_errors(world) -> None:
    capability_only = _create(world, "Capability only")
    runtime_only = _create(world, "Runtime only")
    _assign(world, capability_only.id, CorePromptScopeType.GLOBAL, None, "disable")
    _assign(world, runtime_only.id, CorePromptScopeType.GLOBAL, None, "disable")
    _assign(world, capability_only.id, CorePromptScopeType.CAPABILITY, "runs", "enable")
    _assign(world, runtime_only.id, CorePromptScopeType.RUNTIME, "native", "enable")
    no_context = world[2].resolve(PromptResolutionContext())
    assert all(item.core_prompt_id != capability_only.id for item in no_context.enabled_prompts)
    assert all(item.core_prompt_id != runtime_only.id for item in no_context.enabled_prompts)
    world[3].create("bare-conversation", title="Bare")
    bare = world[2].resolve(PromptResolutionContext(conversation_id="bare-conversation"))
    assert bare.context.project_id is None and bare.context.folder_id is None

    with pytest.raises(PromptResolutionError, match="Unknown conversation") as missing:
        world[2].resolve(PromptResolutionContext(conversation_id="missing"))
    assert missing.value.error_code == "conversation_not_found"
    with pytest.raises(PromptResolutionError) as bad_runtime:
        world[2].resolve(PromptResolutionContext(runtime_key="unknown"))
    assert bad_runtime.value.error_code == "runtime_not_found"
    with pytest.raises(PromptResolutionError) as bad_capability:
        world[2].resolve(PromptResolutionContext(capabilities=frozenset({"unknown"})))
    assert bad_capability.value.error_code == "capability_not_found"


def test_order_is_stable_and_resolution_does_not_mutate_records(world) -> None:
    later = _create(world, "zeta", CorePromptCategory.STYLE)
    earlier = _create(world, "Alpha", CorePromptCategory.CORE)
    _assign(world, later.id, CorePromptScopeType.GLOBAL, None, "enable")
    _assign(world, earlier.id, CorePromptScopeType.GLOBAL, None, "enable")
    before_defs = tuple(world[7].list())
    before_assignments = tuple(world[6].list_for_prompt(later.id)) + tuple(world[6].list_for_prompt(earlier.id))
    first = world[2].resolve(PromptResolutionContext())
    second = world[2].resolve(PromptResolutionContext())
    assert [item.core_prompt_id for item in first.enabled_prompts] == [earlier.id, later.id]
    assert first == second
    assert tuple(world[7].list()) == before_defs
    assert before_assignments == tuple(world[6].list_for_prompt(later.id)) + tuple(world[6].list_for_prompt(earlier.id))


def test_sqlite_restart_resolves_same_prompt_set(world, tmp_path: Path) -> None:
    database = world[8]
    if database is None:
        pytest.skip("Restart durability applies to SQLite")
    prompt = _create(world, "Durable")
    _assign(world, prompt.id, CorePromptScopeType.GLOBAL, None, "enable")
    expected = world[2].resolve(PromptResolutionContext())
    database.dispose()
    reopened = SqliteDatabase(str(tmp_path / "resolver.sqlite3"))
    try:
        actual = EffectivePromptResolver(
            prompts=RelationalCorePromptRepository(database=reopened),
            assignments=RelationalCorePromptAssignmentRepository(database=reopened),
            conversations=RelationalConversationRepository(database=reopened),
            runtime_ids=("native", "openhands"),
        ).resolve(PromptResolutionContext())
        assert actual == expected
    finally:
        reopened.dispose()


def test_prompt_delete_clears_assignments_and_resolver_provenance(world) -> None:
    prompt = _create(world, "Delete with assignments")
    _assign(world, prompt.id, CorePromptScopeType.GLOBAL, None, "enable")
    _assign(world, prompt.id, CorePromptScopeType.RUNTIME, "native", "disable")
    before = world[2].resolve(PromptResolutionContext(runtime_key="native"))
    assert prompt.id in {item.core_prompt_id for item in before.excluded_prompts}
    assert world[6].list_for_prompt(prompt.id)

    world[0].delete_core_prompt(prompt.id)
    after = world[2].resolve(PromptResolutionContext(runtime_key="native"))
    assert prompt.id not in {item.core_prompt_id for item in after.enabled_prompts}
    assert prompt.id not in {item.core_prompt_id for item in after.excluded_prompts}
    assert world[6].list_for_prompt(prompt.id) == []
