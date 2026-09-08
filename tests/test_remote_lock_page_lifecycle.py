from __future__ import annotations

from pathlib import Path


TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "templates"
)


def test_import_review_does_not_release_lock_on_pagehide() -> None:
    content = (
        TEMPLATE_ROOT
        / "import_review.html"
    ).read_text(
        encoding="utf-8"
    )

    assert "navigator.sendBeacon" not in content
    assert "pagehide" not in content


def test_final_review_does_not_release_lock_on_pagehide() -> None:
    content = (
        TEMPLATE_ROOT
        / "import_final_review.html"
    ).read_text(
        encoding="utf-8"
    )

    assert "navigator.sendBeacon" not in content
    assert "pagehide" not in content
