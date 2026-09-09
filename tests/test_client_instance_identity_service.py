from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.services.client_instance_identity_service import (
    ClientInstanceIdentityService,
)


def test_client_instance_id_is_stable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "client-id"

    service = ClientInstanceIdentityService(
        path=str(path)
    )

    first = service.get_or_create()
    second = service.get_or_create()

    assert first == second
    assert UUID(first)
