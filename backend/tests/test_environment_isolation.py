"""Regression tests for backend test-environment isolation.

The suite used to inherit the developer's repository-root ``.env``, because
importing the OpenHands SDK transitively imports ``litellm``, whose module body
calls ``load_dotenv()`` and writes every key from that file into the global
process environment. Since ``Settings`` reads ``os.environ`` on every
construction, the same test answered differently depending on which module had
been imported first, and the default-memory tests failed only in a full run.

These tests pin the boundary down from both sides:

* the test profile is deterministic and cannot be changed by any ``.env``;
* production startup still reads the ``.env`` it always did.

The subprocess cases are deliberate. In-process they would be tautological —
the contamination happens during collection, long before any test body runs —
so the only honest way to test it is a fresh interpreter whose current directory
contains a hostile ``.env``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import TEST_ENVIRONMENT, reset_settings_cache

from ava.configuration.settings import Settings, get_settings

#: The module that first pulls the OpenHands SDK (and therefore ``litellm``)
#: into the process. Importing it alone was enough to load ``.env``.
OPENHANDS_SDK_CARRIER = "ava.runtimes.adapters.openhands.controlled_terminal"

#: A developer ``.env`` that contradicts every backend test default.
HOSTILE_ENV = """\
AVA_PERSISTENCE=relational
AVA_ATTACHMENT_STORAGE=local
AVA_ATTACHMENT_STORAGE_ROOT=/tmp/ava-hostile-attachments
AVA_PERSISTENCE_DATABASE_URL=ava-hostile.sqlite3
AVA_MODEL_PROVIDER=corporate
"""


def _ava_environment() -> dict[str, str]:
    """Every AVA_* variable currently visible to the process."""
    return {name: value for name, value in os.environ.items() if name.startswith("AVA_")}


def _run_in_isolated_interpreter(
    directory: Path, program: str, *, inherit_ava_environment: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run ``program`` in a fresh interpreter whose CWD is ``directory``.

    A temporary working directory is what makes ``load_dotenv()`` find the
    hostile ``.env`` under test: python-dotenv searches upward from the working
    directory, and a temp directory has no ``.env`` in any parent.

    The environment is inherited so the child sees exactly what the test process
    sees plus the file under test — which is what a developer's machine looks
    like. ``inherit_ava_environment=False`` additionally strips every ``AVA_*``
    variable, producing the bare environment of a shell that has not yet loaded
    ``.env``; that is the state production code must still be able to configure
    from the file.
    """
    environment = dict(os.environ)
    if not inherit_ava_environment:
        for name in [name for name in environment if name.startswith("AVA_")]:
            del environment[name]
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=directory,
        env={**environment, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=180,
    )


def _child_reports_settings() -> str:
    """Program body: import the SDK carrier, then report the resulting settings."""
    return (
        "import json, os\n"
        f"import {OPENHANDS_SDK_CARRIER}\n"
        "from ava.configuration.settings import Settings\n"
        "settings = Settings()\n"
        "print(json.dumps({\n"
        "    'persistence': settings.persistence_provider,\n"
        "    'attachment': settings.attachment_storage,\n"
        "    'model_provider': settings.model_provider,\n"
        "}))\n"
    )


# ============================================================
# BEGIN: Test Profile Determinism
# ============================================================


def test_the_suite_defines_its_own_configuration() -> None:
    """Every AVA_* variable the settings layer reads is stated by the harness.

    The suite does not "happen to" have a clean environment; the conftest
    boundary assigns all of them. A new setting added to ``Settings`` without a
    matching entry would show up here as a failure rather than as a test that
    quietly depends on a developer's shell.
    """
    assert _ava_environment() == TEST_ENVIRONMENT


def test_ordinary_settings_use_the_in_memory_profile() -> None:
    """A default Settings is in-memory for both persistence and attachment content."""
    settings = Settings()
    assert settings.persistence_provider == "memory"
    assert settings.attachment_storage == "memory"


def test_importing_the_openhands_sdk_cannot_change_the_configuration() -> None:
    """The original contamination mechanism is inert once the harness has run.

    ``litellm`` calls ``load_dotenv()`` at import, and ``load_dotenv`` defaults
    to ``override=False``: it fills in keys that are absent and leaves existing
    ones alone. Because conftest has already defined every AVA_* variable, the
    SDK's import is a no-op for anything AVA reads.
    """
    before = _ava_environment()
    __import__(OPENHANDS_SDK_CARRIER)
    assert _ava_environment() == before


def test_the_suite_never_writes_persistence_state_into_the_repository() -> None:
    """Filesystem defaults point outside the working tree.

    A test that opts into relational persistence or local attachment storage
    without naming a path writes to a temporary directory rather than creating
    ``backend/ava.sqlite3`` or ``backend/.ava/`` as a side effect of a run.
    """
    backend = Path(__file__).resolve().parent.parent
    for name in ("AVA_PERSISTENCE_DATABASE_URL", "AVA_ATTACHMENT_STORAGE_ROOT"):
        value = TEST_ENVIRONMENT[name]
        assert not value.startswith(f"{backend}{os.sep}"), f"{name} points into the repository"
        assert Path(value).is_absolute()


# ============================================================
# END: Test Profile Determinism
# ============================================================


# ============================================================
# BEGIN: Repository .env Independence
# ============================================================


