"""Fail-closed local Workspace filesystem adapter using Linux openat2."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import os
import platform
import stat
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.tools import ToolResult, ToolStatus
from ava.services.tool_execution_service import AuthorizedToolInvocation

_SYS_OPENAT2 = 437
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_MAX_READ_BYTES = 1_048_576
_MAX_DIRECTORY_ENTRIES = 100
_MAX_DIRECTORY_SCAN = 10_000
_PSEUDO_FS_TYPES = {
    0x9FA0,  # proc
    0x62656572,  # sysfs
    0x1373,  # devtmpfs
    0x27E0EB,  # cgroup
    0x63677270,  # cgroup2
    0x74726163,  # tracefs
    0x64626720,  # debugfs
    0x6E736673,  # nsfs
    0xCAFE4A11,  # bpf
    0x65735543,  # fusectl
    0x73636673,  # securityfs
}
_SUPPORTED_LOCAL_FS_TYPES = {
    0xEF53,  # ext2/3/4
    0x58465342,  # xfs
    0x9123683E,  # btrfs
    0x794C7630,  # overlayfs
    0x01021994,  # tmpfs
}


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64)]


class LinuxWorkspaceFilesystemAdapter:
    """Linux implementation of AVA's read-only Workspace filesystem port."""

    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        if not isinstance(invocation, AuthorizedToolInvocation):
            raise TypeError("service authorization required")
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        # Operations are capped at one MiB / ten thousand directory entries;
        # synchronous handle ownership ensures cancellation cannot leak a worker.
        return self._execute_sync(invocation)

    def _execute_sync(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        request = invocation.request
        try:
            if invocation.workspace_id != invocation.workspace.workspace_id:
                return _error(invocation, "workspace_changed", "The authorized Workspace binding changed.")
            workspace = invocation.workspace
            root = workspace.local_path
            if (
                root is None
                or not root.is_absolute()
                or not workspace.permissions.read
                or workspace.configuration_revision < 0
                or (
                    workspace.configured_capabilities is not None
                    and "file_read" not in workspace.configured_capabilities
                )
            ):
                return _error(invocation, "workspace_unavailable", "The authorized Workspace is unavailable.")
            if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
                return _error(invocation, "secure_filesystem_unavailable", "Secure Workspace access is unavailable.")
            root_fd = _open_workspace_root(root)
            try:
                arguments = request.arguments
                relative = _relative_path(arguments.get("path"), allow_root=request.tool_id == "workspace.list_files")
                if relative is None:
                    return _error(invocation, "invalid_path", "The Workspace path is invalid.")
                if request.tool_id == "workspace.list_files":
                    return _list_files(invocation, root_fd, relative)
                if request.tool_id == "workspace.read_file":
                    return _read_file(invocation, root_fd, relative)
                if request.tool_id == "workspace.file_info":
                    return _file_info(invocation, root_fd, relative)
                return _error(invocation, "unknown_tool", "The Workspace tool is unavailable.")
            finally:
                os.close(root_fd)
        except FileNotFoundError:
            return _error(invocation, "not_found", "The requested Workspace entry was not found.")
        except PermissionError:
            return _error(invocation, "permission_denied", "Access to the Workspace entry was denied.")
        except (ValueError, UnicodeError):
            return _error(invocation, "invalid_path", "The Workspace path is invalid.")
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EXDEV, errno.ENOTDIR):
                return _error(invocation, "security_validation_failed", "The Workspace entry failed security checks.")
            if exc.errno == errno.EACCES:
                return _error(invocation, "permission_denied", "Access to the Workspace entry was denied.")
            if exc.errno == errno.ENOENT:
                return _error(invocation, "not_found", "The requested Workspace entry was not found.")
            if exc.errno in (errno.ENOSYS, errno.E2BIG, errno.EINVAL, errno.EPERM):
                return _error(invocation, "secure_filesystem_unavailable", "Secure Workspace access is unavailable.")
            return _error(invocation, "workspace_access_failed", "The Workspace entry could not be accessed.")
        except Exception:
            return _error(invocation, "tool_execution_failed", "The Workspace tool could not complete.")


def _open_workspace_root(root: Path) -> int:
    if not hasattr(os, "O_PATH") or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise OSError(errno.ENOSYS, "secure filesystem unavailable")
    if root.resolve(strict=True) != root:
        raise OSError(errno.ELOOP, "workspace root is not canonical")
    fd = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        current = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise OSError(errno.ESTALE, "workspace root changed")
        # Linux statfs starts with the filesystem type as a native signed long.
        statfs = ctypes.create_string_buffer(256)
        if ctypes.CDLL(None, use_errno=True).fstatfs(ctypes.c_int(fd), statfs) != 0:
            raise OSError(ctypes.get_errno(), "workspace filesystem could not be verified")
        fs_type = struct.unpack_from("@l", statfs.raw)[0] & 0xFFFFFFFF
        if fs_type in _PSEUDO_FS_TYPES or fs_type not in _SUPPORTED_LOCAL_FS_TYPES:
            raise OSError(errno.EXDEV, "unsupported workspace filesystem")
        # Probe openat2 on the actual root; no fallback to weaker path APIs.
        probe_fd = _openat2(fd, ".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        os.close(probe_fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _openat2(directory_fd: int, path: str, flags: int) -> int:
    how = _OpenHow(
        flags=flags | os.O_CLOEXEC | os.O_NOFOLLOW,
        mode=0,
        resolve=_RESOLVE_BENEATH | _RESOLVE_NO_SYMLINKS | _RESOLVE_NO_MAGICLINKS | _RESOLVE_NO_XDEV,
    )
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        ctypes.c_long(_SYS_OPENAT2),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(os.fsencode(path)),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(result)


def _relative_path(value: Any, *, allow_root: bool) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
        or (len(value) > 1 and value[0].isalpha() and value[1] == ":")
    ):
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if value == ".":
        return "." if allow_root else None
    parts = value.split("/")
    if any(not part or part in {"..", "."} for part in parts):
        return None
    return "/".join(parts)


