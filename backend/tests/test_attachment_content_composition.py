"""Attachment content-store composition tests (Step 4.14.D).

Verify the ``AVA_ATTACHMENT_STORAGE`` seam:

* ``memory`` composes ``InMemoryAttachmentContentStore``; ``local`` composes
  ``LocalAttachmentContentStore`` over the configured root;
* the physical store selection is fully independent of the metadata
  persistence provider (``AVA_PERSISTENCE``): every ``memory | relational`` x
  ``memory | local`` combination is valid, and changing the metadata mode
  never silently changes the content mode;
* the application composes one shared content store per startup;
* an unknown storage mode is a configuration error, never a fallback.
"""

from io import BytesIO

import pytest

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
from ava.infrastructure.composition import create_attachment_content_store
from ava.services.attachment_content_store import InMemoryAttachmentContentStore
from ava.services.attachment_service import AttachmentService

# ============================================================
# BEGIN: Seam selection
# ============================================================


def test_memory_mode_composes_the_in_memory_content_store() -> None:
    """The default (memory) seam selects the in-memory adapter."""
    store = create_attachment_content_store(Settings(attachment_storage="memory"))
    assert isinstance(store, InMemoryAttachmentContentStore)


def test_memory_mode_ignores_a_configured_root() -> None:
    """A root supplied in memory mode does not force local construction."""
    store = create_attachment_content_store(
        Settings(attachment_storage="memory", attachment_storage_root="/unused")
    )
    assert isinstance(store, InMemoryAttachmentContentStore)


def test_local_mode_composes_the_local_content_store_with_the_configured_root(tmp_path) -> None:
    """Local mode constructs the local adapter over the exact configured root."""
    root = tmp_path / "storage"
    store = create_attachment_content_store(
        Settings(attachment_storage="local", attachment_storage_root=str(root))
    )
    assert isinstance(store, LocalAttachmentContentStore)

    store.put("attachments/doc-1/source.bin", BytesIO(b"content"))
    assert (root / "attachments" / "doc-1" / "source.bin").read_bytes() == b"content"


def test_unknown_attachment_storage_mode_fails_composition() -> None:
    """An unimplemented mode is a configuration error, never a memory fallback."""
    with pytest.raises(ValueError, match="Unknown attachment storage provider"):
        create_attachment_content_store(Settings(attachment_storage="s3"))
    with pytest.raises(ValueError, match="Unknown attachment storage provider"):
        create_attachment_content_store(Settings(attachment_storage="databricks"))


# ============================================================
# END: Seam selection
# ============================================================


# ============================================================
# BEGIN: Metadata/content independence
# ============================================================


@pytest.mark.parametrize("persistence_provider", ["memory", "relational"])
@pytest.mark.parametrize("attachment_storage", ["memory", "local"])
def test_metadata_and_content_selection_are_independent(
    tmp_path,
    persistence_provider: str,
    attachment_storage: str,
) -> None:
    """Changing the metadata mode never changes the content-store mode."""
    from ava.infrastructure.composition import create_application_persistence

    settings = Settings(
        persistence_provider=persistence_provider,
        persistence_database_url=":memory:",
        attachment_storage=attachment_storage,
        attachment_storage_root=(str(tmp_path / "storage") if attachment_storage == "local" else ""),
    )
    persistence = create_application_persistence(settings, run_migrations=False)
    try:
        store = create_attachment_content_store(settings)
        assert persistence.attachment_repository is not None
        if attachment_storage == "memory":
            assert isinstance(store, InMemoryAttachmentContentStore)
        else:
            assert isinstance(store, LocalAttachmentContentStore)
    finally:
        persistence.dispose()


def test_local_content_root_is_not_the_metadata_database_location(tmp_path) -> None:
    """Local content never reuses the metadata database path as its root."""
    storage_root = tmp_path / "content"
    settings = Settings(
        persistence_provider="relational",
        persistence_database_url=":memory:",
        attachment_storage="local",
        attachment_storage_root=str(storage_root),
    )
    store = create_attachment_content_store(settings)

    store.put("k", BytesIO(b"x"))

    assert (storage_root / "k").is_file()


# ============================================================
# END: Metadata/content independence
# ============================================================


# ============================================================
# BEGIN: Application composition
# ============================================================


def test_default_application_installs_one_shared_in_memory_content_store() -> None:
    """A default application composes one shared in-memory content store."""
    app = create_app()
    try:
        store = app.state.attachment_content_store
        assert isinstance(store, InMemoryAttachmentContentStore)
        assert app.state.attachment_content_store is store
        store.put("k", BytesIO(b"data"))
        assert store.open("k").read() == b"data"
    finally:
        app.state.persistence.dispose()


def test_local_application_installs_the_configured_root_content_store(tmp_path) -> None:
    """A local-configured application wires the root-backed store exactly once."""
    root = tmp_path / "storage"
    app = create_app(settings=Settings(attachment_storage="local", attachment_storage_root=str(root)))
    try:
        store = app.state.attachment_content_store
        assert isinstance(store, LocalAttachmentContentStore)
        assert app.state.attachment_content_store is store

        store.put("k", BytesIO(b"app-level"))
        assert (root / "k").read_bytes() == b"app-level"
    finally:
        app.state.persistence.dispose()


def test_default_application_wires_one_shared_attachment_service() -> None:
    """The application composes one AttachmentService over the shared ports.

    The composed service writes and reads through the same content-store
    instance the application owns, and its metadata lands in the same composed
    repository — so the four ``memory | relational`` x ``memory | local``
    combinations all stay valid through the single service boundary.
    """
    app = create_app()
    try:
        store = app.state.attachment_content_store
        service = app.state.attachment_service
        assert isinstance(service, AttachmentService)
        assert app.state.attachment_service is service

        created = service.create_attachment(
            file_name="x.bin",
            media_type="application/octet-stream",
            source=BytesIO(b"shared"),
        )
        assert created.status.value == "available"
        assert store.open(created.storage_key).read() == b"shared"
        assert service.open_attachment_content(created.attachment_id).stream.read() == b"shared"
        assert app.state.persistence.attachment_repository.get(created.attachment_id) == created
    finally:
        app.state.persistence.dispose()


# ============================================================
# END: Application composition
# ============================================================