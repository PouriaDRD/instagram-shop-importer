from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Final
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from app.common.exceptions import (
    InstagramAuthenticationRequiredError,
    InstagramFetchTimeoutError,
    InstagramMediaFetchError,
    InstagramPrivateProfileError,
    InstagramProfileNotFoundError,
    InstagramProfileUnavailableError,
    InstagramProviderError,
    InstagramRateLimitedError,
)
from app.config import Config
from app.crawler.instagram.dto import (
    InstagramAssetDTO,
    InstagramAssetType,
    InstagramMediaDTO,
    InstagramMediaType,
    InstagramProfileDTO,
)

logger = logging.getLogger("crawler")


INSTAGRAM_BASE_URL: Final[str] = "https://www.instagram.com"

DEFAULT_VIEWPORT_WIDTH: Final[int] = 1440
DEFAULT_VIEWPORT_HEIGHT: Final[int] = 1000

PROFILE_SETTLE_MS: Final[int] = 2500
MEDIA_SETTLE_MS: Final[int] = 1800
SCROLL_SETTLE_MS: Final[int] = 800

MAX_SCROLL_ROUNDS: Final[int] = 80


class PlaywrightInstagramProvider:
    """
    Instagram crawler based on Playwright.

    Responsibilities:
    - Fetch public Instagram profile metadata.
    - Discover posts and reels from a profile.
    - Fetch individual media pages.
    - Extract Instagram embedded structured JSON.
    - Detect image, video, reel and carousel media.
    - Build validated DTO objects.

    This provider intentionally has no dependency on:
    - Flask
    - SQLAlchemy
    - Selora
    - Django
    """

    def __init__(
        self,
        *,
        headless: bool | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        self._headless = Config.PLAYWRIGHT_HEADLESS if headless is None else headless

        self._timeout_ms = (
            Config.PLAYWRIGHT_TIMEOUT_MS if timeout_ms is None else timeout_ms
        )

    # =========================================================
    # Public API
    # =========================================================

    def fetch_profile(
        self,
        *,
        username: str,
    ) -> InstagramProfileDTO:
        normalized_username = self._normalize_username(username)

        logger.info(
            "Fetching profile @%s",
            normalized_username,
        )

        try:
            with self._browser_context() as context:
                page = context.new_page()

                profile = self._fetch_profile_from_page(
                    page=page,
                    username=normalized_username,
                )

        except PlaywrightTimeoutError as exc:
            raise InstagramFetchTimeoutError(
                ("Instagram profile request timed out " f"for @{normalized_username}")
            ) from exc

        logger.info(
            "Profile fetched @%s",
            normalized_username,
        )

        return profile

    def fetch_media(
        self,
        *,
        username: str,
        max_items: int | None = None,
    ) -> tuple[InstagramMediaDTO, ...]:
        normalized_username = self._normalize_username(username)

        if max_items is not None and max_items <= 0:
            return ()

        logger.info(
            "Discovering media for @%s",
            normalized_username,
        )

        try:
            with self._browser_context() as context:
                page = context.new_page()

                media_urls = self._discover_media_urls(
                    page=page,
                    username=normalized_username,
                    max_items=max_items,
                )

                logger.info(
                    "Found %s media for @%s",
                    len(media_urls),
                    normalized_username,
                )

                media_items: list[InstagramMediaDTO] = []

                for index, media_url in enumerate(
                    media_urls,
                    start=1,
                ):
                    shortcode = self._shortcode_from_url(media_url)

                    logger.info(
                        "Fetching media %s/%s: %s",
                        index,
                        len(media_urls),
                        shortcode,
                    )

                    try:
                        media = self._fetch_media_detail(
                            page=page,
                            media_url=media_url,
                        )

                    except InstagramMediaFetchError:
                        logger.exception(
                            "Failed to fetch media %s",
                            shortcode,
                        )

                        continue

                    media_items.append(media)

        except PlaywrightTimeoutError as exc:
            raise InstagramFetchTimeoutError(
                ("Instagram media discovery timed out " f"for @{normalized_username}")
            ) from exc

        return tuple(media_items)

    # =========================================================
    # Browser lifecycle
    # =========================================================

    @contextmanager
    def _browser_context(
        self,
    ) -> Iterator[BrowserContext]:
        playwright: Playwright | None = None
        browser: Browser | None = None
        context: BrowserContext | None = None

        try:
            playwright = sync_playwright().start()

            browser = playwright.chromium.launch(
                headless=self._headless,
            )

            context = browser.new_context(
                locale="en-US",
                viewport={
                    "width": DEFAULT_VIEWPORT_WIDTH,
                    "height": DEFAULT_VIEWPORT_HEIGHT,
                },
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0.0.0 "
                    "Safari/537.36"
                ),
            )

            context.set_default_timeout(self._timeout_ms)

            yield context

        except PlaywrightTimeoutError:
            raise

        except Exception as exc:
            raise InstagramProviderError(
                ("Failed to initialize " "Instagram browser session.")
            ) from exc

        finally:
            if context is not None:
                context.close()

            if browser is not None:
                browser.close()

            if playwright is not None:
                playwright.stop()

    # =========================================================
    # Profile
    # =========================================================

    def _fetch_profile_from_page(
        self,
        *,
        page: Page,
        username: str,
    ) -> InstagramProfileDTO:
        profile_url = f"{INSTAGRAM_BASE_URL}/" f"{username}/"

        response = page.goto(
            profile_url,
            wait_until="domcontentloaded",
            timeout=self._timeout_ms,
        )

        page.wait_for_timeout(PROFILE_SETTLE_MS)

        self._validate_profile_page(
            page=page,
            username=username,
            status_code=(response.status if response is not None else None),
        )

        payload = self._extract_profile_payload(
            page=page,
            username=username,
        )

        if payload is not None:
            return self._profile_dto_from_payload(
                username=username,
                payload=payload,
            )

        return self._profile_dto_from_metadata(
            page=page,
            username=username,
        )

    def _validate_profile_page(
        self,
        *,
        page: Page,
        username: str,
        status_code: int | None,
    ) -> None:
        body = page.locator("body").inner_text().strip()

        body_lower = body.lower()

        if status_code == 429:
            raise InstagramRateLimitedError("Instagram rate limit reached.")

        not_found_markers = (
            "sorry, this page isn't available",
            "profile isn't available",
            "page isn't available",
            "the link you followed may be broken",
        )

        if any(marker in body_lower for marker in not_found_markers):
            raise InstagramProfileNotFoundError(
                ("Instagram profile was not found: " f"@{username}")
            )

        private_markers = (
            "this account is private",
            "this profile is private",
        )

        if any(marker in body_lower for marker in private_markers):
            raise InstagramPrivateProfileError(
                ("Instagram profile is private: " f"@{username}")
            )

        authentication_markers = (
            "log in to instagram",
            "sign up to see photos",
        )

        if not self._has_profile_content(page) and any(
            marker in body_lower for marker in authentication_markers
        ):
            raise InstagramAuthenticationRequiredError(
                ("Instagram authentication is required " f"for @{username}")
            )

        unavailable_markers = (
            "something went wrong",
            "please try again later",
        )

        if any(marker in body_lower for marker in unavailable_markers):
            raise InstagramProfileUnavailableError(
                ("Instagram profile is temporarily unavailable: " f"@{username}")
            )

    def _has_profile_content(
        self,
        page: Page,
    ) -> bool:
        return page.locator('a[href*="/p/"], ' 'a[href*="/reel/"]').count() > 0

    def _extract_profile_payload(
        self,
        *,
        page: Page,
        username: str,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []

        scripts = page.locator("script")

        for index in range(scripts.count()):
            text = scripts.nth(index).text_content() or ""

            if username not in text:
                continue

            parsed = self._parse_json_script(text)

            if parsed is None:
                continue

            for node in self._walk_json(parsed):
                if not isinstance(
                    node,
                    dict,
                ):
                    continue

                node_username = node.get("username")

                if (
                    isinstance(
                        node_username,
                        str,
                    )
                    and node_username.lower() == username.lower()
                ):
                    candidates.append(node)

        if not candidates:
            return None

        return max(
            candidates,
            key=self._profile_payload_score,
        )

    @staticmethod
    def _profile_payload_score(
        payload: dict[str, Any],
    ) -> int:
        score = 0

        weighted_fields = {
            "full_name": 10,
            "biography": 15,
            "profile_pic_url": 10,
            "profile_pic_url_hd": 15,
            "follower_count": 10,
            "following_count": 8,
            "media_count": 8,
            "is_private": 5,
            "pk": 5,
        }

        for field, weight in weighted_fields.items():
            value = payload.get(field)

            if value not in (
                None,
                "",
                [],
                {},
            ):
                score += weight

        return score

    def _profile_dto_from_payload(
        self,
        *,
        username: str,
        payload: dict[str, Any],
    ) -> InstagramProfileDTO:
        profile_picture_url = self._first_string(
            payload,
            (
                "profile_pic_url_hd",
                "profile_pic_url",
                "profile_picture_url",
            ),
        )

        return InstagramProfileDTO(
            username=username,
            full_name=self._as_string(payload.get("full_name")),
            biography=self._as_string(payload.get("biography")),
            profile_picture_url=(profile_picture_url or None),
            followers_count=self._first_int(
                payload,
                (
                    "follower_count",
                    "followers_count",
                ),
            ),
            following_count=self._first_int(
                payload,
                (
                    "following_count",
                    "follow_count",
                ),
            ),
            media_count=self._first_int(
                payload,
                (
                    "media_count",
                    "post_count",
                ),
            ),
            is_private=self._as_optional_bool(payload.get("is_private")),
            raw_payload=payload,
        )

    def _profile_dto_from_metadata(
        self,
        *,
        page: Page,
        username: str,
    ) -> InstagramProfileDTO:
        description = (
            self._meta_content(
                page,
                'meta[property="og:description"]',
            )
            or ""
        )

        image = self._meta_content(
            page,
            'meta[property="og:image"]',
        )

        title = self._meta_content(
            page,
            'meta[property="og:title"]',
        )

        full_name = ""

        if title:
            full_name = title.split(
                "(@",
                maxsplit=1,
            )[0].strip()

        followers_count = self._extract_compact_count(
            description,
            "Followers",
        )

        following_count = self._extract_compact_count(
            description,
            "Following",
        )

        media_count = self._extract_compact_count(
            description,
            "Posts",
        )

        return InstagramProfileDTO(
            username=username,
            full_name=full_name,
            biography="",
            profile_picture_url=(image or None),
            followers_count=followers_count,
            following_count=following_count,
            media_count=media_count,
            is_private=None,
            raw_payload={
                "og:title": title,
                "og:description": description,
                "og:image": image,
            },
        )

    # =========================================================
    # Media discovery
    # =========================================================

    def _discover_media_urls(
        self,
        *,
        page: Page,
        username: str,
        max_items: int | None,
    ) -> tuple[str, ...]:
        profile_url = f"{INSTAGRAM_BASE_URL}/" f"{username}/"

        page.goto(
            profile_url,
            wait_until="domcontentloaded",
            timeout=self._timeout_ms,
        )

        page.wait_for_timeout(PROFILE_SETTLE_MS)

        self._validate_profile_page(
            page=page,
            username=username,
            status_code=None,
        )

        discovered: list[str] = []
        discovered_set: set[str] = set()

        unchanged_rounds = 0
        previous_count = 0

        for _ in range(MAX_SCROLL_ROUNDS):
            self._collect_media_links(
                page=page,
                result=discovered,
                seen=discovered_set,
            )

            if max_items is not None and len(discovered) >= max_items:
                break

            if len(discovered) == previous_count:
                unchanged_rounds += 1

            else:
                unchanged_rounds = 0
                previous_count = len(discovered)

            if unchanged_rounds >= 3:
                break

            page.evaluate("""
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                )
                """)

            page.wait_for_timeout(SCROLL_SETTLE_MS)

        if max_items is not None:
            discovered = discovered[:max_items]

        return tuple(discovered)

    def _collect_media_links(
        self,
        *,
        page: Page,
        result: list[str],
        seen: set[str],
    ) -> None:
        anchors = page.locator('a[href*="/p/"], ' 'a[href*="/reel/"]')

        for index in range(anchors.count()):
            href = anchors.nth(index).get_attribute("href")

            if not href:
                continue

            normalized = self._normalize_media_url(href)

            if normalized is None:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)

            result.append(normalized)

    # =========================================================
    # Media details
    # =========================================================

    def _fetch_media_detail(
        self,
        *,
        page: Page,
        media_url: str,
    ) -> InstagramMediaDTO:
        shortcode = self._shortcode_from_url(media_url)

        try:
            response = page.goto(
                media_url,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )

            page.wait_for_timeout(MEDIA_SETTLE_MS)

            if response is not None and response.status == 429:
                raise InstagramRateLimitedError("Instagram rate limit reached.")

            payload = self._extract_embedded_media_payload(
                page=page,
                shortcode=shortcode,
            )

            if payload is not None:
                return self._media_dto_from_payload(
                    payload=payload,
                    media_url=media_url,
                    shortcode=shortcode,
                )

            return self._media_dto_from_metadata(
                page=page,
                media_url=media_url,
                shortcode=shortcode,
            )

        except InstagramRateLimitedError:
            raise

        except PlaywrightTimeoutError as exc:
            raise InstagramMediaFetchError(
                ("Instagram media request timed out: " f"{shortcode}")
            ) from exc

        except InstagramMediaFetchError:
            raise

        except Exception as exc:
            raise InstagramMediaFetchError(
                ("Failed to extract Instagram media: " f"{shortcode}")
            ) from exc

    # =========================================================
    # Embedded Instagram JSON extraction
    # =========================================================

    def _extract_embedded_media_payload(
        self,
        *,
        page: Page,
        shortcode: str,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []

        scripts = page.locator("script")

        for index in range(scripts.count()):
            text = scripts.nth(index).text_content() or ""

            if shortcode not in text:
                continue

            parsed = self._parse_json_script(text)

            if parsed is None:
                continue

            self._collect_media_candidates(
                value=parsed,
                shortcode=shortcode,
                candidates=candidates,
            )

        if not candidates:
            return None

        best_candidate = max(
            candidates,
            key=self._media_payload_score,
        )

        return self._normalize_media_payload(
            payload=best_candidate,
            shortcode=shortcode,
        )

    def _collect_media_candidates(
        self,
        *,
        value: Any,
        shortcode: str,
        candidates: list[dict[str, Any]],
    ) -> bool:
        """
        Recursively find media candidates.

        Instagram can place carousel_media, video_versions or other
        important fields on a parent structure instead of directly on
        the dict whose `code` equals the shortcode.

        Returns True when the current subtree contains the requested
        shortcode.
        """

        if isinstance(
            value,
            dict,
        ):
            node_matches = value.get("code") == shortcode

            child_matches = False

            for child in value.values():
                if self._collect_media_candidates(
                    value=child,
                    shortcode=shortcode,
                    candidates=candidates,
                ):
                    child_matches = True

            subtree_matches = node_matches or child_matches

            if node_matches:
                candidates.append(value)

            if child_matches and self._is_useful_media_wrapper(value):
                candidates.append(value)

            return subtree_matches

        if isinstance(
            value,
            list,
        ):
            contains_shortcode = False

            for child in value:
                if self._collect_media_candidates(
                    value=child,
                    shortcode=shortcode,
                    candidates=candidates,
                ):
                    contains_shortcode = True

            return contains_shortcode

        return False

    @staticmethod
    def _is_useful_media_wrapper(
        payload: dict[str, Any],
    ) -> bool:
        useful_fields = {
            "carousel_media",
            "image_versions2",
            "video_versions",
            "caption",
            "taken_at",
            "media_type",
            "product_type",
            "display_uri",
            "like_count",
            "comment_count",
            "view_count",
            "play_count",
            "pk",
        }

        return any(field in payload for field in useful_fields)

    @staticmethod
    def _media_payload_score(
        payload: dict[str, Any],
    ) -> int:
        score = 0

        weighted_fields = {
            "carousel_media": 100,
            "video_versions": 50,
            "image_versions2": 35,
            "taken_at": 25,
            "caption": 20,
            "display_uri": 10,
            "like_count": 10,
            "comment_count": 10,
            "view_count": 10,
            "play_count": 10,
            "original_width": 5,
            "original_height": 5,
            "product_type": 5,
            "media_type": 5,
            "user": 5,
            "pk": 5,
        }

        for field, weight in weighted_fields.items():
            value = payload.get(field)

            if value not in (
                None,
                "",
                [],
                {},
            ):
                score += weight

        carousel_media = payload.get("carousel_media")

        if isinstance(
            carousel_media,
            list,
        ):
            score += (
                min(
                    len(carousel_media),
                    20,
                )
                * 5
            )

        return score

    def _normalize_media_payload(
        self,
        *,
        payload: dict[str, Any],
        shortcode: str,
    ) -> dict[str, Any]:
        """
        Normalize parent/wrapper and shortcode-specific media data.

        The actual shortcode node is used as the base because it usually
        contains caption, counts and identity.

        Rich parent structures then supplement fields such as
        carousel_media or video_versions.
        """

        media_node = self._find_shortcode_node(
            payload,
            shortcode=shortcode,
        )

        if media_node is None:
            return payload

        normalized = dict(media_node)

        for key, value in payload.items():
            current_value = normalized.get(key)

            if current_value in (
                None,
                "",
                [],
                {},
            ):
                normalized[key] = value

        rich_wrapper_fields = (
            "carousel_media",
            "video_versions",
        )

        for key in rich_wrapper_fields:
            wrapper_value = payload.get(key)

            if wrapper_value not in (
                None,
                "",
                [],
                {},
            ):
                normalized[key] = wrapper_value

        if "image_versions2" not in normalized or not normalized.get("image_versions2"):
            wrapper_images = payload.get("image_versions2")

            if wrapper_images:
                normalized["image_versions2"] = wrapper_images

        return normalized

    def _find_shortcode_node(
        self,
        value: Any,
        *,
        shortcode: str,
    ) -> dict[str, Any] | None:
        if isinstance(
            value,
            dict,
        ):
            if value.get("code") == shortcode:
                return value

            for child in value.values():
                match = self._find_shortcode_node(
                    child,
                    shortcode=shortcode,
                )

                if match is not None:
                    return match

        elif isinstance(
            value,
            list,
        ):
            for child in value:
                match = self._find_shortcode_node(
                    child,
                    shortcode=shortcode,
                )

                if match is not None:
                    return match

        return None

    # =========================================================
    # DTO construction
    # =========================================================

    def _media_dto_from_payload(
        self,
        *,
        payload: dict[str, Any],
        media_url: str,
        shortcode: str,
    ) -> InstagramMediaDTO:
        media_type = self._detect_media_type(
            payload=payload,
            media_url=media_url,
        )

        caption = self._extract_caption(payload)

        published_at = self._datetime_from_unix(payload.get("taken_at"))

        thumbnail_url = self._best_image_url(payload)

        assets = self._build_assets_from_payload(
            payload=payload,
        )

        media_id = (
            self._as_string(payload.get("pk"))
            or self._as_string(payload.get("id"))
            or shortcode
        )

        view_count = self._first_int(
            payload,
            (
                "view_count",
                "play_count",
                "video_view_count",
            ),
        )

        return InstagramMediaDTO(
            media_id=media_id,
            shortcode=shortcode,
            media_type=media_type,
            permalink=media_url,
            caption=caption,
            thumbnail_url=(thumbnail_url or None),
            published_at=published_at,
            like_count=self._as_optional_int(payload.get("like_count")),
            comment_count=self._as_optional_int(payload.get("comment_count")),
            view_count=view_count,
            assets=assets,
            raw_payload=payload,
        )

    def _detect_media_type(
        self,
        *,
        payload: dict[str, Any],
        media_url: str,
    ) -> InstagramMediaType:
        carousel_media = payload.get("carousel_media")

        if (
            isinstance(
                carousel_media,
                list,
            )
            and carousel_media
        ):
            return InstagramMediaType.CAROUSEL

        product_type = self._as_string(payload.get("product_type")).lower()

        media_type_number = self._as_optional_int(payload.get("media_type"))

        if "/reel/" in media_url or product_type in {
            "clips",
            "reels",
            "reel",
        }:
            return InstagramMediaType.REEL

        if media_type_number == 2:
            return InstagramMediaType.VIDEO

        if media_type_number == 1:
            return InstagramMediaType.IMAGE

        return InstagramMediaType.UNKNOWN

    # =========================================================
    # Asset extraction
    # =========================================================

    def _build_assets_from_payload(
        self,
        *,
        payload: dict[str, Any],
    ) -> tuple[InstagramAssetDTO, ...]:
        assets: list[InstagramAssetDTO] = []

        carousel_media = payload.get("carousel_media")

        if (
            isinstance(
                carousel_media,
                list,
            )
            and carousel_media
        ):
            for position, child in enumerate(carousel_media):
                if not isinstance(
                    child,
                    dict,
                ):
                    continue

                self._append_media_node_assets(
                    assets=assets,
                    node=child,
                    position=position,
                    carousel_child=True,
                )

            return tuple(assets)

        self._append_media_node_assets(
            assets=assets,
            node=payload,
            position=0,
            carousel_child=False,
        )

        return tuple(assets)

    def _append_media_node_assets(
        self,
        *,
        assets: list[InstagramAssetDTO],
        node: dict[str, Any],
        position: int,
        carousel_child: bool,
    ) -> None:
        media_pk = self._as_string(node.get("pk")) or self._as_string(node.get("id"))

        media_type_number = self._as_optional_int(node.get("media_type"))

        image_candidate = self._best_image_candidate(node)

        if image_candidate is not None:
            image_url = self._as_string(image_candidate.get("url"))

            if image_url:
                asset_type = (
                    InstagramAssetType.THUMBNAIL
                    if media_type_number == 2
                    else InstagramAssetType.IMAGE
                )

                assets.append(
                    InstagramAssetDTO(
                        external_id=media_pk,
                        asset_type=asset_type,
                        source_url=image_url,
                        position=position,
                        width=self._as_optional_int(image_candidate.get("width")),
                        height=self._as_optional_int(image_candidate.get("height")),
                        metadata={
                            "instagram_media_pk": media_pk,
                            "carousel_child": carousel_child,
                        },
                    )
                )

        video_candidate = self._best_video_candidate(node)

        if video_candidate is not None:
            video_url = self._as_string(video_candidate.get("url"))

            if video_url:
                assets.append(
                    InstagramAssetDTO(
                        external_id=media_pk,
                        asset_type=(InstagramAssetType.VIDEO),
                        source_url=video_url,
                        position=position,
                        width=self._as_optional_int(video_candidate.get("width")),
                        height=self._as_optional_int(video_candidate.get("height")),
                        duration_seconds=(
                            self._as_optional_float(node.get("video_duration"))
                        ),
                        metadata={
                            "instagram_media_pk": media_pk,
                            "carousel_child": carousel_child,
                        },
                    )
                )

    def _best_image_candidate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        image_versions = payload.get("image_versions2")

        if isinstance(
            image_versions,
            dict,
        ):
            candidates = image_versions.get("candidates")

            if isinstance(
                candidates,
                list,
            ):
                valid_candidates = [
                    candidate
                    for candidate in candidates
                    if isinstance(
                        candidate,
                        dict,
                    )
                    and candidate.get("url")
                ]

                if valid_candidates:
                    return max(
                        valid_candidates,
                        key=self._candidate_area,
                    )

        display_uri = self._as_string(payload.get("display_uri"))

        if display_uri:
            return {
                "url": display_uri,
                "width": payload.get("original_width"),
                "height": payload.get("original_height"),
            }

        return None

    def _best_image_url(
        self,
        payload: dict[str, Any],
    ) -> str:
        candidate = self._best_image_candidate(payload)

        if candidate is None:
            return ""

        return self._as_string(candidate.get("url"))

    def _best_video_candidate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        candidates = payload.get("video_versions")

        if not isinstance(
            candidates,
            list,
        ):
            return None

        valid_candidates = [
            candidate
            for candidate in candidates
            if isinstance(
                candidate,
                dict,
            )
            and candidate.get("url")
        ]

        if not valid_candidates:
            return None

        return max(
            valid_candidates,
            key=self._candidate_area,
        )

    @staticmethod
    def _candidate_area(
        candidate: dict[str, Any],
    ) -> int:
        width = candidate.get("width")

        height = candidate.get("height")

        if not isinstance(
            width,
            int,
        ):
            width = 0

        if not isinstance(
            height,
            int,
        ):
            height = 0

        return width * height

    # =========================================================
    # Metadata fallback
    # =========================================================

    def _media_dto_from_metadata(
        self,
        *,
        page: Page,
        media_url: str,
        shortcode: str,
    ) -> InstagramMediaDTO:
        og_title = self._meta_content(
            page,
            'meta[property="og:title"]',
        )

        og_description = self._meta_content(
            page,
            'meta[property="og:description"]',
        )

        og_image = self._meta_content(
            page,
            'meta[property="og:image"]',
        )

        caption = self._caption_from_og_title(og_title)

        (
            like_count,
            comment_count,
        ) = self._engagement_from_description(og_description)

        published_at = self._published_at_from_page(page)

        media_type = (
            InstagramMediaType.REEL
            if "/reel/" in media_url
            else InstagramMediaType.IMAGE
        )

        assets: tuple[
            InstagramAssetDTO,
            ...,
        ] = ()

        if og_image:
            assets = (
                InstagramAssetDTO(
                    external_id=shortcode,
                    asset_type=(
                        InstagramAssetType.THUMBNAIL
                        if media_type == InstagramMediaType.REEL
                        else InstagramAssetType.IMAGE
                    ),
                    source_url=og_image,
                    position=0,
                ),
            )

        return InstagramMediaDTO(
            media_id=shortcode,
            shortcode=shortcode,
            media_type=media_type,
            permalink=media_url,
            caption=caption,
            thumbnail_url=(og_image or None),
            published_at=published_at,
            like_count=like_count,
            comment_count=comment_count,
            view_count=None,
            assets=assets,
            raw_payload={
                "og:title": og_title,
                "og:description": og_description,
                "og:image": og_image,
                "fallback": True,
            },
        )

    # =========================================================
    # JSON helpers
    # =========================================================

    @staticmethod
    def _parse_json_script(
        text: str,
    ) -> Any | None:
        stripped = text.strip()

        if not stripped:
            return None

        if not (stripped.startswith("{") or stripped.startswith("[")):
            return None

        try:
            return json.loads(stripped)

        except json.JSONDecodeError:
            return None

    def _walk_json(
        self,
        value: Any,
    ) -> Iterator[Any]:
        yield value

        if isinstance(
            value,
            dict,
        ):
            for child in value.values():
                yield from self._walk_json(child)

        elif isinstance(
            value,
            list,
        ):
            for child in value:
                yield from self._walk_json(child)

    # =========================================================
    # URL helpers
    # =========================================================

    @staticmethod
    def _normalize_username(
        username: str,
    ) -> str:
        normalized = username.strip().lstrip("@").strip("/")

        if not normalized:
            raise ValueError("Instagram username cannot be empty.")

        if "/" in normalized:
            parsed = urlparse(normalized)

            path_parts = [part for part in parsed.path.split("/") if part]

            if path_parts:
                normalized = path_parts[0]

        return normalized

    def _normalize_media_url(
        self,
        href: str,
    ) -> str | None:
        parsed = urlparse(href)

        path = parsed.path if parsed.scheme else href

        path_parts = [part for part in path.split("/") if part]

        route_index: int | None = None

        for index, part in enumerate(path_parts):
            if part in {
                "p",
                "reel",
            }:
                route_index = index
                break

        if route_index is None:
            return None

        if route_index + 1 >= len(path_parts):
            return None

        route = path_parts[route_index]

        shortcode = path_parts[route_index + 1]

        if not shortcode:
            return None

        return f"{INSTAGRAM_BASE_URL}/" f"{route}/" f"{shortcode}/"

    @staticmethod
    def _shortcode_from_url(
        media_url: str,
    ) -> str:
        path_parts = [part for part in urlparse(media_url).path.split("/") if part]

        for index, part in enumerate(path_parts):
            if part in {
                "p",
                "reel",
            } and index + 1 < len(path_parts):
                return path_parts[index + 1]

        raise InstagramMediaFetchError(
            ("Could not determine shortcode from URL: " f"{media_url}")
        )

    # =========================================================
    # Parsing helpers
    # =========================================================

    @staticmethod
    def _extract_caption(
        payload: dict[str, Any],
    ) -> str:
        caption = payload.get("caption")

        if isinstance(
            caption,
            dict,
        ):
            text = caption.get("text")

            if isinstance(
                text,
                str,
            ):
                return text.strip()

        return ""

    @staticmethod
    def _datetime_from_unix(
        value: Any,
    ) -> datetime | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        if isinstance(
            value,
            int | float,
        ):
            try:
                return datetime.fromtimestamp(
                    value,
                    tz=timezone.utc,
                )

            except (
                OverflowError,
                OSError,
                ValueError,
            ):
                return None

        return None

    @staticmethod
    def _meta_content(
        page: Page,
        selector: str,
    ) -> str | None:
        locator = page.locator(selector)

        if locator.count() == 0:
            return None

        content = locator.first.get_attribute("content")

        if content is None:
            return None

        value = content.strip()

        return value if value else None

    @staticmethod
    def _caption_from_og_title(
        title: str | None,
    ) -> str:
        if not title:
            return ""

        match = re.search(
            r'Instagram.*?:\s*"(.+)"',
            title,
        )

        if match:
            return match.group(1).strip()

        first_quote = title.find('"')

        last_quote = title.rfind('"')

        if first_quote >= 0 and last_quote > first_quote:
            return title[first_quote + 1 : last_quote].strip()

        return title.strip()

    def _engagement_from_description(
        self,
        description: str | None,
    ) -> tuple[
        int | None,
        int | None,
    ]:
        if not description:
            return (
                None,
                None,
            )

        like_match = re.search(
            r"([\d,.]+)\s+likes?",
            description,
            flags=re.IGNORECASE,
        )

        comment_match = re.search(
            r"([\d,.]+)\s+comments?",
            description,
            flags=re.IGNORECASE,
        )

        likes = self._parse_number(like_match.group(1)) if like_match else None

        comments = self._parse_number(comment_match.group(1)) if comment_match else None

        return (
            likes,
            comments,
        )

    @staticmethod
    def _published_at_from_page(
        page: Page,
    ) -> datetime | None:
        times = page.locator("time[datetime]")

        if times.count() == 0:
            return None

        values: list[datetime] = []

        for index in range(times.count()):
            raw = times.nth(index).get_attribute("datetime")

            if not raw:
                continue

            try:
                parsed = datetime.fromisoformat(
                    raw.replace(
                        "Z",
                        "+00:00",
                    )
                )

            except ValueError:
                continue

            values.append(parsed)

        if not values:
            return None

        return min(values)

    @staticmethod
    def _extract_compact_count(
        text: str,
        label: str,
    ) -> int | None:
        pattern = rf"([\d,.]+[KMB]?)" rf"\s+{re.escape(label)}"

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        raw = (
            match.group(1)
            .replace(
                ",",
                "",
            )
            .strip()
            .upper()
        )

        multiplier = 1

        if raw.endswith("K"):
            multiplier = 1_000
            raw = raw[:-1]

        elif raw.endswith("M"):
            multiplier = 1_000_000
            raw = raw[:-1]

        elif raw.endswith("B"):
            multiplier = 1_000_000_000
            raw = raw[:-1]

        try:
            return int(float(raw) * multiplier)

        except ValueError:
            return None

    @staticmethod
    def _parse_number(
        raw: str,
    ) -> int | None:
        normalized = raw.replace(
            ",",
            "",
        ).strip()

        try:
            return int(normalized)

        except ValueError:
            return None

    @staticmethod
    def _first_string(
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str:
        for key in keys:
            value = payload.get(key)

            if isinstance(
                value,
                str,
            ):
                value = value.strip()

                if value:
                    return value

        return ""

    def _first_int(
        self,
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> int | None:
        for key in keys:
            value = self._as_optional_int(payload.get(key))

            if value is not None:
                return value

        return None

    @staticmethod
    def _as_string(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        if isinstance(
            value,
            str,
        ):
            return value.strip()

        if isinstance(
            value,
            int | float,
        ) and not isinstance(
            value,
            bool,
        ):
            return str(value)

        return ""

    @staticmethod
    def _as_optional_int(
        value: Any,
    ) -> int | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        if isinstance(
            value,
            int,
        ):
            return value

        if isinstance(
            value,
            float,
        ):
            return int(value)

        if isinstance(
            value,
            str,
        ):
            try:
                return int(value)

            except ValueError:
                return None

        return None

    @staticmethod
    def _as_optional_float(
        value: Any,
    ) -> float | None:
        if isinstance(
            value,
            bool,
        ):
            return None

        if isinstance(
            value,
            int | float,
        ):
            return float(value)

        if isinstance(
            value,
            str,
        ):
            try:
                return float(value)

            except ValueError:
                return None

        return None

    @staticmethod
    def _as_optional_bool(
        value: Any,
    ) -> bool | None:
        if isinstance(
            value,
            bool,
        ):
            return value

        return None
