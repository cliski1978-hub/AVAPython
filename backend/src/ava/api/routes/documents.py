"""Document routes.

Kept deliberately thin; orchestration lives in ``DocumentService`` and the
wire contracts live in ``ava.contracts``. Routes operate entirely with
AVA-owned types and never depend on concrete stores, editor implementations
(Tiptap), or vendor SDKs.

Semantics: ``POST /documents`` creates a resource and responds ``201
Created`` (consistent with ``POST /conversations``). Document identifiers
are always service-generated; clients never supply them. Content is
validated against the AVA HTML content policy by the service (``422`` on
violation). Retrieval endpoints return snapshots, not streams.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ava.contracts.documents import (
    CreateDocumentRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentRevisionListResponse,
    DocumentRevisionResponse,
    UpdateDocumentRequest,
)
from ava.contracts.errors import ErrorCategory, ErrorResponse
from ava.services.document_service import (
    DocumentService,
    DuplicateDocumentError,
    InvalidDocumentContentError,
)

router = APIRouter(tags=["documents"])


# ============================================================
# BEGIN: Create Document
# ============================================================


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=201,
    responses={409: {"model": ErrorResponse}},
)
async def create_document(
    request: Request, body: CreateDocumentRequest
) -> DocumentResponse | JSONResponse:
    """Create an AVA document.

    Ava generates the document identifier in the service layer; the route
    never invents one. An omitted or blank title resolves to the service's
    default title. Content is validated against the AVA HTML content policy
    before it becomes trusted backend content.
    """
    service: DocumentService = request.app.state.document_service
    try:
        return service.create_document(
            title=body.title,
            content=body.content,
            content_format=body.content_format,
        )
    except DuplicateDocumentError as exc:
        return _duplicate_document(exc)
    except InvalidDocumentContentError as exc:
        return _invalid_content(exc)


# ============================================================
# END: Create Document
# ============================================================


# ============================================================
# BEGIN: List Documents
# ============================================================


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(request: Request) -> DocumentListResponse:
    """Return all AVA documents in stable insertion order."""
    service: DocumentService = request.app.state.document_service
    return service.list_documents()


# ============================================================
# END: List Documents
# ============================================================


# ============================================================
# BEGIN: Get Document
# ============================================================


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_document(
    request: Request, document_id: str
) -> DocumentResponse | JSONResponse:
    """Return an AVA document as a snapshot, or ``404`` if unknown."""
    service: DocumentService = request.app.state.document_service
    document = service.get_document(document_id)
    if document is None:
        return _unknown_document(document_id)
    return document


# ============================================================
# END: Get Document
# ============================================================


# ============================================================
# BEGIN: Revision History (Step 4.13.E)
# ============================================================


@router.get(
    "/documents/{document_id}/revisions",
    response_model=DocumentRevisionListResponse,
    responses={404: {"model": ErrorResponse}},
)
async def list_revisions(
    request: Request, document_id: str
) -> DocumentRevisionListResponse | JSONResponse:
    """Return a document's immutable revision history, or ``404`` if unknown.

    Revisions are returned in ``revision_number`` ascending order. The
    ``/documents/{document_id}`` route and these history routes are distinct
    path shapes, so they never conflict. An unknown document returns ``404``;
    a known document with no history yet returns ``200`` with an empty list.
    """
    service: DocumentService = request.app.state.document_service
    result = service.list_revisions(document_id)
    if result is None:
        return _unknown_document(document_id)
    return result


@router.get(
    "/documents/{document_id}/revisions/{revision_id}",
    response_model=DocumentRevisionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_revision(
    request: Request, document_id: str, revision_id: str
) -> DocumentRevisionResponse | JSONResponse:
    """Return an exact document-scoped revision, or ``404`` when missing.

    Unknowable in three cases, all returning ``404``: unknown document,
    known document with an unknown revision, or a revision that belongs to a
    different document (revisions never resolve globally by id alone).
    """
    service: DocumentService = request.app.state.document_service
    revision = service.get_revision(document_id, revision_id)
    if revision is None:
        return _unknown_document(document_id)
    return revision


# ============================================================
# END: Revision History (Step 4.13.E)
# ============================================================


# ============================================================
# BEGIN: Update Document
# ============================================================


@router.patch(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    responses={404: {"model": ErrorResponse}},
)
async def update_document(
    request: Request, document_id: str, body: UpdateDocumentRequest
) -> DocumentResponse | JSONResponse:
    """Update an AVA document's title and/or content atomically.

    The request contract rejects empty updates and blank fields (``422``)
    before this route runs. The service merges the supplied fields over the
    current state and performs one atomic write that appends exactly one
    revision (a combined title+content request stays one revision). An unknown
    document returns ``404`` regardless of the payload.
    """
    service: DocumentService = request.app.state.document_service
    try:
        result = service.update_document(
            document_id,
            title=body.title,
            content=body.content,
            content_format=body.content_format,
        )
    except InvalidDocumentContentError as exc:
        return _invalid_content(exc)
    if result is None:
        return _unknown_document(document_id)
    return result


# ============================================================
# END: Update Document
# ============================================================


def _unknown_document(document_id: str) -> JSONResponse:
    """Build a 404 JSON response for an unknown document identifier."""
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error_code="document_not_found",
            category=ErrorCategory.NOT_FOUND,
            message=f"Unknown document: {document_id}",
        ).model_dump(),
    )


def _duplicate_document(exc: Exception) -> JSONResponse:
    """Build a 409 JSON response for a duplicate document identifier."""
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            error_code="document_id_conflict",
            category=ErrorCategory.VALIDATION,
            message=str(exc),
        ).model_dump(),
    )


def _invalid_content(exc: Exception) -> JSONResponse:
    """Build a 422 JSON response for content rejected by the HTML policy."""
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_code="invalid_document_content",
            category=ErrorCategory.VALIDATION,
            message=str(exc),
        ).model_dump(),
    )