"""Application lifecycle for Project-file metadata and binary content."""

import logging
from collections.abc import Collection
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import uuid4

from ava.repositories.project_file import ProjectFileRecord, normalize_project_file_name
from ava.repositories.project_file_content import ProjectFileContentPort
from ava.repositories.project_file_repository import DuplicateProjectFileNameError, ProjectFileRepository
from ava.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class ProjectFileNotFoundError(Exception):
    """Raised for absent files and files outside the requested Project."""


class ProjectFileStorageError(Exception):
    """Raised when binary storage or compensating cleanup fails."""


class ProjectFileAlreadyExistsError(Exception):
    """Raised when a Project already contains the normalized filename."""

    def __init__(self, file_name: str) -> None:
        super().__init__(file_name)
        self.file_name = file_name


class ProjectFileService:
    def __init__(
        self,
        *,
        projects: ProjectRepository,
        files: ProjectFileRepository,
        content: ProjectFileContentPort,
    ) -> None:
        self._projects, self._files, self._content = projects, files, content

    def create(
        self,
        project_id: str,
        *,
        file_name: str,
        content_type: str | None,
        source: BinaryIO,
    ) -> ProjectFileRecord:
        self._require_project(project_id)
        if not file_name.strip():
            raise ValueError("file_name must not be blank")
        if content_type is not None and not content_type.strip():
            raise ValueError("content_type must not be blank when provided")
        normalized_name = normalize_project_file_name(file_name)
        existing = next(
            (
                item
                for item in self._files.list_by_project(project_id)
                if normalize_project_file_name(item.file_name) == normalized_name
            ),
            None,
        )
        if existing is not None:
            raise ProjectFileAlreadyExistsError(existing.file_name)
        file_id = str(uuid4())
        content_ref = uuid4().hex
        try:
            size = self._content.write(content_ref, source)
        except Exception as exc:
            raise ProjectFileStorageError("Could not store Project file content.") from exc
        try:
            now = datetime.now(UTC)
            record = ProjectFileRecord(file_id, project_id, file_name, content_type, size, content_ref, now, now)
            return self._files.create(record)
        except Exception as metadata_error:
            try:
                if not self._content.delete(content_ref):
                    raise FileNotFoundError("newly written Project file content was unexpectedly absent")
            except Exception as cleanup_error:
                logger.exception("Project file upload rollback failed for file_id=%s", file_id)
                raise ProjectFileStorageError(
                    "Project file metadata failed and stored content cleanup also failed."
                ) from cleanup_error
            if isinstance(metadata_error, DuplicateProjectFileNameError):
                raise ProjectFileAlreadyExistsError(metadata_error.file_name) from metadata_error
            raise metadata_error

    def list(self, project_id: str) -> list[ProjectFileRecord]:
        self._require_project(project_id)
        return list(self._files.list_by_project(project_id))

    def get(self, project_id: str, file_id: str) -> ProjectFileRecord:
        self._require_project(project_id)
        record = self._files.get(file_id)
        if record is None or record.project_id != project_id:
            raise ProjectFileNotFoundError(file_id)
        return record

    def open_content(self, project_id: str, file_id: str) -> BinaryIO:
        record = self.get(project_id, file_id)
        try:
            return self._content.read(record.content_ref)
        except Exception as exc:
            raise ProjectFileStorageError("Could not read Project file content.") from exc

    def delete(self, project_id: str, file_id: str) -> None:
        record = self.get(project_id, file_id)
        removed = self._files.delete(record.id)
        if removed is None:
            raise ProjectFileNotFoundError(file_id)
        self._delete_content((removed,))

    def delete_project(self, project_id: str) -> None:
        """Delete Project metadata first, then its exact transaction-owned bytes."""
        deleted, records = self._projects.delete_with_project_files(project_id, self._files)
        if not deleted:
            from ava.services.project_service import ProjectNotFoundError

            raise ProjectNotFoundError(project_id)
        self._delete_content(records)

    def _delete_content(self, records: Collection[ProjectFileRecord]) -> None:
        failures: list[tuple[str, Exception]] = []
        for record in records:
            try:
                self._content.delete(record.content_ref)
            except Exception as exc:
                failures.append((record.id, exc))
                logger.exception("Project file content cleanup failed for file_id=%s", record.id)
        if failures:
            raise ProjectFileStorageError(
                "Project file metadata was removed but binary content cleanup failed."
            ) from failures[0][1]

    def _require_project(self, project_id: str) -> None:
        # Local import avoids a module cycle: ProjectService delegates Project
        # deletion cleanup to this service, while both share the same error.
        from ava.services.project_service import ProjectNotFoundError

        if self._projects.get(project_id) is None:
            raise ProjectNotFoundError(project_id)
