"""Windows-native, handle-relative Workspace reads.

This adapter intentionally supports only local NTFS volumes. It opens each
path component relative to an already-open directory handle with NtCreateFile,
rejects reparse points and multi-link files by handle metadata, and never
falls back to pathlib/open for an entry lookup.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import re
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.tools import ToolResult, ToolStatus
from ava.services.tool_execution_service import AuthorizedToolInvocation

_MAX_READ_BYTES = 1_048_576
_MAX_DIRECTORY_ENTRIES = 100
_MAX_DIRECTORY_SCAN = 10_000

_GENERIC_READ = 0x80000000
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_LIST_DIRECTORY = 0x0001
_SYNCHRONIZE = 0x00100000
_SHARE_READ_WRITE = 0x00000003  # Deliberately excludes FILE_SHARE_DELETE.
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_OPEN = 1
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_OBJ_CASE_INSENSITIVE = 0x00000040
_OBJ_DONT_REPARSE = 0x00001000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_TAG_INFO = 9
_FILE_STANDARD_INFO = 1
_FILE_BASIC_INFO = 0
_FILE_ID_INFO = 18
_FILE_ID_BOTH_DIR_INFO = 37
_NTFS = "NTFS"
_DRIVE_FIXED = 3
_ERROR_NO_MORE_FILES = 18
_STATUS_NO_MORE_FILES = 0x80000006
_STATUS_NO_SUCH_FILE = 0xC000000F
_LOGGER = logging.getLogger(__name__)


class _UnicodeString(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", wintypes.LPWSTR)]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]


class _FileStandardInfo(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("NumberOfLinks", wintypes.DWORD),
        ("DeletePending", wintypes.BOOLEAN),
        ("Directory", wintypes.BOOLEAN),
    ]


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
    ]


class _FileIdInfo(ctypes.Structure):
    _fields_ = [("VolumeSerialNumber", ctypes.c_ulonglong), ("FileId", ctypes.c_ubyte * 16)]


class _FileIdBothDirectoryInfo(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("FileIndex", wintypes.DWORD),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("EaSize", wintypes.DWORD),
        ("ShortNameLength", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("ShortName", wintypes.WCHAR * 12),
        ("FileId", ctypes.c_longlong),
        ("FileName", wintypes.WCHAR * 1),
    ]


class _WindowsApi:
    """Late-bound Windows APIs, so importing AVA Core remains cross-platform."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows native filesystem APIs are unavailable")
        win_dll = cast(Any, ctypes).WinDLL
        self.kernel32 = win_dll("kernel32", use_last_error=True)
        self.ntdll = win_dll("ntdll")
        self._nt_create_file = self.ntdll.NtCreateFile
        self._nt_query_directory_file = self.ntdll.NtQueryDirectoryFile
        self._read_file = self.kernel32.ReadFile
        self.kernel32.CreateFileW.restype = wintypes.HANDLE
        self.kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.GetFileInformationByHandleEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.kernel32.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        self.kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetDriveTypeW.restype = wintypes.UINT
        self.kernel32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        self.kernel32.GetVolumeInformationW.restype = wintypes.BOOL
        self.kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        self.kernel32.ReadFile.restype = wintypes.BOOL
        self._nt_create_file.restype = ctypes.c_long
        self._nt_create_file.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.ULONG,
            ctypes.POINTER(_ObjectAttributes),
            ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
        ]
        self._nt_query_directory_file.restype = ctypes.c_long
        self._nt_query_directory_file.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(_IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            ctypes.c_int,
            wintypes.BOOLEAN,
            ctypes.POINTER(_UnicodeString),
            wintypes.BOOLEAN,
        ]

    def close(self, handle: int) -> None:
        if handle and not self.kernel32.CloseHandle(wintypes.HANDLE(handle)):
            raise _winerror()

    def info(self, handle: int, info_class: int, info_type: type[ctypes.Structure]) -> ctypes.Structure:
        value = info_type()
        if not self.kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(handle), info_class, ctypes.byref(value), ctypes.sizeof(value)
        ):
            raise _winerror()
        return value

    def final_path(self, handle: int) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.kernel32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise _winerror()
        return buffer.value

    def open_child(self, parent: int, component: str, *, directory: bool) -> int:
        name_buffer = ctypes.create_unicode_buffer(component)
        encoded_length = len(component.encode("utf-16-le"))
        name = _UnicodeString(
            encoded_length,
            encoded_length,
            ctypes.cast(name_buffer, wintypes.LPWSTR),
        )
        attrs = _ObjectAttributes(
            ctypes.sizeof(_ObjectAttributes),
            wintypes.HANDLE(parent),
            ctypes.pointer(name),
            _OBJ_CASE_INSENSITIVE | _OBJ_DONT_REPARSE,
            None,
            None,
        )
        status_block = _IoStatusBlock()
        handle = wintypes.HANDLE()
        access = _FILE_READ_ATTRIBUTES | _SYNCHRONIZE | (_FILE_LIST_DIRECTORY if directory else _GENERIC_READ)
        options = _FILE_OPEN_REPARSE_POINT | _FILE_SYNCHRONOUS_IO_NONALERT
        options |= _FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE
        status = self._nt_create_file(
            ctypes.byref(handle),
            access,
            ctypes.byref(attrs),
            ctypes.byref(status_block),
            None,
            0,
            _SHARE_READ_WRITE,
            _FILE_OPEN,
            options,
            None,
            0,
        )
        if status < 0:
            raise _ntstatus_error(status)
        return int(handle.value or 0)


