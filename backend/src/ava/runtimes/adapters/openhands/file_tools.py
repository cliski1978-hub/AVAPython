"""Adapter-local OpenHands ``FileEditorTool`` with AVA workspace containment.

All OpenHands imports stay inside ``ava/runtimes/adapters/openhands/``. Core AVA
modules and contracts never import these types.

This module builds the *installed* OpenHands ``FileEditorTool`` (via its
registry) but forces every file operation through a containment gate:

- the requested path must canonically resolve inside the AVA-approved root;
- absolute escapes, ``..`` traversal, and symlink escapes (file or directory)
  are rejected deterministically before the installed editor moves a byte;
- a read-only workspace blocks every mutating command technically (not via
  prompt text).

Requires the optional ``openhands-tools`` dependency; import lazily from the
runtime only when an approved workspace asks for file tools.
"""

import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar

from openhands.sdk.tool import ToolAnnotations, register_tool
from openhands.tools.file_editor import FileEditorExecutor, FileEditorTool
from openhands.tools.file_editor.definition import (
    TOOL_DESCRIPTION,
    CommandLiteral,
    FileEditorAction,
    FileEditorObservation,
)
from openhands.tools.file_editor.editor import FileEditor
from openhands.tools.file_editor.exceptions import ToolError

from ava.execution.tool_security import ToolRunContext
from ava.runtimes.adapters.openhands.file_policy import FILE_EDITOR_TOOL_NAME
from ava.runtimes.adapters.openhands.tool_context import get_context

logger = logging.getLogger(__name__)


