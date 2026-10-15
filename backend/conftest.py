"""The backend test suite's environment boundary.

Why this file exists
--------------------

The backend reads its configuration from ``os.environ`` and nothing else:
``Settings`` is a plain dataclass whose fields use ``default_factory`` lambdas
that call ``os.environ`` at *instantiation* time. It does not read a ``.env``
file, and it caches nothing beyond one module-level singleton.

That was safe until a transitive dependency decided otherwise. Importing the
OpenHands SDK pulls in ``litellm``, and ``litellm/__init__.py`` calls
``load_dotenv()`` at module import time. ``load_dotenv()`` defaults to
``override=False``, so it writes every key from the nearest ``.env`` file into
the *global* process environment. The backend's own
``runtimes/adapters/openhands/*`` modules import that SDK at module scope, so
merely *collecting* a test module that touches the OpenHands adapter loads the
developer's repository-root ``.env`` into the pytest process.

The consequence was that the same test gave different answers depending on what
had been imported first. A developer ``.env`` containing
``AVA_PERSISTENCE=relational`` and ``AVA_ATTACHMENT_STORAGE=local`` made
every later ``Settings()`` report relational/local, so the suite's
default-memory assertions failed — while the very same tests passed when run on
their own, because nothing had imported the OpenHands SDK yet. The failure count
moved around with collection order, which is the signature of exactly this kind
of ambient contamination.

The fix
-------

The test suite states its own configuration instead of inheriting it. Every
``AVA_*`` variable the settings layer reads is defined here, at conftest import
time, to the value AVA documents as its default. Two properties make this
sufficient and durable:

* conftest is imported before pytest imports any test module, so the values are
  in place before the OpenHands SDK — and therefore ``load_dotenv()`` — is ever
  imported;
* ``load_dotenv(override=False)`` never overwrites a variable that is already
  set, so the SDK's import-time ``.env`` load becomes a no-op for every key AVA
  reads. It is still free to set unrelated keys, which no AVA test depends on.

This is a test-boundary fix, not a production one. Development startup is
unaffected: ``scripts/dev_backend.sh`` still loads the repository-root ``.env``
and exports it into the server process, exactly as before. Nothing in
``src/ava`` changed, and no production default was altered.

Tests that deliberately want another mode are unaffected: ``monkeypatch``
overrides these values for the duration of a test and restores them afterwards,
and explicitly constructed ``Settings(...)`` objects bypass the environment
entirely. Both mechanisms are the established ones here and both are exercised by
``tests/test_environment_isolation.py``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

#: The configuration the backend test suite runs under, stated explicitly.
#:
#: Every value is the default AVA documents for that setting, so an ordinary
#: test sees the same thing a freshly started, unconfigured backend sees. The
#: two selection keys are the ones the suite's assertions depend on: the backend
#: test profile is in-memory persistence and in-memory attachment content, so no
#: test can be made to pass or fail by a developer's local storage choices.
#:
#: The two filesystem keys are redirected out of the repository. A test that
#: opts into relational persistence or local attachment storage without naming a
#: path then writes to a temporary directory instead of creating
#: ``backend/ava.sqlite3`` or ``backend/.ava/`` as a side effect of running the
#: suite.
TEST_ENVIRONMENT: dict[str, str] = {
    "AVA_APPLICATION": "AVA",
    "AVA_ENVIRONMENT": "development",
    "AVA_AGENT_PROVIDER": "mock",
    "AVA_AGENT_RUNTIME": "native",
    "AVA_MODEL_PROVIDER": "local",
    "AVA_MODEL_NAME": "local-model",
    "AVA_MODEL_ID": "",
    "AVA_MODEL_HOSTING_MODE": "local",
    "AVA_LOCAL_MODEL_BASE_URL": "http://localhost:11434/v1",
    "AVA_HOST": "127.0.0.1",
    "AVA_PORT": "8000",
    "AVA_DEBUG": "true",
    "AVA_LOG_LEVEL": "info",
    "AVA_PERSISTENCE": "memory",
    "AVA_PERSISTENCE_DATABASE_URL": os.path.join(
        tempfile.gettempdir(), "ava-backend-tests", "ava-test.sqlite3"
    ),
    "AVA_ATTACHMENT_STORAGE": "memory",
    "AVA_ATTACHMENT_STORAGE_ROOT": os.path.join(
        tempfile.gettempdir(), "ava-backend-tests", "attachments"
    ),
}


def apply_test_environment() -> None:
    """Define the test configuration in the process environment.

    Assignment is unconditional and happens once, at conftest import. Using
    ``setdefault`` would be wrong: it would leave a developer's exported
    ``AVA_PERSISTENCE`` in place, which is precisely the contamination being
    removed. Overwriting here is safe because this is the test process, and
    because anything a test wants to change it changes afterwards through
    ``monkeypatch``.
    """
    for name, value in TEST_ENVIRONMENT.items():
        os.environ[name] = value


def reset_settings_cache() -> None:
    """Drop the cached ``Settings`` singleton so the next read reflects the environment.

    ``ava.configuration.settings`` memoizes one ``Settings`` instance in a
    module-level global, which is what ``get_settings()`` returns. A cached
    instance built under one configuration would otherwise outlive the test that
    created it and be handed to the next one. Clearing the global is the
    established reset used by the existing settings and provider-composition
    tests; there is no separate public reset API to call.
    """
    from ava.configuration import settings as settings_module

    settings_module._settings = None


apply_test_environment()
from ava.api import app as _ava_app_module  # noqa: E402


class _SuitePrincipalResolver:
    """Explicit test-only authentication provider; never imported by AVA runtime code."""

    def __init__(self) -> None:
        from ava.contracts.security_identity import (
            PrincipalActorType,
            PrincipalResolution,
            PrincipalResolutionStatus,
            VerifiedPrincipal,
        )

        now = datetime.now(UTC)
        self.principal = VerifiedPrincipal(
            identity_provider="https://pytest.invalid/ava-suite",
            subject="suite-principal",
            tenant_ref="suite-tenant",
            actor_type=PrincipalActorType.HUMAN,
            authentication_context="test_session",
            authentication_context_ref=sha256(b"test-only-session-context").hexdigest(),
            authenticated_at=now,
            valid_until=now + timedelta(days=1),
        )
        self._resolution = PrincipalResolution(
            status=PrincipalResolutionStatus.AUTHENTICATED,
            principal=self.principal,
        )

    def resolve(self, request: object) -> object:
        del request
        return self._resolution


class _SuitePrincipalValidity:
    def __init__(self, resolver: _SuitePrincipalResolver) -> None:
        self._resolver = resolver

    def is_current(self, principal_ref: str, authentication_context_ref: str) -> bool:
        principal = self._resolver.principal
        return (
            principal_ref == principal.principal_ref
            and authentication_context_ref == principal.authentication_context_ref
        )


class _SuiteConversationAccess:
    def can_access(self, principal_ref: str, tenant_ref: str | None, conversation_id: str) -> bool:
        # Existing test conversations are intentionally owned by this isolated
        # single-principal test adapter. Production defaults to deny.
        del principal_ref, tenant_ref, conversation_id
        return True


# API tests must opt into a trusted identity adapter now that Run routes no
# longer permit anonymous traffic. The real factory stays default-deny; this
# wrapper exists only in pytest's process and never changes production behavior.
_suite_resolver = _SuitePrincipalResolver()
# Global CORE prompt mutation tests run as this explicit test-only administrator.
# Security regression tests remove the value to exercise the production default-deny path.
os.environ["AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS"] = _suite_resolver.principal.principal_ref
_production_create_app = _ava_app_module.create_app


def _create_test_app(*args: object, **kwargs: object):
    kwargs.setdefault("http_principal_resolver", _suite_resolver)
    kwargs.setdefault("principal_validity", _SuitePrincipalValidity(_suite_resolver))
    kwargs.setdefault("conversation_access", _SuiteConversationAccess())
    app = _production_create_app(*args, **kwargs)
    app.state.test_principal = _suite_resolver.principal
    return app


_ava_app_module.create_app = _create_test_app


@pytest.fixture(autouse=True)
def _isolated_settings_cache() -> Iterator[None]:
    """Give every test a freshly resolved settings cache.

    Autouse because the leak it prevents is invisible: a test that caches
    settings under its own configuration would otherwise hand that instance to
    an unrelated later test. The previous value is restored on the way out so
    the suite leaves the process as it found it.
    """
    from ava.configuration import settings as settings_module

    previous = settings_module._settings
    settings_module._settings = None
    try:
        yield
    finally:
        settings_module._settings = previous
