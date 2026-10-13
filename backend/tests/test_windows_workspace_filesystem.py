"""Native Windows filesystem security tests, run on the Windows CI host."""

import os
import subprocess
from pathlib import Path

import pytest
from test_workspace_filesystem_contract import _invoke, _service

import ava.infrastructure.workspace_filesystem.windows as windows_adapter
from ava.infrastructure.workspace_filesystem.windows import _open_relative, _WindowsApi

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires native Windows filesystem APIs")


def _make_junction(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        pytest.fail(f"Windows runner cannot create the mandatory NTFS junction fixture: {completed.stderr}")


@pytest.mark.asyncio
async def test_windows_native_paths_reparse_points_ads_and_case_insensitivity(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (tmp_path / "safe.txt").write_text("inside", encoding="utf-8")
    _make_junction(tmp_path / "junction", outside)
    service = _service(tmp_path)

    for invalid in (
        "C:relative.txt",
        "C:\\absolute.txt",
        "\\\\server\\share\\file.txt",
        "\\\\?\\C:\\device.txt",
        "safe.txt:stream",
    ):
        result = await _invoke(service, "workspace.read_file", invalid)
        assert result.result is None or result.result.error is not None
    escaped = await _invoke(service, "workspace.read_file", "junction/secret.txt")
    assert escaped.result is not None and escaped.result.error is not None
    differently_cased = await _invoke(service, "workspace.read_file", "SAFE.TXT")
    assert differently_cased.result is not None and differently_cased.result.output is not None
    assert differently_cased.result.output["content"] == "inside"


@pytest.mark.asyncio
async def test_windows_native_directory_symlink_and_file_replacement_protection(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    (tmp_path / "safe.txt").write_text("inside", encoding="utf-8")
    (tmp_path / "pinned-dir").mkdir()
    (tmp_path / "pinned-dir" / "child.txt").write_text("inside", encoding="utf-8")
    try:
        (tmp_path / "symlink-dir").symlink_to(outside, target_is_directory=True)
        (tmp_path / "symlink-file").symlink_to(outside / "secret.txt")
    except OSError as exc:
        pytest.fail(f"Windows runner lacks required symbolic-link capability: {exc}")
    service = _service(tmp_path)
    for path in ("symlink-dir/secret.txt", "symlink-file"):
        outcome = await _invoke(service, "workspace.read_file", path)
        assert outcome.result is not None and outcome.result.error is not None

    api = _WindowsApi()
    root = _open_root_for_test(api, tmp_path)
    try:
        with pytest.raises(OSError):
            tmp_path.rename(tmp_path.with_name(f"{tmp_path.name}-replacement"))
        file_handle = _open_relative(api, root, ("safe.txt",))
        try:
            replacement = tmp_path / "replacement.txt"
            replacement.write_text("replacement", encoding="utf-8")
            with pytest.raises(OSError):
                replacement.replace(tmp_path / "safe.txt")
        finally:
            api.close(file_handle)
        directory_handle = _open_relative(api, root, ("pinned-dir",), directory=True)
        try:
            with pytest.raises(OSError):
                (tmp_path / "pinned-dir").rename(tmp_path / "renamed-dir")
        finally:
            api.close(directory_handle)
    finally:
        api.close(root)


def _open_root_for_test(api: _WindowsApi, root: Path) -> int:
    from ava.infrastructure.workspace_filesystem.windows import _open_root

    return _open_root(api, root)


@pytest.mark.asyncio
async def test_windows_native_handle_identity_and_unavailable_api_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "safe.txt").write_text("inside", encoding="utf-8")
    outcome = await _invoke(_service(tmp_path), "workspace.file_info", "safe.txt")
    assert outcome.result is not None and outcome.result.output is not None
    assert outcome.result.output["type"] == "file"

    class MissingNativeApi:
        def __init__(self) -> None:
            raise OSError(50, "unsupported filesystem operation")

    monkeypatch.setattr(windows_adapter, "_WindowsApi", MissingNativeApi)
    unavailable = await _invoke(_service(tmp_path), "workspace.file_info", "safe.txt")
    assert unavailable.result is not None and unavailable.result.error is not None
    assert unavailable.result.error.error_code == "secure_filesystem_unavailable"