class FileSecurityError(ToolError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_IMAGE_VIEW_DESCRIPTION_LINE = (
    "* If `path` is an image file (.png, .jpg, .jpeg, .gif, .webp, .bmp), `view` displays the image content"
)


def _is_inside_root(path: Path, root: Path) -> bool:
    """Canonical descendant check: path must equal the root or live under it.

    ``resolve()`` follows symlinks for every path component, so a file or
    directory symlink that points outside the root yields an outside canonical
    path and is denied. A not-yet-existing path is checked via its existing
    parent's canonical location.
    """
    try:
        canonical = path.resolve()
    except (OSError, RuntimeError):
        return False
    return canonical == root or root in canonical.parents


class ContainedFileEditor(FileEditor):
    """Installed OpenHands file editor with AVA containment and read-only gate."""

    def __init__(self, workspace_root: str | None = None, *, read_only: bool = False) -> None:
        if workspace_root is None:
            raise ValueError("ContainedFileEditor requires an approved workspace root")
        root = Path(workspace_root)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("Approved workspace root must be an existing absolute directory")
        self._root = root.resolve(strict=True)
        super().__init__(workspace_root=str(self._root), max_file_size_mb=10)
        self._read_only = read_only

    def _require_contained(self, path: Path) -> None:
        if not _is_inside_root(path, self._root):
            raise FileSecurityError("path_outside_workspace", "Path is outside the approved AVA workspace")

    def validate_path(self, command: CommandLiteral, path: Path) -> None:
        """Containment and read-only policy gate, then the installed validation."""
        self._require_contained(path)
        if command not in {"view", "create", "str_replace", "insert", "undo_edit"}:
            raise FileSecurityError("delete_not_authorized", "File deletion is disabled")
        if self._read_only and command != "view":
            raise FileSecurityError("write_not_authorized", "The approved AVA workspace is read-only")
        super().validate_path(command, path)
        if path.exists() and not path.is_dir():
            self.validate_file(path)

    def validate_file(self, path: Path) -> None:
        self._require_contained(path)
        if path.exists() and not path.is_file():
            raise FileSecurityError("unsafe_file_type", "Only regular files are supported")
        if path.is_file() and path.stat().st_nlink > 1:
            raise FileSecurityError("unsafe_file_type", "Hard-linked files are not supported")
        if path.is_file() and path.stat().st_size > self._max_file_size:
            raise FileSecurityError("file_size_limit", "File exceeds the AVA 10 MiB file-size limit")
        super().validate_file(path)

    def write_file(self, path: Path, file_text: str, encoding: str = "utf-8") -> None:
        self._require_contained(path)
        if self._read_only:
            raise FileSecurityError("write_not_authorized", "The approved AVA workspace is read-only")
        try:
            size = len(file_text.encode(encoding))
        except UnicodeEncodeError:
            size = len(file_text.encode("utf-8"))
        if size > self._max_file_size:
            raise FileSecurityError("file_size_limit", "File exceeds the AVA 10 MiB file-size limit")
        if path.exists():
            self.validate_file(path)
        super().write_file(path, file_text, encoding=encoding)

    def _list_directory_for_view(self, path: Path) -> list[str]:
        """List a directory, dropping entries that resolve outside the root.

        Prevents a symlinked subdirectory pointing outside the workspace from
        leaking outside metadata through the directory listing.
        """
        visible_entries = [
            entry
            for entry in (path, *sorted(path.iterdir(), key=lambda p: str(p)))
            if not entry.name.startswith(".") and _is_inside_root(entry, self._root)
        ]
        visible: list[Path] = [path]
        for entry in visible_entries:
            if entry == path:
                continue
            visible.append(entry)
            if entry.is_dir():
                with suppress(OSError):
                    visible.extend(
                        child
                        for child in sorted(entry.iterdir(), key=lambda p: str(p))
                        if not child.name.startswith(".") and _is_inside_root(child, self._root)
                    )
        return [self._format_directory_entry(path, entry) for entry in visible]


class ContainedFileEditorExecutor(FileEditorExecutor):
    """Installed executor equipped with the contained editor."""

    def __init__(
        self,
        workspace_root: str,
        *,
        read_only: bool = False,
        context: ToolRunContext | None = None,
    ) -> None:
        self.editor: FileEditor = ContainedFileEditor(workspace_root=workspace_root, read_only=read_only)
        self.allowed_edits_files: set[Path] | None = None
        self._context = context or ToolRunContext("internal", "openhands")

    def __call__(self, action: FileEditorAction, conversation: Any = None) -> FileEditorObservation:
        operation = "file.read" if action.command == "view" else "file.write"
        context = self._context
        if context.revoked.is_set():
            context.record(FILE_EDITOR_TOOL_NAME, operation, "denied", "run_cancelled")
            return FileEditorObservation.from_text(
                text="Run cancelled",
                command=action.command,
                is_error=True,
            )
        try:
            # Invoke the editor directly so typed denials do not get flattened
            # into SDK error strings containing user paths or file contents.
            result = self.editor(
                command=action.command,
                path=action.path,
                file_text=action.file_text,
                view_range=action.view_range,
                old_str=action.old_str,
                new_str=action.new_str,
                insert_line=action.insert_line,
            )
        except FileSecurityError as exc:
            context.record(FILE_EDITOR_TOOL_NAME, operation, "denied", exc.reason_code)
            return FileEditorObservation.from_text(text=exc.message, command=action.command, is_error=True)
        except Exception:
            logger.exception("Contained file operation failed")
            context.record(FILE_EDITOR_TOOL_NAME, operation, "failure", "file_operation_failed")
            return FileEditorObservation.from_text(
                text="File operation failed",
                command=action.command,
                is_error=True,
            )
        context.record(
            FILE_EDITOR_TOOL_NAME,
            operation,
            "failure" if result.is_error else "success",
            "file_operation_failed" if result.is_error else "allowed",
        )
        if result.is_error:
            return FileEditorObservation.from_text(
                text="File operation failed",
                command=action.command,
                is_error=True,
            )
        return result


class AvaFileEditorTool(FileEditorTool):
    """FileEditorTool registered under the canonical name, fully contained.

    The canonical ``file_editor`` name is kept so the model sees the standard
    OpenHands tool shape; the executor is ``ContainedFileEditorExecutor``.
    """

    name: ClassVar[str] = FILE_EDITOR_TOOL_NAME

    @classmethod
    def create(
        cls,
        conv_state: Any,
        *,
        read_only: bool = False,
        security_context_id: str | None = None,
    ) -> list["AvaFileEditorTool"]:
        workspace_root = conv_state.workspace.working_dir
        executor = ContainedFileEditorExecutor(
            workspace_root=workspace_root,
            read_only=read_only,
            context=get_context(security_context_id) if security_context_id is not None else None,
        )
        description = _file_editor_description(workspace_root, conv_state, read_only=read_only)
        return [
            cls(
                action_type=FileEditorAction,
                observation_type=FileEditorObservation,
                description=description,
                annotations=ToolAnnotations(
                    title="file_editor",
                    readOnlyHint=read_only,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
                executor=executor,
            )
        ]


def _file_editor_description(workspace_root: str, conv_state: Any, *, read_only: bool) -> str:
    """Replicate the installed tool description plus the AVA root guidance."""
    vision = bool(
        getattr(conv_state, "agent", None) is not None
        and getattr(conv_state.agent, "llm", None) is not None
        and conv_state.agent.llm.vision_is_active()
    )
    description_lines = TOOL_DESCRIPTION.split("\n")
    if vision:
        tool_description = (
            f"{'\n'.join(description_lines[:2])}\n{_IMAGE_VIEW_DESCRIPTION_LINE}\n{'\n'.join(description_lines[2:])}"
        )
    else:
        tool_description = TOOL_DESCRIPTION
    mode = "read-only; existing files cannot be created, modified, or reverted"
    if not read_only:
        mode = "read/write within the approved workspace root"
    return (
        f"{tool_description}\n\n"
        f"Your current working directory is: {workspace_root}\n"
        f"When exploring project structure, start with this directory "
        f"instead of the root filesystem.\n"
        f"This tool is restricted to the approved AVA workspace root: "
        f"{workspace_root}. Permission mode: {mode}."
    )


_REGISTERED: bool = False


def ensure_registered() -> None:
    """Register the contained editor exactly once per process.

    The installed OpenHands module registers the raw ``file_editor`` on import;
    this replaces it with the contained implementation. Idempotent so repeated
    runtime calls never double-register.
    """
    global _REGISTERED
    if not _REGISTERED:
        register_tool(FILE_EDITOR_TOOL_NAME, AvaFileEditorTool)
        _REGISTERED = True


ensure_registered()
