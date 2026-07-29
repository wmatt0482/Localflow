"""Persistent logging.

Everything LocalFlow reports goes to a real log file as well as stdout, so
a failure that happens hours after launch can still be diagnosed. The menu
-bar app has no console, and macOS reaps the temporary files a debugging
session might redirect into, so without this a silent failure leaves
nothing behind to look at.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

_logger = logging.getLogger("localflow")
_configured = False
_lock = threading.Lock()


def default_log_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "LocalFlow.log"
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "localflow" / "localflow.log"


def setup(path: Path | None = None) -> Path | None:
    """Attach a rotating file handler. Safe to call more than once.

    Returns the log path, or None if the file could not be opened (in
    which case logging still goes to stdout).
    """
    global _configured
    with _lock:
        if _configured:
            return getattr(_logger, "_localflow_path", None)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        path = path or default_log_path()
        opened: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            _logger.addHandler(handler)
            opened = path
        except OSError as e:
            print(f"[localflow] could not open log file {path}: {e}", flush=True)
        _logger._localflow_path = opened  # type: ignore[attr-defined]
        _configured = True

        # A crash on a background thread otherwise vanishes without trace.
        def _thread_hook(args) -> None:
            _logger.error(
                "unhandled exception in thread %s",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_hook
        return opened


def log(message: str) -> None:
    """Report a line to the user (stdout) and to the log file."""
    print(message, flush=True)
    _logger.info(message)


def exception(message: str) -> None:
    """Report a caught exception with its traceback to the log file."""
    print(message, flush=True)
    _logger.exception(message)
