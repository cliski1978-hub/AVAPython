"""AVA document application service.

Coordinates the document domain against the AVA-owned repository and write
coordinator ports (Step 4.13.D). The service owns what a repository must not:
document identity generation, timezone-aware UTC timestamps, the default
title, content validation through the AVA HTML content policy, and duplicate
normalization.

Reads (``get``/``list``) go through the ``DocumentRepository`` port; revision
history reads go through the ``DocumentRevisionRepository`` port; every write
goes through the ``DocumentWriteCoordinator`` port so the current state and
its immutable revision history advance as one atomic unit — creating a
document also appends revision 1, and a successful update appends exactly one
next revision.

The service programs against ports, never concrete stores or coordinators.
Composition (``create_app``) injects the implementations. The service is
framework-neutral: no FastAPI, Tiptap, frontend packages, SQL/ORM, model
providers, agent runtimes, or OpenHands.
"""

from datetime import UTC, datetime
from uuid import uuid4

from ava.contracts.documents import (
    ContentFormat,
    DocumentListResponse,
    DocumentResponse,
    DocumentRevisionListResponse,
    DocumentRevisionResponse,
)
from ava.repositories.document_repository import (
    DocumentRecord,
    DocumentRepository,
)
from ava.repositories.document_revision_repository import (
    DocumentRevisionRecord,
    DocumentRevisionRepository,
)
from ava.services.document_write_coordinator import DocumentWriteCoordinator
from ava.services.html_content_policy import HtmlContentError, validate_html_content

DEFAULT_DOCUMENT_TITLE = "Untitled Document"


# ============================================================
# BEGIN: Document Domain Errors
# ============================================================


class DuplicateDocumentError(Exception):
    """Raised when a document identifier collides with an existing one."""


class InvalidDocumentContentError(Exception):
    """Raised when document content violates the AVA HTML content policy."""


# ============================================================
# END: Document Domain Errors
# ============================================================


# ============================================================
# BEGIN: Document Service
# ============================================================


