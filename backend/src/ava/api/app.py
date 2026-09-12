"""FastAPI application factory for the AVA backend.

This module is the composition/transport adapter. It is allowed to depend on
AVA Core and the configuration layer:

    FastAPI / API Layer → AVA Core

The forbidden direction is the reverse:

    AVA Core → FastAPI / API Layer
"""

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ava.api.routes.capabilities import router as capabilities_router
from ava.api.routes.health import router as health_router
from ava.configuration.settings import get_settings
from ava.core.application import Application, ApplicationConfig
from ava.services.capability_service import CapabilityService

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
    app.state.capability_service = CapabilityService(
        application=core_application.name()
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins or DEFAULT_CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(capabilities_router)

    return app


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