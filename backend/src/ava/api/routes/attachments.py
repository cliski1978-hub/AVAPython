"""Attachment routes (Step 4.14.F).

Thin transport layer: every decision about storage paths, lifecycle
transitions, and the physical ``storage_key`` lives in ``AttachmentService``,
and the wire contracts live in ``ava.contracts``. Routes consume the shared
``app.state.attachment_service`` composed at startup; they never construct
services, repositories, or content stores.

Semantics:
    * ``POST /attachments`` accepts multipart form data and responds ``201
      Created`` with an ``available`` attachment. The display ``file_name``
      travels as multipart metadata and never influences storage keys (audit
      §7); its absence is rejected with ``422``. ``owner_type``/``owner_id``
      must be both present or both absent.
    * ``GET /attachments`` returns one owner's attachments in stable
      insertion order; the owner pair is required (there is no global list).
    * ``GET /attachments/{attachment_id}`` returns metadata only and never
      touches content, so it can describe ``pending``/``failed`` records.
    * ``GET /attachments/{attachment_id}/content`` streams bytes untouched
      for ``available`` attachments with a ``Content-Disposition:
      attachment`` header (browsers download rather than inline-execute). The
      header is sanitized against CR/LF injection and never reinterprets the
      display name as a filesystem path; the stream is closed after delivery.
"""