class DocumentService:
    """Delegates document reads to the repository port and writes to the write coordinator.

    Args:
        document_repository: The injected document repository port (current-state
            reads: ``get``/``list``).
        document_revision_repository: The injected document revision repository
            port (immutable history reads: ``list_revisions``/``get_revision``).
        document_write_coordinator: The injected atomic write coordinator port;
            every create/update advances the current state and appends exactly
            one revision as one unit.

    The service generates identifiers and timestamps, resolves the default
    title, enforces the HTML content policy before any content is stored, and
    maps coordinator duplicate collisions onto an explicit domain error.
    Unknown-document operations return ``None`` (the route normalizes to 404).
    """

    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        document_revision_repository: DocumentRevisionRepository,
        document_write_coordinator: DocumentWriteCoordinator,
    ) -> None:
        self._document_repository = document_repository
        self._document_revision_repository = document_revision_repository
        self._document_write_coordinator = document_write_coordinator

    def create_document(
        self,
        *,
        content: str,
        title: str | None = None,
        content_format: ContentFormat = ContentFormat.HTML,
    ) -> DocumentResponse:
        """Create a new document, returning its response contract.

        Args:
            content: The canonical serialized-HTML content.
            title: Optional initial title; blank/omitted values resolve to
                ``DEFAULT_DOCUMENT_TITLE``.
            content_format: The AVA-owned content format (only ``html`` is
                supported today).

        Returns:
            The created document's response contract.

        Raises:
            InvalidDocumentContentError: If the content fails the HTML policy
                or the requested content format is unsupported.
            DuplicateDocumentError: If a document identifier collides.
        """
        _enforce_supported_format(content_format)
        _validate_content(content)
        resolved_title = (title or "").strip() or DEFAULT_DOCUMENT_TITLE
        # One coherent operation timestamp: the document's created_at/updated_at
        # and revision 1's snapshot timestamp describe the same logical creation.
        operation_time = datetime.now(UTC)
        document_id = str(uuid4())
        document = DocumentRecord(
            document_id=document_id,
            title=resolved_title,
            content=content,
            content_format=content_format,
            created_at=operation_time,
            updated_at=operation_time,
        )
        try:
            record, _ = self._document_write_coordinator.create(
                document,
                revision_id=str(uuid4()),
                revision_created_at=operation_time,
            )
        except ValueError as exc:
            raise DuplicateDocumentError(f"Document already exists: {exc}") from exc
        return _document_to_response(record)

    def get_document(self, document_id: str) -> DocumentResponse | None:
        """Return the document, or ``None`` if it is unknown."""
        record = self._document_repository.get(document_id)
        if record is None:
            return None
        return _document_to_response(record)

    def list_documents(self) -> DocumentListResponse:
        """Return all documents in stable insertion order."""
        records = self._document_repository.list()
        return DocumentListResponse(documents=[_document_to_response(record) for record in records])

    def list_revisions(self, document_id: str) -> DocumentRevisionListResponse | None:
        """Return a document's full immutable revision history (revision-number ASC).

        Revisions are returned in ``revision_number`` ascending order
        (1, 2, 3, …), the deterministic order the revision repository already
        guarantees — never reverse and never sorted by timestamp. A known
        document with no history (e.g. a legacy Step 4.6 document adopted
        without backfill) yields an empty ``revisions`` list.

        Args:
            document_id: The AVA-owned document identifier.

        Returns:
            The revision-history response, or ``None`` when the document is
            unknown (the route normalizes to 404, distinguishing it from a
            known document with empty history).
        """
        if self._document_repository.get(document_id) is None:
            return None
        revisions = self._document_revision_repository.list_for_document(document_id)
        return DocumentRevisionListResponse(
            document_id=document_id,
            revisions=[_revision_to_response(record) for record in revisions],
        )

    def get_revision(self, document_id: str, revision_id: str) -> DocumentRevisionResponse | None:
        """Return the exact document-scoped revision, or ``None`` when missing.

        A revision is only ever resolvable through its own document: a
        ``revision_id`` belonging to another document never resolves here
        (each repository's ``get`` is a document-scoped exact lookup).

        Args:
            document_id: The AVA-owned document identifier.
            revision_id: The revision identifier to locate.

        Returns:
            The exact immutable revision, or ``None`` if the document is
            unknown, the revision is unknown, or the revision belongs to
            another document.
        """
        if self._document_repository.get(document_id) is None:
            return None
        record = self._document_revision_repository.get(document_id, revision_id)
        if record is None:
            return None
        return _revision_to_response(record)

    def update_document(
        self,
        document_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        content_format: ContentFormat | None = None,
    ) -> DocumentResponse | None:
        """Atomically update a document's title and/or content (one next revision).

        Loads the current state, merges the supplied mutable fields over it,
        validates the final content, stamps one ``updated_at``, mints one
        ``revision_id``, then hands the fully prepared snapshot to the write
        coordinator — a single atomic call that advances current state and
        appends exactly one next revision. A combined title+content request
        therefore produces one revision, never two.

        Existence is resolved before any validation: an unknown document
        yields ``None`` (404) even when the payload is itself invalid.

        Args:
            document_id: The document identifier.
            title: Optional replacement title (trimmed; must not be blank).
            content: Optional canonical serialized-HTML replacement content.
            content_format: Optional AVA-owned content format. When ``content``
                is provided and this is omitted, it resolves to the AVA default
                ``html`` (matching the update contract's contract semantics).

        Returns:
            The updated document, or ``None`` if it is unknown.

        Raises:
            ValueError: If a supplied title is blank after trimming.
            InvalidDocumentContentError: If the final content fails the HTML
                policy or the content format is unsupported.
        """
        current = self._document_repository.get(document_id)
        if current is None:
            return None
        resolved_title = current.title
        if title is not None:
            resolved_title = title.strip()
            if not resolved_title:
                raise ValueError("title must not be blank")
        resolved_content = current.content
        if content is not None:
            resolved_content = content
        resolved_format: ContentFormat
        if content_format is not None:
            resolved_format = content_format
        elif content is not None:
            resolved_format = ContentFormat.HTML
        else:
            resolved_format = current.content_format
        _enforce_supported_format(resolved_format)
        _validate_content(resolved_content)
        operation_time = datetime.now(UTC)
        document = DocumentRecord(
            document_id=document_id,
            title=resolved_title,
            content=resolved_content,
            content_format=resolved_format,
            created_at=current.created_at,
            updated_at=operation_time,
        )
        record, _ = self._document_write_coordinator.update(
            document,
            revision_id=str(uuid4()),
            revision_created_at=operation_time,
        )
        return _document_to_response(record)

    def rename_document(self, document_id: str, title: str) -> DocumentResponse | None:
        """Rename a document, returning the updated document (title-only update).

        A thin compatibility wrapper over the atomic ``update_document`` path
        so every write produces exactly one revision.

        Args:
            document_id: The document identifier.
            title: The new, non-blank title.

        Returns:
            The updated document, or ``None`` if it is unknown.

        Raises:
            ValueError: If ``title`` is blank after trimming (defense in
                depth; the update contract already rejects blank titles).
        """
        trimmed_title = title.strip()
        if not trimmed_title:
            raise ValueError("title must not be blank")
        return self.update_document(document_id, title=trimmed_title)

    def update_document_content(
        self,
        document_id: str,
        *,
        content: str,
        content_format: ContentFormat = ContentFormat.HTML,
    ) -> DocumentResponse | None:
        """Replace a document's content, returning the updated document (content-only update).

        A thin compatibility wrapper over the atomic ``update_document`` path
        so every write produces exactly one revision. Existence is resolved
        before content is validated: an unknown document yields ``None`` (404)
        even when the payload is itself invalid.

        Args:
            document_id: The document identifier.
            content: The canonical serialized-HTML content.
            content_format: The AVA-owned content format.

        Returns:
            The updated document, or ``None`` if it is unknown.

        Raises:
            InvalidDocumentContentError: If the content fails the HTML policy
                or the requested content format is unsupported.
        """
        return self.update_document(
            document_id,
            content=content,
            content_format=content_format,
        )


