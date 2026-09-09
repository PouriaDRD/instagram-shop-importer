from __future__ import annotations

from typing import Any

from app.models import CrawlSession
from app.models.import_draft import (
    ImportDraft,
    ImportDraftItem,
)


class SeloraPayloadMappingError(ValueError):
    """The local draft cannot be represented by Selora's inbound API."""


class SeloraPayloadMapper:
    def build_import_payload(
        self,
        *,
        draft: ImportDraft,
        crawl_session: CrawlSession,
        client_instance_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            draft.crawl_session_id
            != crawl_session.id
        ):
            raise SeloraPayloadMappingError(
                "این پیش‌نویس متعلق به منبع اینستاگرام انتخاب‌شده نیست."
            )

        if not any(
            item.is_selected
            for item in draft.items
        ):
            raise SeloraPayloadMappingError(
                "حداقل یک محصول برای ارسال باید فعال باشد."
            )

        payload: dict[str, Any] = {
            "external_import_id": draft.id,
            "instagram_username": crawl_session.username,
            "profile": self._build_profile_payload(
                crawl_session=crawl_session
            ),
            "media": [
                self._build_media_payload(
                    item=item
                )
                for item in draft.items
            ],
        }

        if client_instance_id is not None:
            normalized_client_instance_id = (
                client_instance_id.strip()
            )

            if not normalized_client_instance_id:
                raise SeloraPayloadMappingError(
                    "client_instance_id نمی‌تواند خالی باشد."
                )

            sync: dict[str, Any] = {
                "snapshot_mode": "full",
                "client_instance_id": (
                    normalized_client_instance_id
                ),
            }

            if draft.remote_lock_token:
                sync["lock_token"] = (
                    draft.remote_lock_token
                )

            if draft.remote_revision is not None:
                sync["expected_revision"] = (
                    draft.remote_revision
                )

            payload["sync"] = sync

        return payload

    @staticmethod
    def _build_profile_payload(
        *,
        crawl_session: CrawlSession,
    ) -> dict[str, Any]:
        return {
            "username": crawl_session.username,
            "full_name": crawl_session.full_name or "",
            "biography": crawl_session.biography or "",
            "profile_picture_url": (
                crawl_session.profile_picture_url
                or ""
            ),
            "followers_count": crawl_session.followers_count,
            "following_count": crawl_session.following_count,
            "media_count": crawl_session.instagram_media_count,
            "is_private": crawl_session.is_private,
            "raw_payload": {},
        }

    def _build_media_payload(
        self,
        *,
        item: ImportDraftItem,
    ) -> dict[str, Any]:
        media = item.media
        product_data = (
            item.product_data
        )

        if product_data is None:
            raise SeloraPayloadMappingError(
                "اطلاعات محصول یکی از آیتم‌ها ناقص است."
            )

        selected_assets = tuple(
            selected_asset
            for selected_asset
            in item.selected_assets
            if selected_asset.is_selected
        )

        all_available_assets = tuple(
            asset
            for asset in media.assets
            if getattr(
                asset,
                "is_available",
                True,
            )
        )

        return {
            "instagram_media_id": media.media_id,
            "shortcode": media.shortcode,
            "media_type": media.media_type,
            "permalink": media.permalink,
            "caption": media.caption or "",
            "thumbnail_url": media.thumbnail_url or "",
            "published_at": (
                media.published_at.isoformat()
                if media.published_at
                is not None
                else None
            ),
            "like_count": media.like_count,
            "comment_count": media.comment_count,
            "view_count": media.view_count,
            "raw_payload": dict(
                media.raw_payload
                or {}
            ),
            "selected": item.is_selected,
            "visible": getattr(
                media,
                "is_available",
                True,
            ),
            "fetched_order": item.position,
            "assets": [
                {
                    "external_id": asset.external_id,
                    "asset_type": asset.asset_type,
                    "source_url": asset.source_url,
                    "position": asset.position,
                    "width": asset.width,
                    "height": asset.height,
                    "duration_seconds": (
                        asset.duration_seconds
                    ),
                    "metadata": dict(
                        asset.asset_metadata
                        or {}
                    ),
                }
                for asset in all_available_assets
            ],
            "draft": {
                "title": (
                    product_data
                    .product_name
                    .strip()
                ),
                "description": (
                    product_data
                    .description
                    .strip()
                ),
                "price_without_discount": (
                    product_data.list_price
                ),
                "price_with_discount": (
                    product_data.sale_price
                ),
                "stock": (
                    product_data.stock
                ),
                "selected_assets": [
                    {
                        "asset_type": (
                            selected.asset
                            .asset_type
                        ),
                        "position": (
                            selected.asset
                            .position
                        ),
                        "use_as_primary": (
                            selected.is_primary
                        ),
                    }
                    for selected
                    in selected_assets
                ],
                "options": self._build_options(
                    colors=tuple(
                        product_data.colors
                        or []
                    ),
                    sizes=tuple(
                        product_data.sizes
                        or []
                    ),
                ),
                "variants": [],
            },
        }

    @staticmethod
    def _build_options(
        *,
        colors: tuple[str, ...],
        sizes: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        options: list[
            dict[str, Any]
        ] = []

        normalized_colors = (
            SeloraPayloadMapper
            ._normalize_values(
                colors
            )
        )
        normalized_sizes = (
            SeloraPayloadMapper
            ._normalize_values(
                sizes
            )
        )

        if normalized_colors:
            options.append(
                {
                    "kind": "color",
                    "name": "رنگ",
                    "position": 0,
                    "values": [
                        {
                            "value": value,
                            "position": position,
                        }
                        for position, value
                        in enumerate(
                            normalized_colors
                        )
                    ],
                }
            )

        if normalized_sizes:
            options.append(
                {
                    "kind": "size",
                    "name": "سایز",
                    "position": len(
                        options
                    ),
                    "values": [
                        {
                            "value": value,
                            "position": position,
                        }
                        for position, value
                        in enumerate(
                            normalized_sizes
                        )
                    ],
                }
            )

        return options

    @staticmethod
    def _normalize_values(
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized: list[
            str
        ] = []
        seen: set[
            str
        ] = set()

        for raw_value in values:
            value = (
                raw_value.strip()
            )
            key = (
                value.casefold()
            )

            if (
                not value
                or key in seen
            ):
                continue

            seen.add(
                key
            )
            normalized.append(
                value
            )

        return tuple(
            normalized
        )
