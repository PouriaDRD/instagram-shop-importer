from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class LocalSyncStatus(StrEnum):
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"


class RemoteWorkflowStatus(StrEnum):
    UNKNOWN = "unknown"
    NEEDS_REVIEW = "needs_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    IMPORTING = "importing"
    IMPORTED = "imported"
    REJECTED = "rejected"


REMOTE_READ_ONLY_STATUSES = frozenset(
    {
        RemoteWorkflowStatus.APPROVED.value,
        RemoteWorkflowStatus.IMPORTING.value,
        RemoteWorkflowStatus.IMPORTED.value,
        RemoteWorkflowStatus.REJECTED.value,
    }
)


class ImportWorkspace(db.Model):
    """
    Persistent operator workspace for one InstagramSource.

    `status` is kept only as a legacy compatibility column during the
    transition from the old draft/sent lifecycle. New code must use:
      - local_sync_status
      - remote_workflow_status

    The workspace itself is permanent and is NOT closed by a successful send.
    """

    __tablename__ = "import_drafts"

    __table_args__ = (
        UniqueConstraint(
            "crawl_session_id",
            name="uq_import_workspace_source",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    source_id: Mapped[str] = mapped_column(
        "crawl_session_id",
        String(36),
        ForeignKey(
            "crawl_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # Legacy compatibility only. Do not use this field for new lifecycle logic.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )

    local_sync_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LocalSyncStatus.PENDING.value,
        index=True,
    )

    remote_workflow_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RemoteWorkflowStatus.UNKNOWN.value,
        index=True,
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_sync_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    remote_status_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    remote_workspace_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    remote_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    remote_is_editable: Mapped[bool | None] = mapped_column(
        nullable=True,
    )

    remote_lock_token: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    remote_lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items: Mapped[list["ImportWorkspaceItem"]] = relationship(
        "ImportWorkspaceItem",
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportWorkspaceItem.position",
    )

    def __init__(
        self,
        *,
        source_id: str | None = None,
        crawl_session_id: str | None = None,
        status: str = "draft",
        local_sync_status: str = LocalSyncStatus.PENDING.value,
        remote_workflow_status: str = RemoteWorkflowStatus.UNKNOWN.value,
    ) -> None:
        effective_source_id = source_id or crawl_session_id

        if not effective_source_id:
            raise ValueError(
                "ImportWorkspace requires source_id."
            )

        self.source_id = effective_source_id
        self.status = status
        self.local_sync_status = local_sync_status
        self.remote_workflow_status = remote_workflow_status

    @property
    def crawl_session_id(self) -> str:
        return self.source_id

    @property
    def is_remote_read_only(self) -> bool:
        return (
            self.remote_is_editable is False
            or self.remote_workflow_status
            in REMOTE_READ_ONLY_STATUSES
        )

    @property
    def has_remote_workspace(self) -> bool:
        return bool(
            self.remote_workspace_id
        )

    @property
    def has_active_remote_lease(self) -> bool:
        if (
            not self.remote_lock_token
            or self.remote_lock_expires_at is None
        ):
            return False

        expires_at = (
            self.remote_lock_expires_at
        )

        # SQLite does not preserve timezone offsets for DateTime columns,
        # even when SQLAlchemy uses DateTime(timezone=True). Values that
        # originated as UTC-aware timestamps can therefore come back from
        # the local database as naive datetimes. All remote lease timestamps
        # in this importer are Selora UTC timestamps, so a naive value is
        # safely interpreted as UTC before comparison.
        if expires_at.tzinfo is None:
            expires_at = (
                expires_at.replace(
                    tzinfo=timezone.utc
                )
            )
        else:
            expires_at = (
                expires_at.astimezone(
                    timezone.utc
                )
            )

        return (
            expires_at
            > datetime.now(timezone.utc)
        )


class ImportWorkspaceItem(db.Model):
    __tablename__ = "import_draft_items"

    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "crawled_media_id",
            name="uq_import_workspace_item_media",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    workspace_id: Mapped[str] = mapped_column(
        "draft_id",
        String(36),
        ForeignKey(
            "import_drafts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    instagram_media_id: Mapped[str] = mapped_column(
        "crawled_media_id",
        String(36),
        ForeignKey(
            "crawled_media.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    is_selected: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    workspace: Mapped["ImportWorkspace"] = relationship(
        "ImportWorkspace",
        back_populates="items",
    )

    media: Mapped["InstagramMedia"] = relationship(
        "InstagramMedia",
    )

    product_data: Mapped["ImportProductData | None"] = relationship(
        "ImportProductData",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    selected_assets: Mapped[list["ImportAssetSelection"]] = relationship(
        "ImportAssetSelection",
        back_populates="workspace_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportAssetSelection.position",
    )

    def __init__(
        self,
        *,
        workspace_id: str | None = None,
        draft_id: str | None = None,
        instagram_media_id: str | None = None,
        crawled_media_id: str | None = None,
        position: int,
        is_selected: bool = True,
    ) -> None:
        effective_workspace_id = (
            workspace_id or draft_id
        )
        effective_media_id = (
            instagram_media_id
            or crawled_media_id
        )

        if not effective_workspace_id:
            raise ValueError(
                "ImportWorkspaceItem requires workspace_id."
            )

        if not effective_media_id:
            raise ValueError(
                "ImportWorkspaceItem requires instagram_media_id."
            )

        self.workspace_id = effective_workspace_id
        self.instagram_media_id = effective_media_id
        self.position = position
        self.is_selected = is_selected

    @property
    def draft_id(self) -> str:
        return self.workspace_id

    @property
    def crawled_media_id(self) -> str:
        return self.instagram_media_id


class ImportProductData(db.Model):
    __tablename__ = "import_draft_product_data"

    workspace_item_id: Mapped[str] = mapped_column(
        "draft_item_id",
        String(36),
        ForeignKey(
            "import_draft_items.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    sale_price: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    list_price: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    colors: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    sizes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    item: Mapped["ImportWorkspaceItem"] = relationship(
        "ImportWorkspaceItem",
        back_populates="product_data",
    )

    def __init__(
        self,
        *,
        workspace_item_id: str | None = None,
        draft_item_id: str | None = None,
        product_name: str = "",
        description: str = "",
        sale_price: int | None = None,
        list_price: int | None = None,
        stock: int = 0,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
    ) -> None:
        effective_item_id = (
            workspace_item_id
            or draft_item_id
        )

        if not effective_item_id:
            raise ValueError(
                "ImportProductData requires workspace_item_id."
            )

        self.workspace_item_id = effective_item_id
        self.product_name = product_name
        self.description = description
        self.sale_price = sale_price
        self.list_price = list_price
        self.stock = stock
        self.colors = list(colors or [])
        self.sizes = list(sizes or [])

    @property
    def draft_item_id(self) -> str:
        return self.workspace_item_id


class ImportAssetSelection(db.Model):
    __tablename__ = "import_draft_assets"

    __table_args__ = (
        UniqueConstraint(
            "draft_item_id",
            "crawled_asset_id",
            name="uq_import_asset_selection_item_asset",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    workspace_item_id: Mapped[str] = mapped_column(
        "draft_item_id",
        String(36),
        ForeignKey(
            "import_draft_items.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    instagram_asset_id: Mapped[str] = mapped_column(
        "crawled_asset_id",
        String(36),
        ForeignKey(
            "crawled_assets.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    position: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    is_selected: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
    )

    is_primary: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    workspace_item: Mapped["ImportWorkspaceItem"] = relationship(
        "ImportWorkspaceItem",
        back_populates="selected_assets",
    )

    asset: Mapped["InstagramAsset"] = relationship(
        "InstagramAsset",
    )

    def __init__(
        self,
        *,
        workspace_item_id: str | None = None,
        draft_item_id: str | None = None,
        instagram_asset_id: str | None = None,
        crawled_asset_id: str | None = None,
        position: int,
        is_selected: bool = True,
        is_primary: bool = False,
    ) -> None:
        effective_item_id = (
            workspace_item_id
            or draft_item_id
        )
        effective_asset_id = (
            instagram_asset_id
            or crawled_asset_id
        )

        if not effective_item_id:
            raise ValueError(
                "ImportAssetSelection requires workspace_item_id."
            )

        if not effective_asset_id:
            raise ValueError(
                "ImportAssetSelection requires instagram_asset_id."
            )

        self.workspace_item_id = effective_item_id
        self.instagram_asset_id = effective_asset_id
        self.position = position
        self.is_selected = is_selected
        self.is_primary = is_primary

    @property
    def draft_item_id(self) -> str:
        return self.workspace_item_id

    @property
    def crawled_asset_id(self) -> str:
        return self.instagram_asset_id


from app.models.media import (
    InstagramAsset,
    InstagramMedia,
)
