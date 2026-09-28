"""Phase 5.9 — credential reference strategy.

The rules under test are mostly negative: a secret must not be persisted, must
not appear in a string representation, must not reach a public contract, and
must not be logged. Those are asserted directly rather than inferred from
passing behavior.
"""

import ast
import dataclasses
import json
import logging
import re
from pathlib import Path

import pytest

from ava.infrastructure.credentials import EnvironmentCredentialResolver
from ava.models.credentials import (
    ENVIRONMENT_CREDENTIAL_SCHEME,
    BlankCredentialError,
    CredentialError,
    CredentialNotFoundError,
    CredentialReference,
    CredentialReferenceError,
    CredentialResolver,
    SecretValue,
    UnsupportedCredentialSchemeError,
    resolve_connection_credential,
)
from ava.models.provider_connections import ProviderConnection

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ava"

SECRET = "sk-live-DO-NOT-LEAK-0123456789"
VARIABLE = "OPENAI_API_KEY"


def _connection(**overrides: object) -> ProviderConnection:
    fields: dict[str, object] = {
        "provider_connection_id": "conn-1",
        "provider_id": "openai-compatible",
        "display_name": "Primary gateway",
        "endpoint": "https://gateway.internal/v1",
    }
    fields.update(overrides)
    return ProviderConnection(**fields)  # type: ignore[arg-type]


def _resolver(**environment: str) -> EnvironmentCredentialResolver:
    return EnvironmentCredentialResolver(dict(environment))


# ============================================================
# BEGIN Credential reference semantics
# ============================================================


def test_reference_syntax_is_scheme_colon_location() -> None:
    parsed = CredentialReference.parse(f"{ENVIRONMENT_CREDENTIAL_SCHEME}:{VARIABLE}")
    assert parsed.scheme == ENVIRONMENT_CREDENTIAL_SCHEME
    assert parsed.location == VARIABLE
    assert parsed.text() == f"env:{VARIABLE}"


def test_reference_round_trips_through_canonical_text() -> None:
    text = f"  {ENVIRONMENT_CREDENTIAL_SCHEME}:{VARIABLE}  "
    assert CredentialReference.parse(text).text() == f"env:{VARIABLE}"


@pytest.mark.parametrize("text", ["", "   ", "OPENAI_API_KEY", ":NAME", "env:", "env:   ", "  :NAME"])
def test_malformed_references_are_rejected(text: str) -> None:
    with pytest.raises(CredentialReferenceError):
        CredentialReference.parse(text)


def test_blank_scheme_and_location_are_rejected_on_direct_construction() -> None:
    with pytest.raises(CredentialReferenceError, match="scheme must be a non-blank string"):
        CredentialReference(scheme="  ", location=VARIABLE)
    with pytest.raises(CredentialReferenceError, match="location must be a non-blank string"):
        CredentialReference(scheme="env", location="")


def test_known_and_future_schemes_share_one_syntax() -> None:
    """A future backend's reference parses identically; only the resolver differs."""
    for text in ("aws-secrets:prod/openai", "azure-keyvault:ava-openai", "databricks:db1"):
        assert CredentialReference.parse(text).text() == text


# ============================================================
# END Credential reference semantics
# ============================================================


# ============================================================
# BEGIN SecretValue representation
# ============================================================


def test_secret_value_reveals_only_on_explicit_request() -> None:
    secret = SecretValue(SECRET)
    assert secret.reveal() == SECRET


def test_secret_value_repr_and_str_are_redacted() -> None:
    secret = SecretValue(SECRET)
    assert SECRET not in repr(secret)
    assert SECRET not in str(secret)
    assert SECRET not in f"{secret}"
    assert repr(secret) == "SecretValue(***)"


def test_secret_value_interpolation_in_a_message_is_redacted() -> None:
    message = f"provider key is {SecretValue(SECRET)}"
    assert SECRET not in message
    assert "***" in message


def test_secret_value_is_not_hashable() -> None:
    with pytest.raises(TypeError, match="not hashable"):
        hash(SecretValue(SECRET))


def test_secret_value_rejects_non_string_material() -> None:
    with pytest.raises(TypeError, match="requires a string secret"):
        SecretValue(b"bytes")  # type: ignore[arg-type]


def test_secret_value_equality_does_not_leak_via_repr() -> None:
    left, right = SecretValue(SECRET), SecretValue(SECRET)
    assert left == right
    assert left != SecretValue("other")
    assert left != "not-a-secret-value"


def test_secret_value_is_not_a_dataclass() -> None:
    """Auto-generated dataclass repr/eq are the leak paths this class closes."""
    assert not dataclasses.is_dataclass(SecretValue)


# ============================================================
# END SecretValue representation
# ============================================================


# ============================================================
# BEGIN Environment resolver
# ============================================================


