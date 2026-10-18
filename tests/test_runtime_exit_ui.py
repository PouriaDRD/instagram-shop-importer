"""Safe exit is available in the desktop runtime, not bare Flask test apps."""

from flask import Flask
from flask.testing import FlaskClient

from app.runtime_shutdown import SafeShutdownController


def test_non_desktop_app_renders_without_dead_exit_link(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/system/exit" not in html
    assert 'name="token"' not in html


def test_desktop_runtime_exposes_exit_and_rejects_invalid_token(app: Flask) -> None:
    controller = SafeShutdownController(app=app)
    controller.install()
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/system/exit' in html
    assert 'name="token"' in html
    assert "runtime_safe_exit" in app.view_functions

    bad_request = client.post("/system/exit", data={"token": "incorrect"})
    assert bad_request.status_code == 403
    assert not controller._shutting_down