# ============================================================
# END: Document Service
# ============================================================


# ============================================================
# BEGIN: Content Validation Boundary
# ============================================================


def _enforce_supported_format(content_format: ContentFormat) -> None:
    """Reject content formats the backend does not (yet) support.

    Today the ``ContentFormat`` enum has a single member (``html``), so the
    contract already gates formats at the boundary; this is defense in depth
    that becomes reachable the day a second format is added. Until then the
    contract's enum rejection is the tested normalization for "unsupported
    content format".
    """
    if content_format is not ContentFormat.HTML:
        raise InvalidDocumentContentError(f"unsupported content format: {content_format}")


def _validate_content(content: str) -> None:
    """Route content through the AVA HTML content policy.

    Raises:
        InvalidDocumentContentError: If the content violates the policy.
    """
    try:
        validate_html_content(content)
    except HtmlContentError as exc:
        raise InvalidDocumentContentError(str(exc)) from exc


# ============================================================
# END: Content Validation Boundary
# ============================================================


# ============================================================
# BEGIN: Record → Response Conversion
# ============================================================


def _document_to_response(record: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        document_id=record.document_id,
        title=record.title,
        content=record.content,
        content_format=record.content_format,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _revision_to_response(record: DocumentRevisionRecord) -> DocumentRevisionResponse:
    """Map a stored revision snapshot onto the transport contract, exactly.

    Content is not mutated or re-sanitized here (validation happens on write);
    canonical HTML round-trips unchanged. The persistence surrogate primary key
    is never exposed; only the AVA-owned revision identity and snapshot fields
    cross the boundary.
    """
    return DocumentRevisionResponse(
        revision_id=record.revision_id,
        document_id=record.document_id,
        revision_number=record.revision_number,
        title=record.title,
        content=record.content,
        content_format=record.content_format,
        created_at=record.created_at,
    )


# ============================================================
# END: Record → Response Conversion
# ============================================================
