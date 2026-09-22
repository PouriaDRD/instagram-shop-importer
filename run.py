from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _prepare_runtime_directory() -> Path:
    if getattr(sys, "frozen", False):
        runtime_root = Path(sys.executable).resolve().parent
    else:
        runtime_root = Path(__file__).resolve().parent

    os.chdir(runtime_root)
    return runtime_root


RUNTIME_ROOT = _prepare_runtime_directory()

# Normal desktop startup must use the explicit runtime migrator below rather
# than create_all(), which cannot alter an existing SQLite schema.
os.environ["INSTAGRAM_IMPORTER_SKIP_CREATE_ALL"] = "1"

import flask.cli  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app.config import Config  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.runtime_single_instance import SingleInstanceGuard  # noqa: E402

configure_logging()
logger = logging.getLogger("app")


def _open_browser() -> None:
    url = f"http://{Config.HOSTNAME}:{Config.PORT}"
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("Could not open browser automatically.")


_INSTANCE_GUARD: SingleInstanceGuard | None = None

if __name__ == "__main__":
    _INSTANCE_GUARD = SingleInstanceGuard(
        name=f"SeloraInstagramImporter-{Config.PORT}"
    )
    if not _INSTANCE_GUARD.acquire():
        logger.info("Importer is already running; opening the existing instance.")
        _open_browser()
        raise SystemExit(0)

from app.integrations.selora.retry_transport import (  # noqa: E402
    install_selora_retry_transport,
)
from app.integrations.selora.diagnostics import (  # noqa: E402
    install_selora_diagnostics,
)
from app.runtime_import_status import (  # noqa: E402
    install_import_status_tracking,
)

install_selora_retry_transport()
install_selora_diagnostics()
install_import_status_tracking()

from app import create_app  # noqa: E402
from app.runtime_database import (  # noqa: E402
    configure_sqlite_runtime,
    migrate_runtime_database,
)
from app.runtime_shutdown import SafeShutdownController  # noqa: E402
from app.services.session_status_service import (  # noqa: E402
    register_session_status_helpers,
)

app = create_app()
register_session_status_helpers(app)
shutdown_controller = SafeShutdownController(app=app)
shutdown_controller.install()

try:
    configure_sqlite_runtime(app)
    migrate_runtime_database(app)
except Exception:
    logger.exception("Database startup migration failed; importer will not start.")
    raise


if __name__ == "__main__":
    flask.cli.show_server_banner = lambda *args, **kwargs: None

    url = f"http://{Config.HOSTNAME}:{Config.PORT}"
    server = make_server(
        Config.HOSTNAME,
        Config.PORT,
        app,
        threaded=True,
    )
    shutdown_controller.bind_server_shutdown(server.shutdown)

    logger.info("Importer ready on %s", url)
    threading.Timer(1.0, _open_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received; starting safe shutdown")
        shutdown_controller.request_shutdown()
        shutdown_controller.wait()
    finally:
        server.server_close()
        if _INSTANCE_GUARD is not None:
            _INSTANCE_GUARD.release()
        logger.info("Importer stopped")
