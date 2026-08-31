"""Central logging setup — call configure_logging() once, at process startup.

Handlers are attached to the root logger ONLY. Every module logger below it
(``rpi5.detect``, ``rpi5.events``, ...) just calls ``getLogger(__name__)`` and
relies on the default ``propagate=True`` to reach these handlers — attaching a
second handler to an individual module logger would duplicate every line it
emits, and setting ``propagate=False`` anywhere would silently drop its logs
instead of duplicating them. Keep it this way.
"""
from __future__ import annotations

import logging.config
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d: %(message)s"

# Retention upper bound = maxBytes * (backupCount + 1) = 10MB * 6 = 60MB, so disk
# usage from this file alone is always bounded and calculable.
_ROTATE_MAX_BYTES = 10 * 1024 * 1024
_ROTATE_BACKUP_COUNT = 5

_ENV_DEFAULT_LEVEL = {
    "development": "DEBUG",
    "staging": "INFO",
    "production": "INFO",
}


def configure_logging() -> None:
    cfg = get_config()
    level = cfg.log_level or _ENV_DEFAULT_LEVEL.get(cfg.env, "INFO")

    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: dict = {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": str(log_dir / "rpi5.log"),
            "maxBytes": _ROTATE_MAX_BYTES,
            "backupCount": _ROTATE_BACKUP_COUNT,
            "encoding": "utf-8",
        },
    }
    root_handlers = ["console", "file"]

    if cfg.log_ship_url:
        # Minimal central-log-station hook (ELK/Loki/CloudWatch-style aggregation):
        # POSTs each formatted record to an HTTP collector. Swap for the collector's
        # own client if it needs auth headers or a specific payload shape — this is
        # deliberately the lowest-effort thing that satisfies "logs land somewhere
        # queryable outside this one SD card", not a permanent choice.
        parsed = urlparse(cfg.log_ship_url)
        handlers["central"] = {
            "class": "logging.handlers.HTTPHandler",
            "formatter": "default",
            "host": parsed.netloc,
            "url": parsed.path or "/",
            "method": "POST",
            "secure": parsed.scheme == "https",
        }
        root_handlers.append("central")

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": LOG_FORMAT}},
        "handlers": handlers,
        "root": {"level": level, "handlers": root_handlers},
    })