def _open_entry(directory_fd: int, relative: str, *, directory: bool = False) -> int:
    flags = os.O_RDONLY | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    return _openat2(directory_fd, relative, flags)


def _list_files(invocation: AuthorizedToolInvocation, root_fd: int, relative: str) -> ToolResult:
    args = invocation.request.arguments
    limit = args.get("limit", 50)
    cursor = args.get("cursor", "0")
    if type(limit) is not int or not 1 <= limit <= _MAX_DIRECTORY_ENTRIES:
        return _error(invocation, "invalid_arguments", "The requested page size is invalid.")
    if not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdigit() or len(cursor) > 12:
        return _error(invocation, "invalid_arguments", "The directory cursor is invalid.")
    offset = int(cursor)
    directory_fd = _open_entry(root_fd, relative, directory=True)
    try:
        names: list[str] = []
        with os.scandir(directory_fd) as entries_iter:
            for entry in entries_iter:
                try:
                    entry.name.encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    continue
                names.append(entry.name)
                if len(names) > _MAX_DIRECTORY_SCAN:
                    return _error(invocation, "directory_too_large", "The directory exceeds the safe listing limit.")
        names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
        page = names[offset : offset + limit]
        entries: list[dict[str, Any]] = []
        for name in page:
            if "\x00" in name:
                continue
            try:
                fd = _open_entry(directory_fd, name, directory=True)
                entry_type = "directory"
                info = os.fstat(fd)
                os.close(fd)
            except OSError as directory_error:
                if directory_error.errno == errno.ENOTDIR:
                    fd = _open_entry(directory_fd, name)
                    try:
                        info = os.fstat(fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                            continue
                        entry_type = "file"
                    finally:
                        os.close(fd)
                elif directory_error.errno in (errno.ENOENT, errno.ELOOP, errno.EACCES):
                    continue
                else:
                    raise
            if entry_type == "directory" and not stat.S_ISDIR(info.st_mode):
                continue
            entry_result: dict[str, Any] = {
                "name": name,
                "type": entry_type,
                "modified_at": _timestamp(info.st_mtime_ns),
            }
            if entry_type == "file":
                entry_result["size_bytes"] = info.st_size
            entries.append(entry_result)
        next_offset = offset + len(page)
        output: dict[str, Any] = {"entries": entries}
        if next_offset < len(names):
            output["next_cursor"] = str(next_offset)
        return _success(invocation, output)
    finally:
        os.close(directory_fd)


def _read_file(invocation: AuthorizedToolInvocation, root_fd: int, relative: str) -> ToolResult:
    max_bytes = invocation.request.arguments.get("max_bytes", _MAX_READ_BYTES)
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_READ_BYTES:
        return _error(invocation, "invalid_arguments", "The requested read limit is invalid.")
    fd = _open_entry(root_fd, relative)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            return _error(invocation, "unsupported_file_type", "Only unlinked regular files can be read.")
        raw = os.read(fd, max_bytes + 1)
        truncated = len(raw) > max_bytes or info.st_size > max_bytes
        content_bytes = raw[:max_bytes]
        try:
            content = content_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            if truncated and exc.end == len(content_bytes) and exc.reason == "unexpected end of data":
                content = content_bytes[: exc.start].decode("utf-8", errors="strict")
            else:
                return _error(invocation, "decode_failure", "The file is not valid UTF-8 text.")
        return _success(
            invocation,
            {
                "content": content,
                "encoding": "utf-8",
                "truncated": truncated,
                "size_bytes": min(info.st_size, _MAX_READ_BYTES + 1),
            },
        )
    finally:
        os.close(fd)


def _file_info(invocation: AuthorizedToolInvocation, root_fd: int, relative: str) -> ToolResult:
    fd = _open_entry(root_fd, relative)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            return _error(invocation, "unsupported_file_type", "Only unlinked regular files are supported.")
        return _success(
            invocation,
            {
                "type": "file",
                "size_bytes": min(info.st_size, _MAX_READ_BYTES + 1),
                "modified_at": _timestamp(info.st_mtime_ns),
            },
        )
    finally:
        os.close(fd)


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat()


def _success(invocation: AuthorizedToolInvocation, output: dict[str, Any]) -> ToolResult:
    return ToolResult(
        invocation_id=invocation.request.invocation_id,
        tool_id=invocation.request.tool_id,
        tool_version=invocation.request.tool_version,
        status=ToolStatus.COMPLETED,
        output=output,
    )


def _error(invocation: AuthorizedToolInvocation, code: str, message: str) -> ToolResult:
    return ToolResult(
        invocation_id=invocation.request.invocation_id,
        tool_id=invocation.request.tool_id,
        tool_version=invocation.request.tool_version,
        status=ToolStatus.FAILED,
        error=ErrorResponse(error_code=code, category=ErrorCategory.UNAVAILABLE, message=message),
    )
