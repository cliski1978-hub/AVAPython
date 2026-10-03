"""Phase 5.81 cross-feature deletion ownership certification."""

from datetime import UTC, datetime
from io import BytesIO

import pytest

from ava.configuration.settings import Settings
from ava.infrastructure.composition import create_application_persistence, create_conversation_hard_delete_coordinator
from ava.repositories.conversation_folder import ConversationFolderRecord
from ava.repositories.core_prompt import CorePromptCategory, CorePromptRecord
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.project import ProjectExecutionDefaults, ProjectRecord
from ava.repositories.project_file import ProjectFileRecord
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.conversation_service import ConversationService
from ava.services.project_file_content_store import InMemoryProjectFileContentStore
from ava.services.project_file_service import ProjectFileService
from ava.services.project_service import ProjectService


@pytest.mark.parametrize("provider", ["memory", "relational"])
def test_conversation_folder_project_prompt_and_file_deletion_matrix(provider: str, tmp_path) -> None:
    """Delete in two orders while asserting each durable resource's owner survives correctly."""
    persistence = create_application_persistence(
        Settings(
            persistence_provider=provider,
            persistence_database_url=str(tmp_path / f"cleanup-{provider}.sqlite3"),
        )
    )
    now = datetime.now(UTC)
    folders = persistence.conversation_folder_repository
    projects = persistence.project_repository
    conversations = persistence.conversation_repository
    prompts = persistence.core_prompt_repository
    assignments = persistence.core_prompt_assignment_repository
    files = persistence.project_file_repository
    content = InMemoryProjectFileContentStore()
    try:
        folders.create(ConversationFolderRecord("folder-f", "Folder F", now, now))
        projects.create(ProjectRecord(
            "project-p", "Project P", now, now, instructions="Project-owned instructions",
            execution_defaults=ProjectExecutionDefaults(runtime_key="native"),
        ))
        conversations.create("conversation-c1", title="C1", project_id="project-p", folder_id="folder-f")
        conversations.create("conversation-c2", title="C2", project_id="project-p", folder_id="folder-f")
        conversations.set_archived("conversation-c2", True)

        prompt = CorePromptRecord(
            "prompt-cp", "Prompt CP", None, "Prompt text", CorePromptCategory.GENERAL, False, now, now
        )
        prompts.create(prompt)
        scopes = (
            (CorePromptScopeType.GLOBAL, None),
            (CorePromptScopeType.PROJECT, "project-p"),
            (CorePromptScopeType.FOLDER, "folder-f"),
            (CorePromptScopeType.CONVERSATION, "conversation-c1"),
            (CorePromptScopeType.RUNTIME, "native"),
            (CorePromptScopeType.CAPABILITY, "runs"),
        )
        for index, (scope, scope_id) in enumerate(scopes):
            assignments.upsert_explicit(CorePromptAssignmentRecord(
                f"assignment-{index}", "prompt-cp", scope, scope_id,
                CorePromptAssignmentMode.DISABLE, now, now,
            ))

        for file_id, name, reference, body in (
            ("file-a", "spec.pdf", "ref-a", b"contents A"),
            ("file-b", "spec.pdf", "ref-b", b"contents B"),
        ):
            content.write(reference, BytesIO(body))
            files.create(ProjectFileRecord(
                file_id, "project-p", name, "application/pdf", len(body), reference, now, now
            ))

        # Conversation owns its scoped metadata, but not its Folder or Project.
        conversation_service = ConversationService(
            conversation_repository=conversations,
            message_repository=persistence.message_repository,
            run_repository=persistence.run_repository,
            run_event_repository=persistence.run_event_repository,
            hard_delete_coordinator=create_conversation_hard_delete_coordinator(persistence),
            attachment_content_store=InMemoryAttachmentContentStore(),
            project_repository=projects,
            folder_repository=folders,
        )
        assert conversation_service.delete_conversation("conversation-c1") is True
        assert conversations.get("conversation-c1") is None
        assert folders.get("folder-f") is not None
        assert projects.get("project-p") is not None
        assert assignments.list_for_scope(CorePromptScopeType.CONVERSATION, "conversation-c1") == []

        # Project deletion detaches, but does not delete, active or archived chats;
        # the independent Folder membership survives. Same-name file B survives
        # deletion of file A by identity, then Project deletion owns both refs.
        project_files = ProjectFileService(projects=projects, files=files, content=content)
        project_files.delete("project-p", "file-a")
        assert files.get("file-a") is None and files.get("file-b") is not None
        assert not content.exists("ref-a") and content.exists("ref-b")
        ProjectService(project_repository=projects, project_file_service=project_files).delete_project("project-p")
        surviving = conversations.get("conversation-c2")
        assert surviving is not None and surviving.project_id is None and surviving.folder_id == "folder-f"
        assert projects.get("project-p") is None
        assert files.list_by_project("project-p") == []
        assert not content.exists("ref-b")
        assert assignments.list_for_scope(CorePromptScopeType.PROJECT, "project-p") == []
        assert surviving.is_archived is True

        # Folder deletion preserves the archived chat and clears only its Folder ID.
        assert folders.delete("folder-f") is True
        surviving = conversations.get("conversation-c2")
        assert surviving is not None and surviving.project_id is None and surviving.folder_id is None
        assert surviving.is_archived is True
        assert assignments.list_for_scope(CorePromptScopeType.FOLDER, "folder-f") == []

        # Prompt deletion clears retained disabled and non-durable-scope overrides too.
        assert len(assignments.list_for_prompt("prompt-cp")) == 3
        assert prompts.delete("prompt-cp") is True
        assert assignments.list_for_prompt("prompt-cp") == []

        # Archived hard delete follows the same ownership cleanup and cannot affect
        # already deleted Project/Folder resources.
        assert conversation_service.delete_conversation("conversation-c2") is True
        assert conversations.get("conversation-c2") is None
        assert projects.get("project-p") is None and folders.get("folder-f") is None

        if persistence.database is not None:
            with persistence.database.connect() as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                assert connection.execute(
                    "SELECT count(*) FROM project_files f LEFT JOIN projects p ON p.id=f.project_id "
                    "WHERE p.id IS NULL"
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT count(*) FROM core_prompt_assignments a LEFT JOIN core_prompts p "
                    "ON p.id=a.core_prompt_id WHERE p.id IS NULL"
                ).fetchone()[0] == 0
            persistence.dispose()
            reopened = create_application_persistence(Settings(
                persistence_provider="relational",
                persistence_database_url=str(tmp_path / "cleanup-relational.sqlite3"),
            ))
            try:
                assert reopened.conversation_repository.get("conversation-c1") is None
                assert reopened.conversation_repository.get("conversation-c2") is None
                assert reopened.project_repository.get("project-p") is None
                assert reopened.conversation_folder_repository.get("folder-f") is None
                assert reopened.core_prompt_repository.get("prompt-cp") is None
                assert reopened.project_file_repository.list_by_project("project-p") == []
            finally:
                reopened.dispose()
    finally:
        persistence.dispose()