class WindowsWorkspaceFilesystemAdapter:
    """Windows implementation of AVA's read-only Workspace filesystem port."""

    async def execute(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        if not isinstance(invocation, AuthorizedToolInvocation):
            raise TypeError("service authorization required")
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        return self._execute_sync(invocation)

    def _execute_sync(self, invocation: AuthorizedToolInvocation) -> ToolResult:
        try:
            if os.name != "nt":
                return _error(
                    invocation,
                    "secure_filesystem_unavailable",
                    "Secure Windows Workspace access is unavailable.",
                )
            workspace = invocation.workspace
            if (
                invocation.workspace_id != workspace.workspace_id
                or workspace.local_path is None
                or not workspace.local_path.is_absolute()
                or not workspace.permissions.read
                or workspace.configuration_revision < 0
                or (
                    workspace.configured_capabilities is not None
                    and "file_read" not in workspace.configured_capabilities
                )
            ):
                return _error(invocation, "workspace_unavailable", "The authorized Workspace is unavailable.")
            api = _WindowsApi()
            root = _open_root(api, workspace.local_path)
            try:
                relative = _relative_path(
                    invocation.request.arguments.get("path"),
                    allow_root=invocation.request.tool_id == "workspace.list_files",
                )
                if relative is None:
                    return _error(invocation, "invalid_path", "The Workspace path is invalid.")
                if invocation.request.tool_id == "workspace.list_files":
                    return _list_files(api, invocation, root, relative)
                if invocation.request.tool_id == "workspace.read_file":
                    return _read_file(api, invocation, root, relative)
                if invocation.request.tool_id == "workspace.file_info":
                    return _file_info(api, invocation, root, relative)
                return _error(invocation, "unknown_tool", "The Workspace tool is unavailable.")
            finally:
                api.close(root)
        except FileNotFoundError:
            return _error(invocation, "not_found", "The requested Workspace entry was not found.")
        except PermissionError:
            return _error(invocation, "permission_denied", "Access to the Workspace entry was denied.")
        except (ValueError, UnicodeError):
            return _error(invocation, "invalid_path", "The Workspace path is invalid.")
        except OSError as exc:
            native_error = getattr(exc, "winerror", None) or exc.errno
            if native_error in {2, 3}:
                return _error(invocation, "not_found", "The requested Workspace entry was not found.")
            if native_error in {5, 32, 33}:
                return _error(invocation, "security_validation_failed", "The Workspace entry failed security checks.")
            if native_error in {50, 120, 1}:
                return _error(invocation, "secure_filesystem_unavailable", "Secure Workspace access is unavailable.")
            return _error(invocation, "workspace_access_failed", "The Workspace entry could not be accessed.")
        except Exception:
            if os.environ.get("AVA_PHASE_6_11_WINDOWS_DIAGNOSTICS") == "1":
                _LOGGER.exception("[DEBUG-AVA611-WINDOWS] Native Workspace operation failed")
            return _error(invocation, "tool_execution_failed", "The Workspace tool could not complete.")


def _open_root(api: _WindowsApi, root: Path) -> int:
    root_text = str(root)
    if not re.fullmatch(r"[A-Za-z]:\\(?:[^<>:\"|?*]+(?:\\[^<>:\"|?*]+)*)?", root_text) or ".." in root.parts:
        raise OSError("Workspace root must be an absolute local drive path")
    if any(
        component.endswith((" ", "."))
        or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", component, re.IGNORECASE)
        for component in root.parts[1:]
    ):
        raise OSError("Workspace root contains a non-canonical Windows component")
    drive_root = root_text[:3]
    if api.kernel32.GetDriveTypeW(drive_root) != _DRIVE_FIXED:
        raise OSError("Workspace volume is not a fixed local drive")
    volume_name = ctypes.create_unicode_buffer(64)
    serial = wintypes.DWORD()
    max_component = wintypes.DWORD()
    flags = wintypes.DWORD()
    fs_name = ctypes.create_unicode_buffer(64)
    if not api.kernel32.GetVolumeInformationW(
        drive_root,
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(flags),
        fs_name,
        len(fs_name),
    ):
        raise _winerror()
    if fs_name.value.upper() != _NTFS:
        raise OSError("Workspace volume is not NTFS")
    root_handle = _open_root_components(api, root)
    try:
        attrs = api.info(root_handle, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
        if attrs.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT or not attrs.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("Workspace root is a reparse point or not a directory")
        final = api.final_path(root_handle)
        expected_prefix = "\\\\?\\" + drive_root
        if not final.casefold().startswith(expected_prefix.casefold()):
            raise OSError("Workspace root resolved outside a local drive")
        current = _open_root_components(api, root)
        try:
            first_id = api.info(root_handle, _FILE_ID_INFO, _FileIdInfo)
            current_id = api.info(int(current), _FILE_ID_INFO, _FileIdInfo)
            if (first_id.VolumeSerialNumber, bytes(first_id.FileId)) != (
                current_id.VolumeSerialNumber,
                bytes(current_id.FileId),
            ):
                raise OSError("Workspace root identity changed")
        finally:
            api.close(current)
        return root_handle
    except BaseException:
        api.close(root_handle)
        raise


def _open_root_components(api: _WindowsApi, root: Path) -> int:
    drive_root = str(root)[:3]
    handle = api.kernel32.CreateFileW(
        drive_root,
        _FILE_READ_ATTRIBUTES | _SYNCHRONIZE | _FILE_LIST_DIRECTORY,
        _SHARE_READ_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise _winerror()
    current = int(handle)
    try:
        attrs = api.info(current, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
        if attrs.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT or not attrs.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError("Workspace volume root is unsafe")
        for component in root.parts[1:]:
            child = api.open_child(current, component, directory=True)
            try:
                attrs = api.info(child, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
                if attrs.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                    raise OSError("Workspace ancestor is a reparse point")
            except BaseException:
                api.close(child)
                raise
            parent = current
            current = child
            api.close(parent)
        return current
    except BaseException:
        api.close(current)
        raise


def _relative_path(value: Any, *, allow_root: bool) -> tuple[str, ...] | None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value or ":" in value:
        return None
    if value == ".":
        return () if allow_root else None
    if value.startswith("/") or value.startswith("//"):
        return None
    try:
        value.encode("utf-16-le", errors="strict")
    except UnicodeEncodeError:
        return None
    parts = tuple(value.split("/"))
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((" ", "."))
        or any(ord(char) < 32 or char in '<>"|?*' for char in part)
        or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.IGNORECASE)
        for part in parts
    ):
        return None
    return parts


def _open_relative(api: _WindowsApi, root: int, parts: tuple[str, ...], *, directory: bool = False) -> int:
    if not parts:
        return root
    current = root
    owned: list[int] = []
    try:
        for index, component in enumerate(parts):
            is_directory = index < len(parts) - 1 or directory
            child = api.open_child(current, component, directory=is_directory)
            owned.append(child)
            info = api.info(child, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
            if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("reparse point rejected")
            standard = api.info(child, _FILE_STANDARD_INFO, _FileStandardInfo)
            if standard.DeletePending or bool(standard.Directory) != is_directory:
                raise OSError("entry type or delete state rejected")
            current = child
        result = owned.pop()
        return result
    finally:
        for handle in reversed(owned):
            api.close(handle)


def _list_files(
    api: _WindowsApi,
    invocation: AuthorizedToolInvocation,
    root: int,
    parts: tuple[str, ...],
) -> ToolResult:
    args = invocation.request.arguments
    limit = args.get("limit", 50)
    cursor = args.get("cursor", "0")
    if type(limit) is not int or not 1 <= limit <= _MAX_DIRECTORY_ENTRIES:
        return _error(invocation, "invalid_arguments", "The requested page size is invalid.")
    if not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdigit() or len(cursor) > 12:
        return _error(invocation, "invalid_arguments", "The directory cursor is invalid.")
    offset = int(cursor)
    directory = _open_relative(api, root, parts, directory=True) if parts else root
    owned = bool(parts)
    try:
        names: list[tuple[str, int, int, int]] = []
        restart = True
        while True:
            buffer = ctypes.create_string_buffer(64 * 1024)
            iosb = _IoStatusBlock()
            status = api._nt_query_directory_file(
                wintypes.HANDLE(directory),
                None,
                None,
                None,
                ctypes.byref(iosb),
                buffer,
                len(buffer),
                _FILE_ID_BOTH_DIR_INFO,
                False,
                None,
                restart,
            )
            restart = False
            if status & 0xFFFFFFFF in {_STATUS_NO_MORE_FILES, _STATUS_NO_SUCH_FILE}:
                break
            if status < 0:
                raise _ntstatus_error(status)
            base = ctypes.addressof(buffer)
            pos = 0
            while True:
                entry = _FileIdBothDirectoryInfo.from_address(base + pos)
                length = int(entry.FileNameLength)
                if length % 2 or length > len(buffer) - pos - 104:
                    raise OSError("invalid directory response")
                name = ctypes.wstring_at(base + pos + 104, length // 2)
                if name not in {".", ".."}:
                    names.append((name, int(entry.FileAttributes), int(entry.EndOfFile), int(entry.LastWriteTime)))
                    if len(names) > _MAX_DIRECTORY_SCAN:
                        return _error(
                            invocation,
                            "directory_too_large",
                            "The directory exceeds the safe listing limit.",
                        )
                if not entry.NextEntryOffset:
                    break
                pos += int(entry.NextEntryOffset)
        names.sort(key=lambda item: (item[0].casefold(), item[0]))
        page = names[offset : offset + limit]
        entries: list[dict[str, Any]] = []
        for name, _, _, _ in page:
            if _relative_path(name, allow_root=False) is None:
                continue
            try:
                child = api.open_child(directory, name, directory=True)
                child_type = "directory"
            except OSError:
                try:
                    child = api.open_child(directory, name, directory=False)
                    child_type = "file"
                except OSError:
                    continue
            try:
                attrs = api.info(child, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
                standard = api.info(child, _FILE_STANDARD_INFO, _FileStandardInfo)
                basic = api.info(child, _FILE_BASIC_INFO, _FileBasicInfo)
                if attrs.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT or standard.DeletePending:
                    continue
                if child_type == "file" and (standard.Directory or standard.NumberOfLinks != 1):
                    continue
                if child_type == "directory" and not standard.Directory:
                    continue
                item: dict[str, Any] = {
                    "name": name,
                    "type": child_type,
                    "modified_at": _filetime_iso(basic.LastWriteTime),
                }
                if child_type == "file":
                    item["size_bytes"] = max(0, int(standard.EndOfFile))
                entries.append(item)
            finally:
                api.close(child)
        result: dict[str, Any] = {"entries": entries}
        next_offset = offset + len(page)
        if next_offset < len(names):
            result["next_cursor"] = str(next_offset)
        return _success(invocation, result)
    finally:
        if owned:
            api.close(directory)


def _read_file(api: _WindowsApi, invocation: AuthorizedToolInvocation, root: int, parts: tuple[str, ...]) -> ToolResult:
    max_bytes = invocation.request.arguments.get("max_bytes", _MAX_READ_BYTES)
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_READ_BYTES:
        return _error(invocation, "invalid_arguments", "The requested read limit is invalid.")
    handle = _open_relative(api, root, parts)
    try:
        standard = api.info(handle, _FILE_STANDARD_INFO, _FileStandardInfo)
        basic = api.info(handle, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
        if (
            standard.NumberOfLinks != 1
            or standard.DeletePending
            or basic.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return _error(invocation, "unsupported_file_type", "Only unlinked regular files can be read.")
        capacity = max_bytes + 1
        raw_buffer = bytearray()
        while len(raw_buffer) < capacity:
            request_size = min(64 * 1024, capacity - len(raw_buffer))
            buffer = ctypes.create_string_buffer(request_size)
            read = wintypes.DWORD()
            if not api._read_file(wintypes.HANDLE(handle), buffer, request_size, ctypes.byref(read), None):
                raise _winerror()
            if not read.value:
                break
            raw_buffer.extend(buffer.raw[: read.value])
        raw = bytes(raw_buffer)
        truncated = len(raw) > max_bytes or standard.EndOfFile > max_bytes
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
                "size_bytes": min(standard.EndOfFile, _MAX_READ_BYTES + 1),
            },
        )
    finally:
        api.close(handle)


def _file_info(api: _WindowsApi, invocation: AuthorizedToolInvocation, root: int, parts: tuple[str, ...]) -> ToolResult:
    handle = _open_relative(api, root, parts)
    try:
        standard = api.info(handle, _FILE_STANDARD_INFO, _FileStandardInfo)
        attrs = api.info(handle, _FILE_ATTRIBUTE_TAG_INFO, _FileAttributeTagInfo)
        basic = api.info(handle, _FILE_BASIC_INFO, _FileBasicInfo)
        if (
            standard.NumberOfLinks != 1
            or standard.DeletePending
            or attrs.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return _error(invocation, "unsupported_file_type", "Only unlinked regular files are supported.")
        return _success(
            invocation,
            {
                "type": "file",
                "size_bytes": min(standard.EndOfFile, _MAX_READ_BYTES + 1),
                "modified_at": _filetime_iso(basic.LastWriteTime),
            },
        )
    finally:
        api.close(handle)


def _filetime_iso(value: int) -> str:
    return datetime.fromtimestamp((value - 116444736000000000) / 10_000_000, tz=UTC).isoformat()


def _winerror() -> OSError:
    code = cast(Any, ctypes).get_last_error()
    return OSError(code, "Windows filesystem operation failed", None, code)


def _ntstatus_error(status: int) -> OSError:
    dos_error = {
        0xC000000F: 2,  # STATUS_NO_SUCH_FILE
        0xC0000034: 2,  # STATUS_OBJECT_NAME_NOT_FOUND
        0xC000003A: 3,  # STATUS_OBJECT_PATH_NOT_FOUND
        0xC0000022: 5,  # STATUS_ACCESS_DENIED
        0xC0000033: 123,  # STATUS_OBJECT_NAME_INVALID
        0xC000003B: 161,  # STATUS_OBJECT_PATH_SYNTAX_BAD
        0xC0000035: 183,  # STATUS_OBJECT_NAME_COLLISION
        0xC0000054: 32,  # STATUS_FILE_LOCK_CONFLICT
        0xC0000055: 33,  # STATUS_LOCK_NOT_GRANTED
        0xC00000BB: 50,  # STATUS_NOT_SUPPORTED
    }.get(status & 0xFFFFFFFF, 1)
    return OSError(dos_error, "Windows native filesystem operation failed", None, dos_error)


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
