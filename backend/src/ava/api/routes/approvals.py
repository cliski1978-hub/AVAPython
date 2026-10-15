"""Authenticated, Workspace-scoped approval review and decision API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ava.api.principal import require_verified_principal
from ava.contracts.approvals import (
    ApprovalDecision,
    ApprovalQueueResponse,
    ApprovalRecord,
    ApprovalReviewItem,
    ApprovalStatus,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.contracts.security_identity import VerifiedPrincipal
from ava.repositories.approval_repository import ApprovalConflictError
from ava.services.approval_service import ApprovalExpiredError, ApprovalService, ApprovalUnavailableError

router = APIRouter(tags=["approvals"], dependencies=[Depends(require_verified_principal)])


@router.get("/approvals", response_model=ApprovalQueueResponse)
async def list_approvals(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ApprovalQueueResponse:
    service: ApprovalService = request.app.state.approval_service
    records = service.list_for_current_human(limit=100, principal=principal)
    pending = tuple(_review_item(record) for record in records if record.status == ApprovalStatus.PENDING)
    history = tuple(_review_item(record) for record in records if record.status != ApprovalStatus.PENDING)
    return ApprovalQueueResponse(pending=pending, history=history)


@router.get("/approvals/{approval_id}", response_model=ApprovalReviewItem)
async def get_approval(
    request: Request,
    approval_id: str,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ApprovalReviewItem | JSONResponse:
    service: ApprovalService = request.app.state.approval_service
    try:
        return _review_item(service.get_for_current_human(approval_id, principal=principal))
    except ApprovalUnavailableError:
        return _error(404, "approval_not_found", "Approval was not found.")


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalReviewItem)
async def decide_approval(
    request: Request,
    approval_id: str,
    body: ApprovalDecision,
    principal: Annotated[VerifiedPrincipal, Depends(require_verified_principal)],
) -> ApprovalReviewItem | JSONResponse:
    service: ApprovalService = request.app.state.approval_service
    try:
        record = service.decide_for_current_human(approval_id, body, principal=principal)
        return _review_item(record)
    except ApprovalExpiredError:
        return _error(410, "approval_expired", "Approval has expired.", category=ErrorCategory.VALIDATION)
    except ApprovalConflictError:
        return _error(
            409, "approval_already_resolved", "Approval has already been resolved.", category=ErrorCategory.VALIDATION
        )
    except ApprovalUnavailableError:
        return _error(404, "approval_not_found", "Approval was not found.")


def _review_item(record: ApprovalRecord) -> ApprovalReviewItem:
    metadata = record.decision_metadata
    return ApprovalReviewItem(
        approval_id=record.approval_id,
        run_id=record.run_id,
        invocation_id=record.invocation_id,
        tool_id=record.tool_id,
        tool_version=record.tool_version,
        status=record.status,
        requested_at=record.requested_at,
        expires_at=record.expires_at,
        safe_summary=record.summary,
        decision_at=metadata.decided_at if metadata is not None else None,
        decision_label="Authenticated reviewer" if metadata is not None else None,
        workspace_label=record.workspace_id,
        can_decide=record.status == ApprovalStatus.PENDING,
    )


def _error(
    status_code: int, code: str, message: str, *, category: ErrorCategory = ErrorCategory.NOT_FOUND
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error_code=code, category=category, message=message).model_dump(mode="json"),
    )
