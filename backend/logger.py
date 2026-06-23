"""PRANA logging module — single source of truth for all logging."""
import logging
import sys
from typing import Optional


_LOG = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    global _LOG
    if _LOG is None:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        _LOG = logging.getLogger("prana")
        _LOG.addHandler(handler)
        _LOG.setLevel(logging.DEBUG)
    return _LOG if name is None else _LOG.getChild(name)