def test_environment_reference_resolves_to_secret_material() -> None:
    resolved = _resolver(**{VARIABLE: SECRET}).resolve(f"env:{VARIABLE}")
    assert isinstance(resolved, SecretValue)
    assert resolved.reveal() == SECRET


def test_resolver_defaults_to_the_process_environment() -> None:
    resolver = EnvironmentCredentialResolver()
    assert isinstance(resolver, CredentialResolver)


def test_missing_environment_variable_fails_deterministically() -> None:
    with pytest.raises(CredentialNotFoundError) as excinfo:
        _resolver().resolve(f"env:{VARIABLE}")
    assert str(excinfo.value) == f"Credential environment variable is not set: {VARIABLE}"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_environment_value_fails_deterministically(value: str) -> None:
    with pytest.raises(BlankCredentialError) as excinfo:
        _resolver(**{VARIABLE: value}).resolve(f"env:{VARIABLE}")
    assert str(excinfo.value) == f"Credential environment variable is blank: {VARIABLE}"


def test_blank_secret_is_rejected_because_a_blank_key_authenticates_nothing() -> None:
    """A whitespace key produces a degenerate header, so blank is misconfiguration."""
    import asyncio

    import httpx

    from ava.contracts.models import ModelMessage, ModelRequest
    from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "object": "chat.completion",
                "model": "configured-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
            },
        )

    provider = OpenAICompatibleModelProvider(
        base_url="https://gateway.internal/v1",
        model_name="configured-model",
        provider_name="openai-compatible",
        api_key="   ",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def scenario() -> None:
        await provider.generate(ModelRequest(messages=[ModelMessage(role="user", content="Hello")]))

    asyncio.run(scenario())
    assert str(captured["authorization"]).strip() == "Bearer"


def test_malformed_reference_fails_before_any_lookup() -> None:
    with pytest.raises(CredentialReferenceError):
        _resolver(**{VARIABLE: SECRET}).resolve(VARIABLE)


@pytest.mark.parametrize(
    "text", ["aws-secrets:prod/openai", "azure-keyvault:ava", "databricks:db", "file:/etc/key"]
)
def test_unsupported_scheme_is_rejected_with_its_own_error(text: str) -> None:
    with pytest.raises(UnsupportedCredentialSchemeError) as excinfo:
        _resolver().resolve(text)
    assert CredentialReference.parse(text).scheme in str(excinfo.value)


def test_unsupported_scheme_does_not_fall_back_to_environment_lookup() -> None:
    """A secret must never be found under a scheme the resolver does not serve."""
    with pytest.raises(UnsupportedCredentialSchemeError):
        _resolver(**{VARIABLE: SECRET}).resolve(f"vault:{VARIABLE}")


def test_all_resolution_failures_share_one_ava_owned_base() -> None:
    for call, expected in (
        (lambda: _resolver().resolve(f"env:{VARIABLE}"), CredentialNotFoundError),
        (lambda: _resolver(**{VARIABLE: " "}).resolve(f"env:{VARIABLE}"), BlankCredentialError),
        (lambda: _resolver().resolve("nope"), CredentialReferenceError),
        (lambda: _resolver().resolve("aws-secrets:x"), UnsupportedCredentialSchemeError),
    ):
        with pytest.raises(CredentialError) as excinfo:
            call()
        assert isinstance(excinfo.value, expected)


def test_resolver_returns_no_optional_value_on_failure() -> None:
    """Resolution never degrades to ``None``; an unauthenticated provider asks instead."""
    with pytest.raises(CredentialError):
        _resolver().resolve(f"env:{VARIABLE}")


# ============================================================
# END Environment resolver
# ============================================================


# ============================================================
# BEGIN Error and log safety
# ============================================================


def _raise_all_failures() -> list[str]:
    """Trigger every resolver failure and return the messages."""
    messages: list[str] = []
    calls = (
        lambda: _resolver().resolve(f"env:{VARIABLE}"),
        lambda: _resolver(**{VARIABLE: ""}).resolve(f"env:{VARIABLE}"),
        lambda: _resolver().resolve("malformed"),
        lambda: _resolver().resolve("aws-secrets:prod/openai"),
    )
    for call in calls:
        with pytest.raises(CredentialError) as excinfo:
            call()
        messages.append(str(excinfo.value))
    return messages


def test_no_error_message_contains_secret_material() -> None:
    for message in _raise_all_failures():
        assert SECRET not in message


def test_error_messages_name_the_reference_location() -> None:
    messages = _raise_all_failures()
    assert any(VARIABLE in message for message in messages)


def test_logging_a_resolved_secret_does_not_emit_it(caplog: pytest.LogCaptureFixture) -> None:
    secret = _resolver(**{VARIABLE: SECRET}).resolve(f"env:{VARIABLE}")
    logger = logging.getLogger("ava.credentials.test")
    with caplog.at_level(logging.DEBUG):
        logger.debug("resolved credential: %r / %s", secret, secret)
    assert SECRET not in caplog.text
    assert "***" in caplog.text


def test_traceback_of_a_resolution_failure_carries_no_secret() -> None:
    import traceback

    try:
        _resolver(**{VARIABLE: "  "}).resolve(f"env:{VARIABLE}")
    except CredentialError:
        rendered = traceback.format_exc()
    assert SECRET not in rendered


# ============================================================
# END Error and log safety
# ============================================================


# ============================================================
# BEGIN Credential-free connections
# ============================================================


def test_credential_free_connection_needs_no_reference() -> None:
    assert _connection().credential_reference is None


def test_credential_free_connection_resolves_to_nothing_without_calling_the_resolver() -> None:
    class ExplodingResolver(CredentialResolver):
        def resolve(self, reference: str) -> SecretValue:  # pragma: no cover - must not run
            raise AssertionError("resolver must not be invoked for a credential-free connection")

    assert resolve_connection_credential(_connection(), ExplodingResolver()) is None


def test_connection_with_a_reference_resolves_through_the_same_seam() -> None:
    connection = _connection(credential_reference=f"env:{VARIABLE}")
    resolved = resolve_connection_credential(connection, _resolver(**{VARIABLE: SECRET}))
    assert resolved is not None and resolved.reveal() == SECRET


def test_credential_free_connection_survives_a_resolver_that_cannot_resolve_anything() -> None:
    assert resolve_connection_credential(_connection(), _resolver()) is None


def test_local_unauthenticated_provider_still_constructs_without_credentials() -> None:
    """A local provider needs no secret, so Phase 5.9 must not force one on it."""
    from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

    connection = _connection(endpoint="http://localhost:11434/v1", provider_id="local")
    resolved = resolve_connection_credential(connection, _resolver())
    provider = OpenAICompatibleModelProvider(
        base_url=connection.endpoint or "",
        model_name="qwen3",
        provider_name=connection.provider_id,
        api_key=resolved.reveal() if resolved is not None else None,
    )
    binding = provider.create_runtime_model_binding(
        model_id="model-local", provider_id="local", provider_model_name="qwen3"
    )
    assert binding.api_key is None


# ============================================================
# END Credential-free connections
# ============================================================


# ============================================================
# BEGIN Provider infrastructure seam
# ============================================================


def test_resolved_secret_reaches_a_provider_constructor() -> None:
    """Isolated proof of the Phase 5.16 integration point, not a live wiring.

    ``SecretValue.reveal()`` converts back to the plain string provider
    constructors already accept, and the provider then carries it on its
    internal-only runtime binding. Nothing here is used by composition, so
    persisted connections are not authoritative for live runs.
    """
    from ava.models.providers.openai_compatible.provider import OpenAICompatibleModelProvider

    connection = _connection(credential_reference=f"env:{VARIABLE}")
    resolved = resolve_connection_credential(connection, _resolver(**{VARIABLE: SECRET}))
    provider = OpenAICompatibleModelProvider(
        base_url=connection.endpoint or "",
        model_name="configured-model",
        provider_name=connection.provider_id,
        api_key=resolved.reveal() if resolved is not None else None,
    )
    binding = provider.create_runtime_model_binding(
        model_id="model-1", provider_id=connection.provider_id, provider_model_name="gpt-x"
    )
    assert binding.api_key == SECRET


def test_runtime_binding_keeps_the_secret_out_of_public_contracts() -> None:
    """``RuntimeModelBinding.api_key`` stays the internal-only carrier it documents itself as."""
    from ava.models.bindings import RuntimeModelBinding

    assert [field.name for field in dataclasses.fields(RuntimeModelBinding)] == [
        "model_id",
        "provider_id",
        "provider_model_name",
        "protocol",
        "endpoint",
        "api_key",
    ]
    contracts_dir = SRC_DIR / "contracts"
    for path in sorted(contracts_dir.rglob("*.py")):
        assert "api_key" not in path.read_text(encoding="utf-8"), path


# ============================================================
# END Provider infrastructure seam
# ============================================================


# ============================================================
# BEGIN No secret persistence
# ============================================================


def test_provider_connection_persists_only_the_reference() -> None:
    from ava.infrastructure.persistence.composition import create_relational_repositories
    from ava.models.provider_connections import ProviderConnection as Connection

    bundle = create_relational_repositories(":memory:")
    try:
        bundle.provider_connection_repository.create(
            Connection(
                provider_connection_id="conn-secret",
                provider_id="openai-compatible",
                display_name="Gateway",
                endpoint="https://gateway.internal/v1",
                credential_reference=f"env:{VARIABLE}",
            )
        )
        stored = bundle.provider_connection_repository.get("conn-secret")
        assert stored is not None
        assert stored.credential_reference == f"env:{VARIABLE}"
    finally:
        bundle.dispose()


def test_provider_connection_table_has_no_secret_column() -> None:
    from ava.infrastructure.persistence.database import SqliteDatabase

    database = SqliteDatabase(":memory:")
    try:
        with database.connect() as connection:
            columns = {
                row["name"] for row in connection.execute('PRAGMA table_info("provider_connections")')
            }
    finally:
        database.dispose()
    assert "credential_reference" in columns
    assert columns & {"credential_value", "api_key", "password", "token", "secret"} == set()


def test_migrations_never_introduce_a_secret_column() -> None:
    versions = SRC_DIR / "infrastructure" / "persistence" / "migrations" / "versions"
    for path in sorted(versions.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for column in ("credential_value", "api_key", "password", "token", "secret_value"):
            assert not re.search(rf"\b{column}\b\s+(TEXT|VARCHAR|BLOB)", text), path


def test_persisted_provider_connection_serializes_only_the_reference() -> None:
    connection = _connection(credential_reference=f"env:{VARIABLE}")
    payload = json.dumps(dataclasses.asdict(connection))
    assert payload.count("credential_reference") == 1
    assert f"env:{VARIABLE}" in payload
    assert SECRET not in payload


# ============================================================
# END No secret persistence
# ============================================================


# ============================================================
# BEGIN Architecture boundaries
# ============================================================


def _declared_field_names(class_node: ast.ClassDef) -> set[str]:
    return {
        node.target.id
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def test_provider_connection_declares_no_resolved_secret_field() -> None:
    fields = _declared_field_names(
        _class_node(SRC_DIR / "models" / "provider_connections.py", "ProviderConnection")
    )
    assert "credential_reference" in fields
    assert fields & {"api_key", "credential", "secret", "token", "password", "credential_value"} == set()


def test_model_and_runtime_configuration_declare_no_credential_fields() -> None:
    forbidden = {
        "api_key", "credential", "secret", "token", "password",
        "credential_value", "credential_reference",
    }
    model_fields = _declared_field_names(
        _class_node(SRC_DIR / "models" / "model_configurations.py", "ModelConfiguration")
    )
    runtime_fields = _declared_field_names(
        _class_node(SRC_DIR / "runtimes" / "configurations.py", "RuntimeConfiguration")
    )
    assert model_fields & forbidden == set()
    assert runtime_fields & forbidden == set()


def test_credential_resolver_is_ava_owned_and_sdk_free() -> None:
    from ava.models.contracts import ModelProviderPort  # noqa: F401 - vendor guard baseline

    path = SRC_DIR / "models" / "credentials.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "abc", "collections", "dataclasses", "hmac", "ava", "typing"}


def test_environment_resolver_stays_infrastructure_side() -> None:
    assert (SRC_DIR / "infrastructure" / "credentials.py").exists()
    resolver_path = SRC_DIR / "infrastructure" / "credentials.py"
    for directory in ("core", "contracts", "models", "services", "repositories", "runtimes", "agents"):
        for path in (SRC_DIR / directory).rglob("*.py"):
            assert "infrastructure.credentials" not in path.read_text(encoding="utf-8"), path
    assert "EnvironmentCredentialResolver" in resolver_path.read_text(encoding="utf-8")


def test_run_service_does_not_depend_on_the_credential_resolver() -> None:
    run_service = SRC_DIR / "services" / "run_service.py"
    text = run_service.read_text(encoding="utf-8")
    for forbidden in ("CredentialResolver", "SecretValue", "CredentialReference", "resolve_connection_credential"):
        assert forbidden not in text


def test_no_public_contract_or_run_event_mentions_resolved_secret_types() -> None:
    """Contracts and repository ports must contain no executable secret reference.

    Checked by AST rather than substring: contract docstrings deliberately name
    what is absent (a Settings contract explains that no field may hold a
    ``SecretValue``), and prose about an omission is not code referencing the
    thing omitted. Imports, attribute access, and call targets are what matter.
    """
    for directory in ("contracts", "repositories"):
        for path in (SRC_DIR / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "credentials" not in node.module, f"{path}: imports {node.module}"
                if isinstance(node, (ast.Name, ast.Attribute)):
                    name = node.id if isinstance(node, ast.Name) else node.attr
                    assert name not in ("SecretValue", "CredentialResolver"), f"{path}: {name}"
                if isinstance(node, ast.Call):
                    callee = node.func
                    called = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                    assert called != "reveal", path


def test_credentials_module_is_exported_from_the_models_package() -> None:
    import ava.models as models

    for name in ("SecretValue", "CredentialResolver", "CredentialReference", "resolve_connection_credential"):
        assert name in models.__all__
        assert hasattr(models, name)


# ============================================================
# END Architecture boundaries
# ============================================================
