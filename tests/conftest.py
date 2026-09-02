from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import Config
from app.extensions import db


@pytest.fixture()
def app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Flask]:
    database_path = tmp_path / "test_importer.sqlite3"

    database_uri = "sqlite:///" f"{database_path.as_posix()}"

    monkeypatch.setattr(
        Config,
        "SQLALCHEMY_DATABASE_URI",
        database_uri,
    )

    monkeypatch.setattr(
        Config,
        "DEBUG",
        False,
    )

    application = create_app()

    application.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=False,
    )

    with application.app_context():
        db.drop_all()
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(
    app: Flask,
) -> FlaskClient:
    return app.test_client()
