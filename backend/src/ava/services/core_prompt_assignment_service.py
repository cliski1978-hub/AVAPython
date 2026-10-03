"""Explicit assignment writes and queries; deliberately performs no resolution."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ava.contracts.capabilities import CapabilityName
from ava.repositories.conversation_folder_repository import ConversationFolderRepository
from ava.repositories.conversation_repository import ConversationRepository
from ava.repositories.core_prompt_assignment import (
    CorePromptAssignmentMode,
    CorePromptAssignmentRecord,
    CorePromptScopeType,
)
from ava.repositories.core_prompt_assignment_repository import CorePromptAssignmentRepository
from ava.repositories.core_prompt_repository import CorePromptRepository
from ava.repositories.project_repository import ProjectRepository


class CorePromptAssignmentError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


class CorePromptAssignmentService:
    def __init__(
        self,
        *,
        assignments: CorePromptAssignmentRepository,
        prompts: CorePromptRepository,
        projects: ProjectRepository,
        folders: ConversationFolderRepository,
        conversations: ConversationRepository,
        runtime_ids: Collection[str] = (),
    ) -> None:
        self._assignments, self._prompts = assignments, prompts
        self._projects, self._folders, self._conversations = projects, folders, conversations
        self._runtime_ids = frozenset(runtime_ids)

    def list_for_prompt(self, prompt_id: str) -> list[CorePromptAssignmentRecord]:
        self._require_prompt(prompt_id)
        return list(self._assignments.list_for_prompt(prompt_id))

    def get_assignment(
        self, prompt_id: str, scope: CorePromptScopeType, scope_id: str | None
    ) -> CorePromptAssignmentRecord | None:
        self._require_prompt(prompt_id)
        self._validate_scope(scope, scope_id)
        return self._assignments.get_explicit(prompt_id, scope, scope_id)

    def list_for_scope(self, scope: CorePromptScopeType, scope_id: str | None) -> list[CorePromptAssignmentRecord]:
        self._validate_scope(scope, scope_id)
        return list(self._assignments.list_for_scope(scope, scope_id))

    def set_assignment(
        self, prompt_id: str, scope: CorePromptScopeType, scope_id: str | None, state: str
    ) -> CorePromptAssignmentRecord | None:
        self._require_prompt(prompt_id)
        self._validate_scope(scope, scope_id)
        current = self._assignments.get_explicit(prompt_id, scope, scope_id)
        if state == "inherit":
            self._assignments.delete_explicit(prompt_id, scope, scope_id)
            return None
        try:
            mode = CorePromptAssignmentMode(state)
        except ValueError as exc:
            raise CorePromptAssignmentError(
                "core_prompt_assignment_state_invalid", "State must be inherit, enable, or disable."
            ) from exc
        if current is not None and current.mode == mode:
            return current
        now = datetime.now(UTC)
        if current is not None and now <= current.updated_at:
            now = current.updated_at + timedelta(microseconds=1)
        record = CorePromptAssignmentRecord(
            id=current.id if current else str(uuid4()),
            core_prompt_id=prompt_id,
            scope_type=scope,
            scope_id=scope_id,
            mode=mode,
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        return self._assignments.upsert_explicit(record)

    def _require_prompt(self, prompt_id: str) -> None:
        if self._prompts.get(prompt_id) is None:
            raise CorePromptAssignmentError("core_prompt_not_found", f"Unknown CORE prompt: {prompt_id}")

    def _validate_scope(self, scope: CorePromptScopeType, scope_id: str | None) -> None:
        if scope == CorePromptScopeType.GLOBAL:
            if scope_id is not None:
                raise CorePromptAssignmentError("core_prompt_scope_invalid", "Global scope_id must be null.")
            return
        if scope_id is None or not scope_id.strip():
            raise CorePromptAssignmentError("core_prompt_scope_invalid", "Target scope_id must be nonblank.")
        if scope == CorePromptScopeType.RUNTIME:
            if scope_id not in self._runtime_ids:
                raise CorePromptAssignmentError(
                    "core_prompt_scope_target_not_found", f"Unknown runtime registry key: {scope_id}"
                )
            return
        if scope == CorePromptScopeType.CAPABILITY:
            try:
                CapabilityName(scope_id)
            except ValueError as exc:
                raise CorePromptAssignmentError(
                    "core_prompt_scope_target_not_found", f"Unknown capability name: {scope_id}"
                ) from exc
            return
        exists: object | None
        if scope == CorePromptScopeType.PROJECT:
            exists, code, label = self._projects.get(scope_id), "project_not_found", "Project"
        elif scope == CorePromptScopeType.FOLDER:
            exists, code, label = self._folders.get(scope_id), "conversation_folder_not_found", "Conversation folder"
        elif scope == CorePromptScopeType.CONVERSATION:
            exists, code, label = self._conversations.get(scope_id), "conversation_not_found", "Conversation"
        else:
            raise CorePromptAssignmentError(
                "core_prompt_scope_unsupported", f"Assignments for scope {scope.value!r} are not currently supported."
            )
        if exists is None:
            raise CorePromptAssignmentError(code, f"Unknown {label}: {scope_id}")
