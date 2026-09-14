from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

from PIL import Image, ImageFile, ImageOps


logger = logging.getLogger(__name__)


class SeloraMediaDerivativeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SeloraPreparedImage:
    file_path: Path
    content_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SeloraMediaDerivativeService:
    max_dimension: int = 2048
    quality: int = 82
    method: int = 6

    def prepare_webp(
        self,
        *,
        source_path: Path,
        source_sha256: str,
    ) -> SeloraPreparedImage:
        if (
            not source_path.is_file()
            or source_path.stat().st_size <= 0
        ):
            raise SeloraMediaDerivativeError(
                "Source image is missing or empty."
            )

        derivative_dir = (
            source_path.parent
            / ".selora"
        )

        derivative_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            derivative_dir
            / f"{source_sha256}.webp"
        )

        if (
            output_path.is_file()
            and output_path.stat().st_size > 0
        ):
            return SeloraPreparedImage(
                file_path=output_path,
                content_type="image/webp",
                sha256=self._sha256(output_path),
            )

        temporary_path = output_path.with_suffix(
            ".webp.part"
        )

        try:
            try:
                with Image.open(source_path) as source_image:
                    image = ImageOps.exif_transpose(
                        source_image
                    )

                    image.load()

            except OSError as exc:
                if (
                    "image file is truncated"
                    not in str(exc).lower()
                ):
                    raise

                logger.warning(
                    (
                        "Retrying slightly truncated Instagram "
                        "image with tolerant Pillow decoding: "
                        "source=%s error=%s"
                    ),
                    source_path,
                    exc,
                )

                previous_setting = (
                    ImageFile.LOAD_TRUNCATED_IMAGES
                )

                try:
                    ImageFile.LOAD_TRUNCATED_IMAGES = True

                    with Image.open(
                        source_path
                    ) as source_image:
                        image = (
                            ImageOps.exif_transpose(
                                source_image
                            )
                        )

                        image.load()

                finally:
                    ImageFile.LOAD_TRUNCATED_IMAGES = (
                        previous_setting
                    )

            if (
                image.width > self.max_dimension
                or image.height > self.max_dimension
            ):
                image.thumbnail(
                    (
                        self.max_dimension,
                        self.max_dimension,
                    ),
                    Image.Resampling.LANCZOS,
                )

            has_alpha = (
                image.mode in {"RGBA", "LA"}
                or (
                    image.mode == "P"
                    and "transparency"
                    in image.info
                )
            )

            if has_alpha:
                image = image.convert("RGBA")
            else:
                image = image.convert("RGB")

            image.save(
                temporary_path,
                format="WEBP",
                quality=self.quality,
                method=self.method,
                optimize=True,
            )

            if (
                not temporary_path.is_file()
                or temporary_path.stat().st_size <= 0
            ):
                raise SeloraMediaDerivativeError(
                    "Generated WebP image is empty."
                )

            temporary_path.replace(
                output_path
            )

        except Exception as exc:
            logger.exception(
                (
                    "Selora WebP preparation failed: "
                    "source=%s output=%s "
                    "source_exists=%s source_size=%s "
                    "error_type=%s error=%s"
                ),
                source_path,
                output_path,
                source_path.exists(),
                (
                    source_path.stat().st_size
                    if source_path.exists()
                    else None
                ),
                type(exc).__name__,
                exc,
            )

            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

            if isinstance(
                exc,
                SeloraMediaDerivativeError,
            ):
                raise

            raise SeloraMediaDerivativeError(
                (
                    "Could not prepare image for "
                    "Selora upload."
                )
            ) from exc

        return SeloraPreparedImage(
            file_path=output_path,
            content_type="image/webp",
            sha256=self._sha256(output_path),
        )

    @staticmethod
    def _sha256(file_path: Path) -> str:
        digest = hashlib.sha256()

        with file_path.open("rb") as file_handle:
            while True:
                chunk = file_handle.read(
                    64 * 1024
                )

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()
