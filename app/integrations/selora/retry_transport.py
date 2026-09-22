from __future__ import annotations

from functools import wraps
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.integrations.selora.client import SeloraApiClient


logger = logging.getLogger(__name__)


def build_selora_retry_session() -> requests.Session:
    """Create a bounded retry transport for transient Selora failures."""
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=2,
        other=1,
        backoff_factor=0.6,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=8,
        pool_maxsize=8,
    )
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def install_selora_retry_transport() -> None:
    """
    Inject the retrying Session into SeloraApiClient without changing its
    public contract or response parsing code.
    """
    if getattr(SeloraApiClient, "_selora_retry_transport_installed", False):
        return

    original_init = SeloraApiClient.__init__

    @wraps(original_init)
    def _retrying_init(self, *args, **kwargs):
        if kwargs.get("http_session") is None:
            kwargs["http_session"] = build_selora_retry_session()
        return original_init(self, *args, **kwargs)

    SeloraApiClient.__init__ = _retrying_init
    setattr(SeloraApiClient, "_selora_retry_transport_installed", True)
    logger.info("Selora bounded retry transport installed")
