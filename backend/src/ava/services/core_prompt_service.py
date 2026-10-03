"""Application behavior for durable CORE prompt definitions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ava.contracts.core_prompts import CreateCorePromptRequest, UpdateCorePromptRequest
from ava.repositories.core_prompt import CorePromptRecord
from ava.repositories.core_prompt_repository import CorePromptRepository


class CorePromptNotFoundError(Exception):
    """Raised when an operation targets an unknown CORE prompt."""

    def __init__(self, core_prompt_id: str) -> None:
        self.core_prompt_id = core_prompt_id
        super().__init__(f"Unknown CORE prompt: {core_prompt_id}")


class InvalidCorePromptNameError(ValueError):
    """Raised when a prompt display name is blank after trimming."""


class InvalidCorePromptTextError(ValueError):
    """Raised when prompt text contains no non-whitespace content."""


class DuplicateCorePromptIdentityError(Exception):
    """Raised if the generated CORE prompt identity collides with storage."""


class CorePromptService:
    """Own prompt identity, validation, timestamps, enable state, and deletion."""

    def __init__(self, *, core_prompt_repository: CorePromptRepository) -> None:
        self._prompts = core_prompt_repository

    def create_core_prompt(self, request: CreateCorePromptRequest) -> CorePromptRecord:
        name = self._normalize_name(request.name)
        self._validate_prompt_text(request.prompt_text)
        now = datetime.now(UTC)
        prompt = CorePromptRecord(
            id=str(uuid4()),
            name=name,
            description=request.description,
            prompt_text=request.prompt_text,
            category=request.category,
            is_enabled=True,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._prompts.create(prompt)
        except ValueError as exc:
            raise DuplicateCorePromptIdentityError(
                "Could not create CORE prompt due to an identity collision."
            ) from exc

    def get_core_prompt(self, core_prompt_id: str) -> CorePromptRecord:
        prompt = self._prompts.get(core_prompt_id)
        if prompt is None:
            raise CorePromptNotFoundError(core_prompt_id)
        return prompt

    def list_core_prompts(self) -> list[CorePromptRecord]:
        return list(self._prompts.list())

    def update_core_prompt(self, core_prompt_id: str, request: UpdateCorePromptRequest) -> CorePromptRecord:
        current = self.get_core_prompt(core_prompt_id)
        name = self._normalize_name(request.name)
        self._validate_prompt_text(request.prompt_text)
        updated = replace(
            current,
            name=name,
            description=request.description if "description" in request.model_fields_set else current.description,
            prompt_text=request.prompt_text,
            category=request.category,
            updated_at=self._next_updated_at(current.updated_at),
        )
        persisted = self._prompts.update(updated)
        if persisted is None:
            raise CorePromptNotFoundError(core_prompt_id)
        return persisted

    def set_enabled(self, core_prompt_id: str, is_enabled: bool) -> CorePromptRecord:
        current = self.get_core_prompt(core_prompt_id)
        if current.is_enabled == is_enabled:
            return current
        persisted = self._prompts.set_enabled(
            core_prompt_id,
            is_enabled,
            self._next_updated_at(current.updated_at),
        )
        if persisted is None:
            raise CorePromptNotFoundError(core_prompt_id)
        return persisted

    def delete_core_prompt(self, core_prompt_id: str) -> None:
        if not self._prompts.delete(core_prompt_id):
            raise CorePromptNotFoundError(core_prompt_id)

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise InvalidCorePromptNameError("CORE prompt name must not be blank.")
        return normalized

    @staticmethod
    def _validate_prompt_text(prompt_text: str) -> None:
        if not prompt_text.strip():
            raise InvalidCorePromptTextError("CORE prompt text must not be blank.")

    @staticmethod
    def _next_updated_at(previous: datetime) -> datetime:
        now = datetime.now(UTC)
        if now <= previous:
            return previous + timedelta(microseconds=1)
        return now
