from __future__ import annotations

from dataclasses import dataclass

from app.integrations.selora.client import (
    SeloraApiClient,
    SeloraImportResult,
)
from app.integrations.selora.payload_mapper import (
    SeloraPayloadMapper,
)
from app.models import CrawlSession
from app.models.import_draft import ImportDraft


@dataclass(frozen=True, slots=True)
class SeloraImportService:
    client: SeloraApiClient
    mapper: SeloraPayloadMapper

    def send(
        self,
        *,
        draft: ImportDraft,
        crawl_session: CrawlSession,
        client_instance_id: str,
    ) -> SeloraImportResult:
        payload = (
            self.mapper
            .build_import_payload(
                draft=draft,
                crawl_session=crawl_session,
                client_instance_id=client_instance_id,
            )
        )

        return self.client.send_import(
            payload=payload,
            request_id=draft.id,
        )
