from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.tool_features import ToolFeaturesResponse, UpdateToolFeaturesRequest
from ava.services.tool_feature_service import (
    ToolFeatureAdministrationRequiredError,
    ToolFeatureConflictError,
    ToolFeatureService,
)

router = APIRouter(tags=["settings"])


@router.get("/settings/tool-features", response_model=ToolFeaturesResponse)
def get_tool_features(request: Request) -> ToolFeaturesResponse:
    service: ToolFeatureService = request.app.state.tool_feature_service
    return service.state()


@router.put("/settings/tool-features", response_model=ToolFeaturesResponse)
def update_tool_features(request: Request, body: UpdateToolFeaturesRequest) -> ToolFeaturesResponse | JSONResponse:
    service: ToolFeatureService = request.app.state.tool_feature_service
    try:
        return service.update(body)
    except ToolFeatureAdministrationRequiredError as exc:
        code, status, message = "feature_administration_required", 403, str(exc)
    except ToolFeatureConflictError as exc:
        code, status, message = "feature_configuration_conflict", 409, str(exc)
    except ValueError as exc:
        code, status, message = "feature_configuration_invalid", 422, str(exc)
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            error_code=code,
            category=ErrorCategory.CONFIGURATION,
            message=message,
        ).model_dump(mode="json"),
    )
