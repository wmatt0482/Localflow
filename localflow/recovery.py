"""Recover from failures that cannot be fixed inside the process.

A thread blocked in a kernel mutex cannot be interrupted, killed or
joined. macOS CoreAudio does exactly that to us: when an input device
disappears while its stream is being stopped, PortAudio's
FinishStoppingStream waits forever on a HAL mutex, and the audio worker
is gone for the lifetime of the process. Observed in the wild on
2026-10-20 after five days wedged (docs/audit-2026-09-14/
deadlock-stack-excerpt.txt).

Nothing in-process can undo that, so the only honest recovery is to
relaunch. This module decides when that is allowed and performs it.
"""

from __future__ import annotations

import faulthandler
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .applog import exception as log_exception, log

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "LocalFlow"
RESTART_LOG = SUPPORT_DIR / "restarts.json"
CRASH_LOG = Path.home() / "Library" / "Logs" / "LocalFlow-crash.log"

# A relaunch loop is worse than a dead hotkey: it would respawn every few
# seconds forever. Allow a few, then stop and leave the reason on screen.
MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 1800.0

_lock = threading.Lock()
_already_restarting = False


def bundle_path(executable: str | None = None) -> str | None:
    """The .app this process was launched from, if any."""
    exe = executable if executable is not None else sys.executable
    marker = ".app/Contents/MacOS/"
    index = exe.find(marker)
    return exe[: index + len(".app")] if index != -1 else None


def _recent_restarts(now: float) -> list[float]:
    try:
        stamps = json.loads(RESTART_LOG.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(stamps, list):
        return []
    return [
        float(s)
        for s in stamps
        if isinstance(s, (int, float)) and now - float(s) < RESTART_WINDOW_SECONDS
    ]


def restart_allowed(now: float) -> bool:
    return len(_recent_restarts(now)) < MAX_RESTARTS


def _record_restart(now: float) -> None:
    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        RESTART_LOG.write_text(json.dumps(_recent_restarts(now) + [now]))
    except OSError as e:
        # Losing the counter only costs us the loop guard; never fatal.
        log(f"[localflow] could not record the restart ({e})")


def dump_stacks(reason: str) -> None:
    """Append every thread's stack to the crash log, for diagnosis later."""
    try:
        CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CRASH_LOG.open("a") as fp:
            fp.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {reason} ====\n")
            faulthandler.dump_traceback(file=fp, all_threads=True)
        log(f"[localflow] thread stacks written to {CRASH_LOG}")
    except Exception as e:  # diagnosis must never break recovery
        log_exception(f"[localflow] could not dump stacks: {e}")


def restart(reason: str, *, now: float | None = None) -> bool:
    """Relaunch this app, once. Returns False if it was not attempted.

    The caller's thread may itself be the wedged one, so this never waits
    on anything: it spawns a detached helper that waits for our pid to
    disappear and then reopens the bundle.
    """
    global _already_restarting
    now = time.monotonic() if now is None else now
    wall = time.time()

    with _lock:
        if _already_restarting:
            return False
        bundle = bundle_path()
        if bundle is None:
            log(f"[localflow] {reason} - not running from an .app, cannot relaunch")
            return False
        if not restart_allowed(wall):
            log(
                f"[localflow] {reason} - already restarted {MAX_RESTARTS} times in "
                f"the last {RESTART_WINDOW_SECONDS / 60:.0f} minutes; not restarting "
                f"again. Quit and reopen LocalFlow to reset this."
            )
            return False
        _already_restarting = True

    log(f"[localflow] {reason} - restarting LocalFlow")
    dump_stacks(reason)
    _record_restart(wall)
    try:
        subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; '
                'exec /usr/bin/open "$2"',
                "sh",
                str(os.getpid()),
                bundle,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log_exception(f"[localflow] could not spawn the relaunch helper: {e}")
        with _lock:
            _already_restarting = False
        return False

    # os._exit, not sys.exit: a wedged CoreAudio thread makes an orderly
    # interpreter shutdown hang, which would strand the helper forever.
    threading.Timer(1.0, os._exit, (0,)).start()
    return True
