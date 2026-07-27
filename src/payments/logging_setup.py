"""Logging configuration helper for the payments batch platform."""

from __future__ import annotations

import logging

from payments.config import get_settings

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_CONFIGURED_MARKER = "_payments_configured"


def configure_logging(level: str | None = None) -> None:
    if level is None:
        level = get_settings().log_level

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if getattr(root_logger, _CONFIGURED_MARKER, False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root_logger.addHandler(handler)
    setattr(root_logger, _CONFIGURED_MARKER, True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
