from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4


class ClientInstanceIdentityError(RuntimeError):
    pass


class ClientInstanceIdentityService:
    """
    Stable UUID for one local importer installation/computer.

    The id is intentionally not tied to a workspace or Instagram account.
    """

    def __init__(
        self,
        *,
        path: str,
    ) -> None:
        normalized = path.strip()

        if not normalized:
            raise ClientInstanceIdentityError(
                "CLIENT_INSTANCE_ID_FILE cannot be empty."
            )

        self._path = Path(
            normalized
        ).expanduser()

    def get_or_create(self) -> str:
        existing = self._read_existing()

        if existing is not None:
            return str(existing)

        generated = uuid4()

        try:
            self._path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self._path.write_text(
                f"{generated}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ClientInstanceIdentityError(
                (
                    "Could not persist the local "
                    "client instance identity."
                )
            ) from exc

        return str(generated)

    def _read_existing(
        self,
    ) -> UUID | None:
        try:
            raw = self._path.read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ClientInstanceIdentityError(
                (
                    "Could not read the local "
                    "client instance identity."
                )
            ) from exc

        if not raw:
            return None

        try:
            return UUID(
                raw
            )
        except ValueError as exc:
            raise ClientInstanceIdentityError(
                (
                    "Stored client instance identity "
                    "is not a valid UUID."
                )
            ) from exc
