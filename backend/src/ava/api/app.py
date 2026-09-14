"""FastAPI application factory for the AVA backend.

This module is the composition/transport adapter. It is allowed to depend on
AVA Core and the configuration layer:

    FastAPI / API Layer → AVA Core

The forbidden direction is the reverse:

    AVA Core → FastAPI / API Layer
"""

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ava.api.routes.capabilities import router as capabilities_router
from ava.api.routes.health import router as health_router
from ava.api.routes.runs import router as runs_router
from ava.configuration.settings import get_settings
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.core.application import Application, ApplicationConfig
from ava.infrastructure.composition import create_agent_adapter
from ava.services.capability_service import CapabilityService
from ava.services.run_service import RunService

# ============================================================
# BEGIN: Application Factory
# ============================================================


def create_app(
    application: Application | None = None,
    *,
    cors_origins: Sequence[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Composition flow:

        Environment → Settings → ApplicationConfig → Application → Services

    Args:
        application: An AVA core application root. If omitted, one is
            composed from the environment-driven Settings.
        cors_origins: Allowed CORS origins for the transport adapter.

    Returns:
        A configured FastAPI application instance.
    """
    settings = get_settings()
    core_application = application or Application(
        config=ApplicationConfig(
            application_name=settings.application_name,
            environment=settings.environment,
            agent_provider=settings.agent_provider,
            model_provider=settings.model_provider,
        )
    )

    app = FastAPI(title="AVA", version="0.1.0")

    app.state.application = core_application

    # The configured agent adapter is composed once at startup. The API layer
    # consumes it only through services, never directly.
    agent_port = create_agent_adapter(settings.agent_provider)
    app.state.agent_port = agent_port
    app.state.run_service = RunService(agent_port)
    app.state.capability_service = CapabilityService(
        application=core_application.name(),
        agent=agent_port,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins or DEFAULT_CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(Exception, handle_unhandled_exception)

    app.include_router(health_router)
    app.include_router(capabilities_router)
    app.include_router(runs_router)

    return app


async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Map unhandled internal failures to the AVA error contract.

    Kept intentionally small: in-flight activity is awaiting completion (no
    background work exists yet), so an unhandled exception is an internal
    error. Tracebacks and adapter internals must never reach the client.
    """
    logging.getLogger("ava.api").exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="internal_error",
            category=ErrorCategory.INTERNAL,
            message="An internal error occurred.",
            recoverable=False,
        ).model_dump(mode="json"),
    )


# ============================================================
# END: Application Factory
# ============================================================


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "tauri://localhost",
]