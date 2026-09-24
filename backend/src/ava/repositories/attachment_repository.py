"""AVA-owned attachment repository port.

Expresses the durable *metadata* semantics of AVA attachments, so durable
implementations can satisfy the same contract without changing attachment
behavior.

The port is deliberately framework-neutral: no SQL, ORM entities, sessions,
transactions, queries, rows, or database drivers — and no physical content
concepts. Physical bytes live behind the ``AttachmentContentStore`` seam,
which is deliberately out of Step 4.14.A scope (Step 4.14.B+). A repository
never reads, writes, opens, streams, or uploads file bytes; it stores
metadata only.

Inputs and outputs use the AVA-owned ``AttachmentRecord`` snapshot and
primitive values only. Attachment identifiers and storage keys are
caller-supplied; a repository never mints ids and never interprets
``storage_key`` as a filesystem path. The only mutation the port exposes is
``update_state`` — advancing the lifecycle-controlled ``size_bytes``/``status``
pair — which the ``AttachmentService`` (Step 4.14.E) drives; orchestration
logic lives in the service, never in the port.
"""

from abc import ABC, abstractmethod
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.attachments import AttachmentOwnerType, AttachmentStatus

# ============================================================
# BEGIN: Attachment Record
# ============================================================


@dataclass(frozen=True)
class AttachmentRecord:
    """AVA-owned immutable metadata snapshot of an attachment.

    Metadata only: no physical file bytes, no provider-specific fields
    (``s3_bucket``/``azure_container``/``dbfs_path``/``local_absolute_path``),
    no wire-only contract version, and no filesystem absolute path. Content
    is referenced only through the opaque ``storage_key``, and file bytes
    live behind the content-store seam (Step 4.14.B+).

    ``owner_type``/``owner_id`` form a nullable owner pair: either both are
    set (the attachment is associated with a document, conversation, or
    message) or both are ``None`` (an unassociated attachment). The pair is
    validated by repositories on ``create``. ``size_bytes`` is
    caller-supplied metadata in this foundation slice (``>= 0``, zero-byte
    files allowed); the content store makes stored size authoritative once
    physical storage exists.

    ``created_at`` is a timezone-aware UTC timestamp (``datetime.now(UTC)``
    semantics); durable adapters must preserve aware-UTC round-tripping.
    Checksum support (``sha256``) is deferred; ``status`` is the only
    lifecycle-progressing field.
    """

    attachment_id: str
    file_name: str
    media_type: str
    size_bytes: int
    storage_key: str
    owner_type: AttachmentOwnerType | None
    owner_id: str | None
    status: AttachmentStatus
    created_at: datetime


# ============================================================
# END: Attachment Record
# ============================================================


# ============================================================
# BEGIN: Attachment Repository
# ============================================================


class AttachmentRepository(ABC):
    """Port that attachment repositories must satisfy.

    Responsibilities:

    * ``create`` — persist a new attachment metadata record; a duplicate
      ``attachment_id`` or duplicate ``storage_key`` is an error.
    * ``get`` — read one attachment's metadata by id, or ``None``.
    * ``list_for_owner`` — enumerate an owner's attachments in stable
      insertion order.
    * ``update_state`` — advance the lifecycle-controlled ``size_bytes`` and
      ``status`` pair by id (the port's only mutation).

    ``create`` is the create-time validation boundary this foundation slice
    guarantees: the owner pair must be both-set or both-``None``, and
    ``size_bytes`` must be non-negative. ``update_state`` carries the same
    non-negative-size rule and mutates exactly the two fields the
    ``AttachmentService`` owns (authoritative stored size + lifecycle status).

    Deliberately not part of this port: attachment identity generation,
    physical-content read/write (content store), orchestration of lifecycle
    transitions, delete semantics, query language, and observability helpers
    (``clear``).
    """

    @abstractmethod
    def create(self, record: AttachmentRecord) -> AttachmentRecord:
        """Persist a new attachment metadata record.

        Args:
            record: The AVA-owned immutable metadata snapshot to store.

        Returns:
            The record as stored, unchanged.

        Raises:
            ValueError: If an attachment with this ``attachment_id`` already
                exists, if ``storage_key`` is already in use, if the owner
                pair is not both-set/both-``None``, or if ``size_bytes`` is
                negative.
        """
        raise NotImplementedError

    @abstractmethod
    def get(self, attachment_id: str) -> AttachmentRecord | None:
        """Return the attachment's metadata snapshot, or ``None`` if unknown."""
        raise NotImplementedError

    @abstractmethod
    def list_for_owner(
        self,
        owner_type: AttachmentOwnerType,
        owner_id: str,
    ) -> Collection[AttachmentRecord]:
        """Return an owner's attachments in stable insertion order.

        Args:
            owner_type: The AVA owner kind (document/conversation/message).
            owner_id: The AVA-owned owner identifier.

        Returns:
            An ordered immutable snapshot of the owner's attachments.
            Unassociated attachments and attachments owned by another type or
            id are never returned.
        """
        raise NotImplementedError

    @abstractmethod
    def update_state(
        self,
        attachment_id: str,
        *,
        size_bytes: int,
        status: AttachmentStatus,
    ) -> AttachmentRecord | None:
        """Advance the lifecycle-controlled ``size_bytes``/``status`` pair by id.

        The only mutation the port exposes. ``size_bytes`` and ``status`` are
        the two lifecycle-controlled fields the ``AttachmentService`` drives
        (authoritative stored size + final lifecycle status); every other
        field is immutable. Unlike ``create``, this never raises for a known
        attachment: the updated snapshot is returned, or ``None`` when the
        attachment is unknown.

        Args:
            attachment_id: The AVA-owned attachment identifier.
            size_bytes: The authoritative stored byte count to record
                (``>= 0``; zero-byte files allowed).
            status: The lifecycle status to record.

        Returns:
            The refreshed metadata snapshot, or ``None`` if the attachment is
            unknown.

        Raises:
            ValueError: If ``size_bytes`` is negative.
        """
        raise NotImplementedError


# ============================================================
# END: Attachment Repository
# ============================================================