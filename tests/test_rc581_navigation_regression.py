"""RC5.8.1: no post-completion UI navigation loop from saved crawl state."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "index.html"
JS_TEST = ROOT / "tests" / "js" / "crawl_resume_rc581.cjs"


def test_completed_crawl_clears_resume_before_navigation() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    terminal = source.split("case 'completed':", 1)[1].split("case 'cancelled':", 1)[0]
    assert terminal.index("resetLoading()") < terminal.index("window.location.assign(data.detail_url)")
    assert "if (resumed)" in terminal
    assert 'viewResults.hidden = false' in terminal
    assert 'pollCrawlStatus(data.status_url, { resumed: true })' in source


def test_resumed_and_new_crawls_do_not_loop_in_javascript() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not installed; static regression check still runs")
    result = subprocess.run(
        [node, str(JS_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert result.stdout.count("[PASS]") == 3
