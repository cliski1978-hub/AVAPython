"""Settings routes: manage AVA's persisted configuration (Phase 5.10).

A dedicated ``/settings`` boundary, deliberately separate from discovery:

* ``/settings/*`` reads and writes *persisted configuration* — what an operator
  has configured, including disabled records.
* ``/model-providers``, ``/models``, ``/runtimes``, and ``/capabilities`` remain
  *discovery* — what is currently available and healthy.

The two are never merged: discovery still answers from the live registries, and
this router only ever touches the configuration repositories through
``SettingsService``. Nothing here resolves a credential, constructs a provider,
or influences run execution.

Every route is a thin transport shim: validate nothing itself, translate the
service's AVA-owned errors into the existing ``ErrorResponse`` envelope, and
return an explicit contract. Field-level validation is the request model's job
(``422``) and domain validation is the service's.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.settings import (
    ApplicationExecutionDefaultsState,
    CreateModelConfigurationRequest,
    CreateProviderConnectionRequest,
    CreateRuntimeConfigurationRequest,
    ModelConfigurationListResponse,
    ModelConfigurationResponse,
    ProviderConnectionListResponse,
    ProviderConnectionResponse,
    RuntimeConfigurationListResponse,
    RuntimeConfigurationResponse,
    SetApplicationExecutionDefaultsRequest,
    UpdateModelConfigurationRequest,
    UpdateProviderConnectionRequest,
    UpdateRuntimeConfigurationRequest,
)
from ava.services.settings_service import (
    DuplicateSettingsRecordError,
    ImmutableSettingsFieldError,
    InvalidSettingsError,
    SettingsService,
    UnknownSettingsRecordError,
)

router = APIRouter(tags=["settings"])


def _service(request: Request) -> SettingsService:
    service: SettingsService = request.app.state.settings_service
    return service


# ============================================================
# BEGIN: Provider Connections
# ============================================================


@router.get("/settings/providers", response_model=ProviderConnectionListResponse)
def list_provider_connections(request: Request) -> ProviderConnectionListResponse:
    """List every configured provider connection, including disabled ones.

    Settings needs the complete inventory, so nothing is filtered. A
    ``credential_reference`` is returned as stored — it names a location, never
    a secret.
    """
    return _service(request).list_provider_connections()


@router.post(
    "/settings/providers",
    response_model=ProviderConnectionResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_provider_connection(
    request: Request, body: CreateProviderConnectionRequest
) -> ProviderConnectionResponse | JSONResponse:
    """Create a provider connection.

    The client supplies the configuration identity. A supplied
    ``credential_reference`` must be well-formed, but the secret it names is
    never resolved here: saving configuration and testing availability are
    separate concerns, and a transient backend outage must not invalidate stored
    settings.
    """
    try:
        return _service(request).create_provider_connection(body)
    except DuplicateSettingsRecordError as exc:
        return _conflict("provider_connection_already_exists", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_provider_connection", exc)


@router.get(
    "/settings/providers/{provider_connection_id}",
    response_model=ProviderConnectionResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_provider_connection(
    request: Request, provider_connection_id: str
) -> ProviderConnectionResponse | JSONResponse:
    """Return one configured provider connection, or ``404`` if unknown."""
    try:
        return _service(request).get_provider_connection(provider_connection_id)
    except UnknownSettingsRecordError as exc:
        return _not_found("provider_connection_not_found", exc)


@router.put(
    "/settings/providers/{provider_connection_id}",
    response_model=ProviderConnectionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_provider_connection(
    request: Request, provider_connection_id: str, body: UpdateProviderConnectionRequest
) -> ProviderConnectionResponse | JSONResponse:
    """Replace a provider connection's mutable fields.

    The provider association is immutable: resend the current ``provider_id`` or
    omit it, and any other value is a ``409`` rather than a silent reassignment.
    """
    try:
        return _service(request).update_provider_connection(provider_connection_id, body)
    except UnknownSettingsRecordError as exc:
        return _not_found("provider_connection_not_found", exc)
    except ImmutableSettingsFieldError as exc:
        return _conflict("provider_connection_field_immutable", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_provider_connection", exc)


# ============================================================
# END: Provider Connections
# ============================================================


# ============================================================
# BEGIN: Model Configurations
# ============================================================


@router.get("/settings/models", response_model=ModelConfigurationListResponse)
def list_model_configurations(request: Request) -> ModelConfigurationListResponse:
    """List every configured model, including disabled ones.

    Distinct from ``GET /models``, which reports discovered availability and
    health. This endpoint answers "what has been configured?".
    """
    return _service(request).list_model_configurations()


@router.post(
    "/settings/models",
    response_model=ModelConfigurationResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_model_configuration(
    request: Request, body: CreateModelConfigurationRequest
) -> ModelConfigurationResponse | JSONResponse:
    """Create a model configuration against an existing provider connection.

    A connection that does not exist is a ``422``: this endpoint never
    manufactures one, because inventing a connection would give a model an
    endpoint nobody configured.
    """
    try:
        return _service(request).create_model_configuration(body)
    except DuplicateSettingsRecordError as exc:
        return _conflict("model_configuration_already_exists", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_model_configuration", exc)


@router.get(
    "/settings/models/{model_id}",
    response_model=ModelConfigurationResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_model_configuration(request: Request, model_id: str) -> ModelConfigurationResponse | JSONResponse:
    """Return one configured model, or ``404`` if unknown."""
    try:
        return _service(request).get_model_configuration(model_id)
    except UnknownSettingsRecordError as exc:
        return _not_found("model_configuration_not_found", exc)


@router.put(
    "/settings/models/{model_id}",
    response_model=ModelConfigurationResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_model_configuration(
    request: Request, model_id: str, body: UpdateModelConfigurationRequest
) -> ModelConfigurationResponse | JSONResponse:
    """Replace a model's mutable fields.

    The provider-connection association is immutable: a configured model can
    never be silently re-pointed at a different deployment.
    """
    try:
        return _service(request).update_model_configuration(model_id, body)
    except UnknownSettingsRecordError as exc:
        return _not_found("model_configuration_not_found", exc)
    except ImmutableSettingsFieldError as exc:
        return _conflict("model_configuration_field_immutable", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_model_configuration", exc)


# ============================================================
# END: Model Configurations
# ============================================================


# ============================================================
# BEGIN: Runtime Configurations
# ============================================================


@router.get("/settings/runtimes", response_model=RuntimeConfigurationListResponse)
def list_runtime_configurations(request: Request) -> RuntimeConfigurationListResponse:
    """List every configured runtime, including disabled ones.

    Distinct from ``GET /runtimes``, which reports which runtime
    implementations are registered. This endpoint answers "which runtime
    instances have been configured?".
    """
    return _service(request).list_runtime_configurations()


@router.post(
    "/settings/runtimes",
    response_model=RuntimeConfigurationResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_runtime_configuration(
    request: Request, body: CreateRuntimeConfigurationRequest
) -> RuntimeConfigurationResponse | JSONResponse:
    """Create a runtime configuration.

    ``runtime_type`` is not checked against installed runtimes and the runtime
    registry is never mutated from here.
    """
    try:
        return _service(request).create_runtime_configuration(body)
    except DuplicateSettingsRecordError as exc:
        return _conflict("runtime_configuration_already_exists", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_runtime_configuration", exc)


@router.get(
    "/settings/runtimes/{runtime_configuration_id}",
    response_model=RuntimeConfigurationResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_runtime_configuration(
    request: Request, runtime_configuration_id: str
) -> RuntimeConfigurationResponse | JSONResponse:
    """Return one configured runtime, or ``404`` if unknown."""
    try:
        return _service(request).get_runtime_configuration(runtime_configuration_id)
    except UnknownSettingsRecordError as exc:
        return _not_found("runtime_configuration_not_found", exc)


@router.put(
    "/settings/runtimes/{runtime_configuration_id}",
    response_model=RuntimeConfigurationResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_runtime_configuration(
    request: Request, runtime_configuration_id: str, body: UpdateRuntimeConfigurationRequest
) -> RuntimeConfigurationResponse | JSONResponse:
    """Replace a runtime's display name and enabled state.

    The adapter type is immutable, so a ``native`` identity cannot be
    re-pointed at ``openhands`` under the same configuration id.
    """
    try:
        return _service(request).update_runtime_configuration(runtime_configuration_id, body)
    except UnknownSettingsRecordError as exc:
        return _not_found("runtime_configuration_not_found", exc)
    except ImmutableSettingsFieldError as exc:
        return _conflict("runtime_configuration_field_immutable", exc)
    except InvalidSettingsError as exc:
        return _invalid("invalid_runtime_configuration", exc)


# ============================================================
# END: Runtime Configurations
# ============================================================


# ============================================================
# BEGIN: Application Execution Defaults
# ============================================================


@router.get("/settings/defaults", response_model=ApplicationExecutionDefaultsState)
def get_execution_defaults(request: Request) -> ApplicationExecutionDefaultsState:
    """Return the application's execution defaults.

    Not a list: a deployment has at most one defaults record. "Not configured
    yet" is reported as ``configured: false`` with a null ``defaults`` rather
    than ``404``, because an unconfigured application is normal state, not a
    missing resource.
    """
    return _service(request).get_execution_defaults()


@router.put(
    "/settings/defaults",
    response_model=ApplicationExecutionDefaultsState,
    responses={422: {"model": ErrorResponse}},
)
def set_execution_defaults(
    request: Request, body: SetApplicationExecutionDefaultsRequest
) -> ApplicationExecutionDefaultsState | JSONResponse:
    """Replace the application execution defaults.

    All three references must resolve to existing, enabled records, and the
    selected model must belong to the selected provider connection. Defaults
    reference configured identity only — adapter keys such as ``provider_id``,
    ``provider_model_name``, or ``runtime_type`` are not accepted.
    """
    try:
        return _service(request).set_execution_defaults(body)
    except InvalidSettingsError as exc:
        return _invalid("invalid_execution_defaults", exc)


# ============================================================
# END: Application Execution Defaults
# ============================================================


# ============================================================
# BEGIN: Error Translation
# ============================================================


def _error(error_code: str, category: ErrorCategory, exc: Exception, status_code: int) -> JSONResponse:
    """Build an AVA error response.

    Service messages are already safe: they name configuration identity and
    credential reference *locations*, never resolved secret material, and never
    carry a stack trace.
    """
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=error_code, category=category, message=str(exc)).model_dump(),
    )


def _not_found(error_code: str, exc: Exception) -> JSONResponse:
    return _error(error_code, ErrorCategory.NOT_FOUND, exc, 404)


def _conflict(error_code: str, exc: Exception) -> JSONResponse:
    return _error(error_code, ErrorCategory.VALIDATION, exc, 409)


def _invalid(error_code: str, exc: Exception) -> JSONResponse:
    return _error(error_code, ErrorCategory.VALIDATION, exc, 422)


# ============================================================
# END: Error Translation
# ============================================================
