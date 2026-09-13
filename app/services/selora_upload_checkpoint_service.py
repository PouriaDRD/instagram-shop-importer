from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any


@dataclass(frozen=True, slots=True)
class SeloraUploadCheckpointService:
    root_path: Path = Path("instance/upload_checkpoints")

    def _path_for(
        self,
        *,
        draft_id: str,
    ) -> Path:
        safe_draft_id = "".join(
            character
            if (
                character.isalnum()
                or character in {"-", "_"}
            )
            else "_"
            for character in draft_id.strip()
        )

        return (
            self.root_path
            / f"{safe_draft_id}.json"
        ).resolve()

    def load(
        self,
        *,
        draft_id: str,
        workspace_id: str,
    ) -> dict[str, dict[str, Any]]:
        path = self._path_for(
            draft_id=draft_id,
        )

        if not path.is_file():
            return {}

        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            ValueError,
            TypeError,
        ):
            return {}

        if not isinstance(raw, dict):
            return {}

        if (
            raw.get("workspace_id")
            != workspace_id
        ):
            return {}

        assets = raw.get("assets")

        if not isinstance(
            assets,
            dict,
        ):
            return {}

        return {
            str(key): value
            for key, value
            in assets.items()
            if isinstance(value, dict)
        }

    def is_uploaded(
        self,
        *,
        checkpoint: dict[str, dict[str, Any]],
        asset_key: str,
        sha256: str,
    ) -> bool:
        item = checkpoint.get(
            asset_key
        )

        if not isinstance(
            item,
            dict,
        ):
            return False

        return (
            item.get("sha256")
            == sha256
        )

    def mark_uploaded(
        self,
        *,
        draft_id: str,
        workspace_id: str,
        checkpoint: dict[str, dict[str, Any]],
        asset_key: str,
        sha256: str,
        request_id: str,
    ) -> None:
        checkpoint[
            asset_key
        ] = {
            "sha256": sha256,
            "request_id": request_id,
            "uploaded_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        existing_status = self.read_status(
            draft_id=draft_id,
        )

        payload = {
            "version": 1,
            "draft_id": draft_id,
            "workspace_id": workspace_id,
            "assets": checkpoint,
            "progress": {
                "status": existing_status["status"],
                "total": existing_status["total"],
                "current": existing_status["current"],
                "current_media_id": (
                    existing_status[
                        "current_media_id"
                    ]
                ),
                "current_asset_type": (
                    existing_status[
                        "current_asset_type"
                    ]
                ),
                "error": existing_status["error"],
                "updated_at": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
            },
        }

        self._write_payload(
            draft_id=draft_id,
            payload=payload,
        )

    def read_status(
        self,
        *,
        draft_id: str,
    ) -> dict[str, Any]:
        path = self._path_for(
            draft_id=draft_id,
        )

        if not path.is_file():
            return {
                "status": "idle",
                "total": 0,
                "completed": 0,
                "remaining": 0,
                "current": 0,
                "current_media_id": "",
                "current_asset_type": "",
                "error": "",
            }

        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            ValueError,
            TypeError,
        ):
            return {
                "status": "idle",
                "total": 0,
                "completed": 0,
                "remaining": 0,
                "current": 0,
                "current_media_id": "",
                "current_asset_type": "",
                "error": "",
            }

        if not isinstance(
            raw,
            dict,
        ):
            return {
                "status": "idle",
                "total": 0,
                "completed": 0,
                "remaining": 0,
                "current": 0,
                "current_media_id": "",
                "current_asset_type": "",
                "error": "",
            }

        progress = raw.get(
            "progress"
        )

        if not isinstance(
            progress,
            dict,
        ):
            progress = {}

        assets = raw.get(
            "assets"
        )

        completed = (
            len(assets)
            if isinstance(assets, dict)
            else 0
        )

        total = progress.get(
            "total",
            completed,
        )

        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
        ):
            total = completed

        completed = min(
            completed,
            total,
        ) if total else completed

        return {
            "status": str(
                progress.get(
                    "status",
                    "idle",
                )
                or "idle"
            ),
            "total": total,
            "completed": completed,
            "remaining": max(
                total - completed,
                0,
            ),
            "current": int(
                progress.get(
                    "current",
                    0,
                )
                or 0
            ),
            "current_media_id": str(
                progress.get(
                    "current_media_id",
                    "",
                )
                or ""
            ),
            "current_asset_type": str(
                progress.get(
                    "current_asset_type",
                    "",
                )
                or ""
            ),
            "error": str(
                progress.get(
                    "error",
                    "",
                )
                or ""
            ),
        }

    def update_progress(
        self,
        *,
        draft_id: str,
        workspace_id: str,
        checkpoint: dict[str, dict[str, Any]],
        status: str,
        total: int,
        current: int = 0,
        current_media_id: str = "",
        current_asset_type: str = "",
        error: str = "",
    ) -> None:
        payload = {
            "version": 1,
            "draft_id": draft_id,
            "workspace_id": workspace_id,
            "assets": checkpoint,
            "progress": {
                "status": status,
                "total": int(total),
                "current": int(current),
                "current_media_id": (
                    current_media_id
                ),
                "current_asset_type": (
                    current_asset_type
                ),
                "error": error,
                "updated_at": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
            },
        }

        self._write_payload(
            draft_id=draft_id,
            payload=payload,
        )

    def _write_payload(
        self,
        *,
        draft_id: str,
        payload: dict[str, Any],
    ) -> None:
        path = self._path_for(
            draft_id=draft_id,
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            prefix=f"{path.stem}.",
            dir=path.parent,
            delete=False,
        )

        temporary_path = Path(
            temp_file.name
        )

        try:
            with temp_file:
                temp_file.write(
                    serialized
                )
                temp_file.flush()

                try:
                    os.fsync(
                        temp_file.fileno()
                    )
                except OSError:
                    pass

            last_error: PermissionError | None = None

            for attempt in range(6):
                try:
                    os.replace(
                        temporary_path,
                        path,
                    )
                    last_error = None
                    break

                except PermissionError as exc:
                    last_error = exc
                    time.sleep(
                        0.05
                        * (attempt + 1)
                    )

            if last_error is not None:
                raise last_error

        finally:
            if temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def asset_key(
        *,
        instagram_media_id: str,
        asset_type: str,
        position: int,
    ) -> str:
        return (
            f"{instagram_media_id}"
            f"|{asset_type}"
            f"|{int(position)}"
        )
