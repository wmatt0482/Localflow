"""Global hotkey handling via pynput.

Supports two interaction modes:

* hold: press starts recording, release stops it (push-to-talk).
* toggle: press once to start, press again to stop.
"""

from __future__ import annotations

from typing import Callable


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


class HotkeyListener:
    """Calls ``on_start``/``on_stop`` according to hotkey and mode."""

    def __init__(
        self,
        hotkey: str,
        mode: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ):
        self.key = parse_hotkey(hotkey)
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
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

    def start(self) -> None:
        """Start listening in a background thread (non-blocking)."""
        if self._listener is not None:
            return
        from pynput.keyboard import Listener

        self._listener = Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

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
