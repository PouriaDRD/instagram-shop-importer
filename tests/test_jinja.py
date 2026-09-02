from __future__ import annotations

from pathlib import Path

from flask import Flask

TEMPLATE_DIRECTORY = Path("app/templates")


def test_all_templates_compile(
    app: Flask,
) -> None:
    templates = sorted(TEMPLATE_DIRECTORY.glob("*.html"))

    assert templates

    for template_path in templates:
        app.jinja_env.get_template(template_path.name)


def test_no_jinja_null_test_exists_in_templates() -> None:
    bad_lines: list[str] = []

    for path in TEMPLATE_DIRECTORY.rglob("*.html"):
        content = path.read_text(encoding="utf-8")

        for line_number, line in enumerate(
            content.splitlines(),
            start=1,
        ):
            if "is null" in line or "is not null" in line:
                bad_lines.append((f"{path}:" f"{line_number}: " f"{line.strip()}"))

    assert not bad_lines, "Invalid Jinja null checks found:\n" + "\n".join(bad_lines)


def test_defensive_null_alias_exists(
    app: Flask,
) -> None:
    assert "null" in app.jinja_env.tests

    null_test = app.jinja_env.tests["null"]

    assert null_test(None) is True
    assert null_test(0) is False
    assert null_test("") is False


def test_required_datetime_filters_exist(
    app: Flask,
) -> None:
    filters = app.jinja_env.filters

    assert "iran_date" in filters
    assert "iran_time" in filters

    assert "iran_datetime" in filters


def test_persian_templates_are_valid_utf8() -> None:
    for path in TEMPLATE_DIRECTORY.rglob("*.html"):
        content = path.read_text(encoding="utf-8")

        assert "\ufffd" not in content
