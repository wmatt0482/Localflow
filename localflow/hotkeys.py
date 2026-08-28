"""Global hotkey handling via pynput.

Supports two interaction modes:

* hold: press starts recording, release stops it (push-to-talk).
* toggle: press once to start, press again to stop.
"""

from __future__ import annotations

import sys
from typing import Callable

from .applog import log


def prime_keycode_context() -> None:
    """Cache the keyboard layout for pynput. Must run on the MAIN thread.

    macOS 15+ kills the process (EXC_BREAKPOINT in dispatch_assert_queue)
    when the TIS* input-source APIs are called off the main queue. pynput
    resolves the keyboard layout with those APIs on its listener thread and
    on whatever thread first uses a Controller, so resolve the layout here
    once and patch pynput to reuse the cached result. Layout switches while
    the app runs won't be picked up — same tradeoff pynput already makes
    for the lifetime of a listener.
    """
    if sys.platform != "darwin":
        return
    import contextlib

    from pynput._util import darwin as util_darwin
    from pynput.keyboard import _darwin as keyboard_darwin

    with util_darwin.keycode_context() as context:
        cached = context

    @contextlib.contextmanager
    def cached_context():
        yield cached

    util_darwin.keycode_context = cached_context
    keyboard_darwin.keycode_context = cached_context


def parse_hotkey(name: str):
    """Resolve a config string like "ctrl_r", "f9" or "§" to a pynput key.

    Returns either a ``Key`` enum member or a ``KeyCode``.
    """
    from pynput.keyboard import Key, KeyCode

    name = name.strip()
    if len(name) == 1:
        return KeyCode.from_char(name.lower())
    try:
        return Key[name.lower()]
    except KeyError:
        raise ValueError(
            f"Unknown hotkey {name!r}. Use a single character or a pynput "
            f"key name like 'ctrl_r', 'f9', 'pause', 'scroll_lock'."
        ) from None


# macOS switches an event tap off behind your back: if the tap's callback
# takes too long it sends kCGEventTapDisabledByTimeout and stops delivering
# events, and certain system events do the same. pynput enables the tap once
# at startup and keeps no reference to it, so it can never switch it back on
# — the listener thread stays alive but goes permanently deaf, which looks
# exactly like "the hotkey stopped working" until the app is restarted.
# Catch the notification macOS sends and re-arm the tap.
def _listener_class():
    from pynput.keyboard import Listener

    if sys.platform != "darwin":
        return Listener

    from Quartz import (
        CGEventTapEnable,
        CGEventTapIsEnabled,
        kCGEventTapDisabledByTimeout,
        kCGEventTapDisabledByUserInput,
    )

    _TAP_DISABLED = (
        kCGEventTapDisabledByTimeout,
        kCGEventTapDisabledByUserInput,
    )

    class ResilientListener(Listener):
        """Keyboard listener that re-arms its tap when macOS disables it."""

        #: Called after the tap is re-armed, so the owner can reset state.
        on_tap_recovered: Callable[[], None] | None = None

        def __init__(self, *args, **kwargs):
            self._tap = None
            super().__init__(*args, **kwargs)

        def _create_event_tap(self):
            self._tap = super()._create_event_tap()
            return self._tap

        def _handle_message(
            self, proxy, event_type, event, refcon, injected=False
        ):
            if event_type in _TAP_DISABLED:
                self.rearm_tap()
                callback = self.on_tap_recovered
                if callback is not None:
                    callback()
                return None
            return super()._handle_message(
                proxy, event_type, event, refcon, injected
            )

        def rearm_tap(self) -> bool:
            if self._tap is None:
                return False
            CGEventTapEnable(self._tap, True)
            return self.tap_enabled

        @property
        def tap_enabled(self) -> bool:
            return self._tap is not None and bool(CGEventTapIsEnabled(self._tap))

    return ResilientListener


class HotkeyListener:
    """Calls ``on_start``/``on_stop`` according to hotkey and mode."""

    def __init__(
        self,
        hotkey: str,
        mode: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_interrupt: Callable[[], None] | None = None,
    ):
        self.key = parse_hotkey(hotkey)
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        # Called when a hold is cut short by the tap dying mid-press.
        self.on_interrupt = on_interrupt
        self._active = False
        self._listener = None

    def _matches(self, key) -> bool:
        from pynput.keyboard import KeyCode

        if isinstance(key, KeyCode) and isinstance(self.key, KeyCode):
            return key.char is not None and key.char.lower() == self.key.char
        return key == self.key

    def _on_press(self, key) -> None:
        if not self._matches(key):
            return
        if self.mode == "toggle":
            if self._active:
                self._active = False
                self.on_stop()
            else:
                self._active = True
                self.on_start()
        elif not self._active:  # hold; ignore key auto-repeat
            self._active = True
            self.on_start()

    def _on_release(self, key) -> None:
        if self.mode == "hold" and self._matches(key) and self._active:
            self._active = False
            self.on_stop()

    @property
    def alive(self) -> bool:
        """Whether the underlying listener thread is actually running.

        pynput's listener thread exits on its own when macOS tears down or
        refuses the event tap, and nothing else notices: the hotkey simply
        stops responding. Callers poll this to detect that.
        """
        listener = self._listener
        return listener is not None and listener.is_alive()

    @property
    def tap_enabled(self) -> bool:
        """Whether macOS is still delivering events to our tap.

        A live thread is not enough: the tap can be switched off while the
        thread keeps running, which is the silent failure this guards.
        """
        listener = self._listener
        if listener is None:
            return False
        # Non-macOS listeners have no tap; treat them as always live.
        return bool(getattr(listener, "tap_enabled", True))

    def rearm(self) -> bool:
        """Switch the tap back on; fall back to a full restart."""
        listener = self._listener
        rearm_tap = getattr(listener, "rearm_tap", None)
        if rearm_tap is not None and rearm_tap():
            self._handle_tap_recovered()
            return True
        self.stop()
        self.start()
        return self.tap_enabled

    def _handle_tap_recovered(self) -> None:
        # While the tap was off no events arrived, so a release we were
        # waiting on is gone for good. Clear the held-key state or the next
        # press is swallowed as auto-repeat and never starts a recording.
        was_active, self._active = self._active, False
        log("[localflow] macOS disabled the event tap — re-armed")
        if was_active and self.on_interrupt is not None:
            self.on_interrupt()

    def start(self) -> None:
        """Start listening in a background thread (non-blocking)."""
        if self.alive:
            return
        if self._listener is not None:
            # A dead listener object can't be restarted; drop it first.
            self.stop()
        listener = _listener_class()(
            on_press=self._on_press, on_release=self._on_release
        )
        listener.on_tap_recovered = self._handle_tap_recovered
        self._listener = listener
        listener.start()

    def join(self) -> None:
        """Block until the listener stops (Ctrl+C interrupts)."""
        if self._listener is not None:
            self._listener.join()

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.stop()
        self._active = False

    def run(self) -> None:
        """Block, listening for the hotkey until interrupted."""
        self.start()
        self.join()
