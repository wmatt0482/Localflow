"""macOS menu-bar app for LocalFlow.

Shows a microphone icon in the menu bar (red dot while recording) with
Pause/Resume and Quit. The dictation engine is the same DictationApp the
CLI uses; the model loads in a background thread so the icon appears
immediately.
"""

from __future__ import annotations

import sys
import threading

_KEY_LABELS = {
    "cmd_r": "Right ⌘",
    "cmd": "⌘",
    "ctrl_r": "Right Ctrl",
    "ctrl": "Ctrl",
    "alt_r": "Right ⌥",
    "shift_r": "Right ⇧",
}

ICON_LOADING = "⏳"    # hourglass
ICON_READY = "\U0001f3a4"  # microphone
ICON_RECORDING = "\U0001f534"  # red circle
ICON_PAUSED = "⏸"     # pause
ICON_TROUBLE = "⚠️"  # warning sign


def _hotkey_label(hotkey: str) -> str:
    return _KEY_LABELS.get(hotkey, hotkey)


def main() -> int:
    if sys.platform != "darwin":
        print("The menu-bar app requires macOS. Use `localflow` instead.")
        return 1

    import rumps

    from .app import DictationApp
    from .applog import log, setup as setup_logging
    from .config import load_config
    from .hotkeys import prime_keycode_context

    log_path = setup_logging()

    # We're on the main thread here; the engine boots on a worker thread,
    # which must never touch the TIS keyboard-layout APIs.
    prime_keycode_context()

    # Without Accessibility the hotkey listener silently receives nothing,
    # and a quiet AXIsProcessTrusted() check doesn't even register the app
    # in the Accessibility pane. Ask with the system prompt instead, which
    # does both. macOS shows the dialog at most once per grant state.
    try:
        import HIServices

        ax_trusted = HIServices.AXIsProcessTrusted()
        if not ax_trusted:
            HIServices.AXIsProcessTrustedWithOptions(
                {"AXTrustedCheckOptionPrompt": True}
            )
    except Exception as e:
        ax_trusted = f"check failed: {e}"

    # Listening for keys needs Input Monitoring as well on newer macOS.
    # Without it CGEventTapCreate returns NULL and pynput gives up
    # silently, so the hotkey is dead with no error anywhere.
    try:
        import ctypes

        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        kIOHIDRequestTypeListenEvent = 1
        hid_access = iokit.IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)
        hid_access = {0: "granted", 1: "denied", 2: "undetermined"}.get(
            hid_access, hid_access
        )
        if hid_access != "granted":
            iokit.IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
    except Exception as e:
        hid_access = f"check failed: {e}"

    log(f"[localflow] accessibility={ax_trusted} input-monitoring={hid_access}")

    config = load_config()
    engine = DictationApp(config)

    class Tray(rumps.App):
        def __init__(self) -> None:
            super().__init__("LocalFlow", title=ICON_LOADING, quit_button=None)
            self.paused = False
            action = "Hold" if config.mode == "hold" else "Press"
            self.hint_item = rumps.MenuItem(
                f"{action} {_hotkey_label(config.hotkey)} to dictate"
            )
            self.pause_item = rumps.MenuItem(
                "Pause listening", callback=self.on_pause
            )
            self.menu = [
                self.hint_item,
                self.pause_item,
                None,
                rumps.MenuItem("Open log", callback=self.on_open_log),
                rumps.MenuItem("Quit LocalFlow", callback=self.on_quit),
            ]
            # Poll engine state from the main thread; AppKit UI must not
            # be touched from the recorder/transcriber threads.
            self.timer = rumps.Timer(self.sync, 0.25)
            self.timer.start()

        def sync(self, _timer) -> None:
            if self.paused:
                icon = ICON_PAUSED
            elif not engine.ready:
                icon = ICON_LOADING
            elif engine.recording:
                icon = ICON_RECORDING
            elif not engine.healthy:
                # The watchdog restarts dead threads within seconds; if
                # this sticks, something is wrong worth looking at.
                icon = ICON_TROUBLE
            else:
                icon = ICON_READY
            if self.title != icon:
                self.title = icon

        def on_open_log(self, _item) -> None:
            if log_path is None:
                rumps.alert("LocalFlow", "No log file could be opened.")
                return
            import subprocess

            subprocess.Popen(["/usr/bin/open", "-R", str(log_path)])

        def on_pause(self, item) -> None:
            if self.paused:
                engine.resume()
                item.title = "Pause listening"
            else:
                engine.pause()
                item.title = "Resume listening"
            self.paused = not self.paused

        def on_quit(self, _item) -> None:
            engine.stop()
            rumps.quit_application()

    def boot() -> None:
        try:
            engine.start()
        except Exception as e:
            log(f"[localflow] failed to start: {e}")
            rumps.notification(
                "LocalFlow", "Failed to start", str(e), sound=False
            )
            return
        # pynput exits its listener thread silently when the event tap
        # can't be created (missing permission); make that visible.
        import time as _time

        _time.sleep(3)
        if engine._listener is not None and not engine._listener.alive:
            log(
                "[localflow] hotkey listener died — event tap not created. "
                "Check Accessibility AND Input Monitoring in System "
                "Settings > Privacy & Security, then relaunch."
            )

    threading.Thread(target=boot, daemon=True).start()
    Tray().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