def test_a_repository_env_cannot_reach_the_backend_test_configuration(tmp_path: Path) -> None:
    """A developer ``.env`` loses to the test boundary, even after the SDK import.

    This is the regression test for the original bug. A fresh interpreter starts
    in a directory whose ``.env`` demands relational persistence and local
    attachment storage, imports the harness exactly as pytest does, then imports
    the OpenHands SDK exactly as a full test collection does. The result must
    still be the memory profile.
    """
    (tmp_path / ".env").write_text(HOSTILE_ENV, encoding="utf-8")
    result = _run_in_isolated_interpreter(
        tmp_path,
        "import conftest\n" + _child_reports_settings(),
    )
    assert result.returncode == 0, result.stderr
    reported = json.loads(result.stdout.strip().splitlines()[-1])
    assert reported == {"persistence": "memory", "attachment": "memory", "model_provider": "local"}


def test_production_startup_still_honours_the_repository_env(tmp_path: Path) -> None:
    """The same ``.env`` still configures AVA when the test harness is not involved.

    The counterpart to the test above, and the reason the fix belongs at the test
    boundary: nothing in ``src/ava`` changed. A process that starts from a bare
    environment and imports the OpenHands SDK still picks the file up, exactly as
    it did before the harness existed, and ``scripts/dev_backend.sh`` still
    exports it into the server process. Stripping the inherited AVA_* variables
    reproduces the shell that has not yet loaded ``.env``.
    """
    (tmp_path / ".env").write_text(HOSTILE_ENV, encoding="utf-8")
    result = _run_in_isolated_interpreter(
        tmp_path, _child_reports_settings(), inherit_ava_environment=False
    )
    assert result.returncode == 0, result.stderr
    reported = json.loads(result.stdout.strip().splitlines()[-1])
    assert reported == {
        "persistence": "relational",
        "attachment": "local",
        "model_provider": "corporate",
    }


# ============================================================
# END: Repository .env Independence
# ============================================================


# ============================================================
# BEGIN: Cache Isolation and Ordering
# ============================================================


def test_a_cached_settings_instance_cannot_outlive_its_test() -> None:
    """The settings singleton is rebuilt rather than inherited.

    ``get_settings()`` memoizes one instance. Without the autouse reset, a test
    that resolved settings under its own configuration would hand that instance
    to the next test in the session. The reset is exercised directly here, since
    relying on neighbouring tests to prove a leak would make this test
    order-dependent — the very thing it guards against.
    """
    assert get_settings().persistence_provider == "memory"
    from ava.configuration import settings as settings_module

    settings_module._settings = Settings(persistence_provider="relational")
    reset_settings_cache()
    assert get_settings().persistence_provider == "memory"


def test_configuration_does_not_depend_on_what_was_resolved_first() -> None:
    """Memory -> relational -> memory yields memory, and never a stale value.

    Both directions matter: a relational reading must not permanently switch the
    process to relational, and a memory reading must not be able to hide a
    relational one a later test asked for.
    """
    assert get_settings().persistence_provider == "memory"

    reset_settings_cache()
    os.environ["AVA_PERSISTENCE"] = "relational"
    try:
        assert get_settings().persistence_provider == "relational"
    finally:
        os.environ["AVA_PERSISTENCE"] = TEST_ENVIRONMENT["AVA_PERSISTENCE"]
    reset_settings_cache()

    assert get_settings().persistence_provider == "memory"


def test_explicit_settings_construction_bypasses_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Injection stays the primary way to choose a mode in a test.

    The established mechanism is an explicit ``Settings(...)`` call, and the
    isolation boundary does not intercept it: the environment is only consulted
    for values the caller did not supply.
    """
    monkeypatch.setenv("AVA_PERSISTENCE", "relational")
    assert Settings(persistence_provider="memory").persistence_provider == "memory"
    assert Settings(
        persistence_provider="relational",
        persistence_database_url="explicit.sqlite3",
    ).persistence_provider == "relational"


# ============================================================
# END: Cache Isolation and Ordering
# ============================================================


# ============================================================
# BEGIN: Explicit Mode Opt-In Still Works
# ============================================================


def test_a_test_can_still_opt_into_relational_persistence(tmp_path: Path) -> None:
    """A relational test gets relational persistence, and it is durable.

    Proves the boundary is a default rather than a prohibition: this is the
    configuration the persistent tests across the suite depend on.
    """
    monkey = pytest.MonkeyPatch()
    monkey.setenv("AVA_PERSISTENCE", "relational")
    try:
        reset_settings_cache()
        from ava.infrastructure.composition import create_application_persistence
        from ava.infrastructure.persistence.repositories import RelationalRunRepository

        persistence = create_application_persistence(
            Settings(
                persistence_provider="relational",
                persistence_database_url=str(tmp_path / "opt-in.sqlite3"),
            )
        )
        try:
            assert isinstance(persistence.run_repository, RelationalRunRepository)
            assert persistence.database is not None
        finally:
            persistence.dispose()
    finally:
        monkey.undo()
        reset_settings_cache()


def test_a_test_can_still_opt_into_local_attachment_storage(tmp_path: Path) -> None:
    """A local-storage test gets a filesystem-backed content store."""
    from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
    from ava.infrastructure.composition import create_attachment_content_store

    store = create_attachment_content_store(
        Settings(attachment_storage="local", attachment_storage_root=str(tmp_path / "content"))
    )
    assert isinstance(store, LocalAttachmentContentStore)
    assert (tmp_path / "content").is_dir()


# ============================================================
# END: Explicit Mode Opt-In Still Works
# ============================================================