from collections.abc import Iterator
from typing import Annotated, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ava.contracts.attachments import (
    AttachmentListResponse,
    AttachmentOwnerType,
    AttachmentResponse,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.repositories.attachment_repository import AttachmentRecord
from ava.services.attachment_service import (
    AttachmentService,
    AttachmentStateError,
    AttachmentStorageError,
)

router = APIRouter(tags=["attachments"])


# ============================================================
# BEGIN: Create Attachment
# ============================================================


@router.post(
    "/attachments",
    response_model=AttachmentResponse,
    status_code=201,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def create_attachment(
    request: Request,
    file: Annotated[UploadFile, File()],
    owner_type: Annotated[AttachmentOwnerType | None, Form()] = None,
    owner_id: Annotated[str | None, Form()] = None,
) -> AttachmentResponse | JSONResponse:
    """Create an attachment from uploaded multipart bytes.

    The service mints the id, key, and timestamp; the route invents none of
    them. The uploaded stream is handed straight to the service's store
    without being buffered in full here. A missing filename is rejected
    (``422``); storage failures map to ``500`` without leaking storage
    internals.
    """
    if (owner_type is None) != (owner_id is None):
        return _invalid_owner_pair()
    if not file.filename:
        return _missing_file_name()
    service: AttachmentService = request.app.state.attachment_service
    try:
        record = service.create_attachment(
            file_name=file.filename,
            media_type=file.content_type or "application/octet-stream",
            source=file.file,
            owner_type=owner_type,
            owner_id=owner_id,
        )
    except AttachmentStorageError:
        return _storage_failure()
    return _attachment_to_response(record)


# ============================================================
# END: Create Attachment
# ============================================================


# ============================================================
# BEGIN: List Attachments
# ============================================================


@router.get("/attachments", response_model=AttachmentListResponse)
async def list_attachments(
    request: Request,
    owner_type: AttachmentOwnerType,
    owner_id: str,
) -> AttachmentListResponse:
    """Return one owner's attachments in stable insertion order.

    Both query parameters are required: there is no global attachment list,
    and unassociated attachments are never listed here. Missing parameters
    are rejected by FastAPI with ``422``.
    """
    service: AttachmentService = request.app.state.attachment_service
    records = service.list_attachments(owner_type, owner_id)
    return AttachmentListResponse(
        owner_type=owner_type,
        owner_id=owner_id,
        attachments=[_attachment_to_response(record) for record in records],
    )


# ============================================================
# END: List Attachments
# ============================================================


# ============================================================
# BEGIN: Get Attachment Metadata
# ============================================================


@router.get(
    "/attachments/{attachment_id}",
    response_model=AttachmentResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_attachment(
    request: Request, attachment_id: str
) -> AttachmentResponse | JSONResponse:
    """Return attachment metadata, or ``404`` if unknown.

    Metadata only: the content store is never touched, so known
    ``pending``/``failed`` records are still described for inspection.
    """
    service: AttachmentService = request.app.state.attachment_service
    record = service.get_attachment(attachment_id)
    if record is None:
        return _unknown_attachment(attachment_id)
    return _attachment_to_response(record)


# ============================================================
# END: Get Attachment Metadata
# ============================================================


# ============================================================
# BEGIN: Get Attachment Content
# ============================================================


@router.get(
    "/attachments/{attachment_id}/content",
    response_model=None,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_attachment_content(
    request: Request, attachment_id: str
) -> StreamingResponse | JSONResponse:
    """Stream an available attachment's bytes untouched.

    Only ``available`` attachments expose content: ``pending``/``failed``
    return ``409`` and unknown ids ``404``. The stream is passed through from
    the service without full buffering and is closed after delivery. The
    response header pins ``Content-Disposition: attachment`` so the payload
    is downloaded, never inline-executed.
    """
    service: AttachmentService = request.app.state.attachment_service
    try:
        ref = service.open_attachment_content(attachment_id)
    except AttachmentStateError:
        return _content_unavailable(attachment_id)
    except AttachmentStorageError:
        return _storage_failure()
    if ref is None:
        return _unknown_attachment(attachment_id)
    return StreamingResponse(
        _iter_chunks(ref.stream),
        headers={
            "content-type": ref.record.media_type,
            "content-disposition": _content_disposition(ref.record.file_name),
        },
    )


# ============================================================
# END: Get Attachment Content
# ============================================================


def _attachment_to_response(record: AttachmentRecord) -> AttachmentResponse:
    """Map stored attachment metadata to the wire response contract.

    The single record → response seam for every metadata route (POST/GET/
    list). It maps exactly the approved fields and deliberately drops the
    physical ``storage_key`` and any storage internals. It never opens or
    reads content.
    """
    return AttachmentResponse(
        attachment_id=record.attachment_id,
        file_name=record.file_name,
        media_type=record.media_type,
        size_bytes=record.size_bytes,
        owner_type=record.owner_type,
        owner_id=record.owner_id,
        status=record.status,
        created_at=record.created_at,
    )


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    """Stream a caller-owned binary file and close it after delivery.

    The service hands the route a caller-owned stream; this wrapper is the
    route's close guarantee so the descriptor never leaks, including when
    the response is interrupted.
    """
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        stream.close()


def _content_disposition(file_name: str) -> str:
    """Build a safe ``Content-Disposition`` value (transport-only).

    Always ``attachment`` so browsers download rather than inline-execute.
    Non-printable bytes (notably CR/LF and unicode line separators) are
    dropped, which makes header injection impossible and keeps the header
    ASCII-only: a plain-ASCII ``filename`` covers legacy clients and a quoted
    ``filename*`` (RFC 5987) carries the full Unicode display name. The value
    is display metadata and is never interpreted as a filesystem path.
    """
    display = "".join(ch for ch in file_name if ch.isprintable())
    ascii_name = display.encode("ascii", "ignore").decode("ascii")
    fallback = (ascii_name or "attachment").replace("\\", "_").replace('"', "_")
    header = f'attachment; filename="{fallback}"'
    if ascii_name != display:
        header += f"; filename*=UTF-8''{quote(display.encode('utf-8'), safe='')}"
    return header


def _missing_file_name() -> JSONResponse:
    """Build a 422 JSON response for an upload without a filename."""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="missing_file_name",
            category=ErrorCategory.VALIDATION,
            message="Upload requires a filename",
        ).model_dump(),
    )


def _invalid_owner_pair() -> JSONResponse:
    """Build a 422 JSON response for a half-set owner pair."""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="invalid_owner_pair",
            category=ErrorCategory.VALIDATION,
            message="owner_type and owner_id must be both present or both absent",
        ).model_dump(),
    )


def _unknown_attachment(attachment_id: str) -> JSONResponse:
    """Build a 404 JSON response for an unknown attachment identifier."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="attachment_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown attachment: {attachment_id}",
        ).model_dump(),
    )


def _content_unavailable(attachment_id: str) -> JSONResponse:
    """Build a 409 JSON response for a pending/failed attachment's content."""
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code="attachment_content_unavailable",
            category=ErrorCategory.UNAVAILABLE,
            message=f"Attachment content is not available: {attachment_id}",
        ).model_dump(),
    )


def _storage_failure() -> JSONResponse:
    """Build a 500 JSON response for attachment storage failures.

    The message is deliberately generic: storage keys, paths, and adapter
    internals must never reach the client.
    """
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="attachment_storage_failure",
            category=ErrorCategory.INTERNAL,
            message="Attachment storage failed.",
            recoverable=False,
        ).model_dump(),
    )