from __future__ import annotations

from unittest import TestCase
from unittest.mock import Mock, patch

from flask import Flask

from app.routes.web import web_bp


class ImportSuccessRouteTests(TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(web_bp)

    @patch("app.routes.web.ImportDraftRepository")
    @patch("app.routes.web.render_template")
    def test_success_route_reads_result_from_query_string(
        self,
        render_template: Mock,
        repository_class: Mock,
    ) -> None:
        repository = repository_class.return_value

        draft = Mock()
        draft.id = "draft-1"
        draft.crawl_session_id = "crawl-1"
        repository.get.return_value = draft

        render_template.return_value = "ok"

        client = self.app.test_client()

        response = client.get(
            (
                "/draft/draft-1/success"
                "?session_id=session-1"
                "&request_id=req-1"
                "&replayed=1"
                "&draft_count=2"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        render_template.assert_called_once_with(
            "import_success.html",
            draft=draft,
            session_id="session-1",
            request_id="req-1",
            replayed=True,
            draft_count=2,
        )

    @patch("app.routes.web.ImportDraftRepository")
    def test_success_route_returns_404_for_unknown_draft(
        self,
        repository_class: Mock,
    ) -> None:
        repository_class.return_value.get.return_value = None

        client = self.app.test_client()

        response = client.get("/draft/missing/success")

        self.assertEqual(
            response.status_code,
            404,
        )
