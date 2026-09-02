from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class ImportDraft(db.Model):
    __tablename__ = "import_drafts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    crawl_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("crawl_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
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

    items: Mapped[list["ImportDraftItem"]] = relationship(
        "ImportDraftItem",
        back_populates="draft",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportDraftItem.position",
    )

    def __init__(self, *, crawl_session_id: str, status: str = "draft") -> None:
        self.crawl_session_id = crawl_session_id
        self.status = status


class ImportDraftItem(db.Model):
    __tablename__ = "import_draft_items"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("import_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crawled_media_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("crawled_media.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    is_selected: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    draft: Mapped["ImportDraft"] = relationship("ImportDraft", back_populates="items")
    media: Mapped["CrawledMedia"] = relationship("CrawledMedia")
    product_data: Mapped["ImportDraftProductData | None"] = relationship(
        "ImportDraftProductData",
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    selected_assets: Mapped[list["ImportDraftAsset"]] = relationship(
        "ImportDraftAsset",
        back_populates="draft_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportDraftAsset.position",
    )

    def __init__(
        self,
        *,
        draft_id: str,
        crawled_media_id: str,
        position: int,
        is_selected: bool = True,
    ) -> None:
        self.draft_id = draft_id
        self.crawled_media_id = crawled_media_id
        self.position = position
        self.is_selected = is_selected


class ImportDraftProductData(db.Model):
    __tablename__ = "import_draft_product_data"

    draft_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("import_draft_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    list_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    colors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sizes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    item: Mapped["ImportDraftItem"] = relationship(
        "ImportDraftItem",
        back_populates="product_data",
    )

    def __init__(
        self,
        *,
        draft_item_id: str,
        product_name: str = "",
        description: str = "",
        sale_price: int | None = None,
        list_price: int | None = None,
        stock: int = 0,
        colors: list[str] | None = None,
        sizes: list[str] | None = None,
    ) -> None:
        self.draft_item_id = draft_item_id
        self.product_name = product_name
        self.description = description
        self.sale_price = sale_price
        self.list_price = list_price
        self.stock = stock
        self.colors = list(colors or [])
        self.sizes = list(sizes or [])


class ImportDraftAsset(db.Model):
    __tablename__ = "import_draft_assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    draft_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("import_draft_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    crawled_asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("crawled_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    is_selected: Mapped[bool] = mapped_column(nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)

    draft_item: Mapped["ImportDraftItem"] = relationship(
        "ImportDraftItem",
        back_populates="selected_assets",
    )
    asset: Mapped["CrawledAsset"] = relationship("CrawledAsset")

    def __init__(
        self,
        *,
        draft_item_id: str,
        crawled_asset_id: str,
        position: int,
        is_selected: bool = True,
        is_primary: bool = False,
    ) -> None:
        self.draft_item_id = draft_item_id
        self.crawled_asset_id = crawled_asset_id
        self.position = position
        self.is_selected = is_selected
        self.is_primary = is_primary


from app.models.media import CrawledAsset, CrawledMedia
