"""Root-logger configuration.

``setup_logging()`` is idempotent: it adds handlers only once, so it is safe to
call from ``bootstrap()`` and from any module that needs early logging.
"""

import logging

from src.app_config import LOG_FILE, LOGS_DIR

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)-10s: %(message)s"


def setup_logging() -> None:
    """Configure root logger with a file handler and a stream handler.

    Safe to call multiple times; handlers are added only once.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return  # already configured

    root.setLevel(logging.INFO)

    fmt = logging.Formatter(_LOG_FORMAT)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
