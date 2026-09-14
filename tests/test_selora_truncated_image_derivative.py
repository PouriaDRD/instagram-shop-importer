from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.selora_media_derivative_service import (
    SeloraMediaDerivativeService,
)


def test_prepare_webp_accepts_slightly_truncated_jpeg(
    tmp_path: Path,
):
    source = tmp_path / "source.jpg"

    image = Image.new(
        "RGB",
        (600, 400),
        (120, 80, 40),
    )

    image.save(
        source,
        format="JPEG",
        quality=90,
    )

    data = source.read_bytes()

    # Simulate the same class of slightly incomplete
    # Instagram CDN file observed in production.
    source.write_bytes(data[:-4])

    service = SeloraMediaDerivativeService()

    result = service.prepare_webp(
        source_path=source,
        source_sha256="test-truncated-jpeg",
    )

    assert result.file_path.is_file()
    assert result.file_path.stat().st_size > 0
    assert result.content_type == "image/webp"

    with Image.open(result.file_path) as generated:
        generated.load()

        assert generated.format == "WEBP"
        assert generated.width == 600
        assert generated.height == 400
