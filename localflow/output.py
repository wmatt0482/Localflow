"""Deliver transcribed text into the currently focused application.

Two strategies:

* ``paste`` (default): put the text on the clipboard and press Ctrl+V
  (Cmd+V on macOS). Fast and robust for long text, emoji and accents.
  Optionally restores the previous clipboard contents afterwards.
* ``type``: simulate individual keystrokes. Slower, but works in apps
  that block paste.
"""

from __future__ import annotations

import sys
import time


class TextOutput:
    def __init__(self, method: str = "paste", restore_clipboard: bool = True):
        if method not in ("paste", "type"):
            raise ValueError(f"unknown output method: {method!r}")
        self.method = method
        self.restore_clipboard = restore_clipboard
        self._keyboard = None

    def _controller(self):
        if self._keyboard is None:
            from pynput.keyboard import Controller

            self._keyboard = Controller()
        return self._keyboard

    def send(self, text: str) -> None:
        if not text:
            return
        if self.method == "paste":
            self._paste(text)
        else:
            self._type(text)

    def _type(self, text: str) -> None:
        self._controller().type(text)

    def _paste(self, text: str) -> None:
        import pyperclip
        from pynput.keyboard import Key

        keyboard = self._controller()
        previous = None
        if self.restore_clipboard:
            try:
                previous = pyperclip.paste()
            except pyperclip.PyperclipException:
                previous = None

        pyperclip.copy(text)
        # Give the clipboard manager a moment to register the new value.
        time.sleep(0.05)

        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with keyboard.pressed(modifier):
            keyboard.press("v")
            keyboard.release("v")

        if previous is not None:
            # Wait for the target app to read the clipboard before
            # restoring, otherwise it would paste the old contents.
            time.sleep(0.3)
            pyperclip.copy(previous)
