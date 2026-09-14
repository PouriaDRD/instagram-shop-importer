from __future__ import annotations

import logging

import app.logging_config as logging_config


def test_log_directory_can_be_created(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        logging_config,
        "_application_root",
        lambda: tmp_path,
    )

    log_directory = (
        logging_config.get_log_directory()
    )

    assert log_directory == (
        tmp_path / "logs"
    )

    assert log_directory.is_dir()


def test_logger_name_filter():
    filter_ = (
        logging_config._LoggerNameFilter(
            exact=("http",),
            prefixes=(
                "app.services.selora",
            ),
        )
    )

    http_record = logging.LogRecord(
        "http",
        logging.INFO,
        __file__,
        1,
        "ok",
        (),
        None,
    )

    selora_record = logging.LogRecord(
        "app.services.selora_import_service",
        logging.INFO,
        __file__,
        1,
        "ok",
        (),
        None,
    )

    unrelated_record = logging.LogRecord(
        "crawler",
        logging.INFO,
        __file__,
        1,
        "ok",
        (),
        None,
    )

    assert filter_.filter(
        http_record
    )

    assert filter_.filter(
        selora_record
    )

    assert not filter_.filter(
        unrelated_record
    )


def test_exclude_logger_filter():
    filter_ = (
        logging_config._ExcludeLoggerFilter(
            exact=("http",),
            prefixes=(
                "app.services.selora",
            ),
        )
    )

    http_record = logging.LogRecord(
        "http",
        logging.INFO,
        __file__,
        1,
        "x",
        (),
        None,
    )

    selora_record = logging.LogRecord(
        "app.services.selora_import_service",
        logging.INFO,
        __file__,
        1,
        "x",
        (),
        None,
    )

    app_record = logging.LogRecord(
        "app",
        logging.INFO,
        __file__,
        1,
        "x",
        (),
        None,
    )

    assert not filter_.filter(
        http_record
    )

    assert not filter_.filter(
        selora_record
    )

    assert filter_.filter(
        app_record
    )
