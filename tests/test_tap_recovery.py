"""macOS silently switches off a slow event tap, and the hotkey goes deaf.

This is the failure that killed dictation over and over in real use: the
listener thread stays alive, the menu-bar icon looks fine, and no key press
is ever seen again until the app is restarted. Two defences are tested here
— never being slow enough to get switched off, and recovering when it
happens anyway.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from localflow import app as app_module
from localflow.app import DictationApp
from localflow.config import Config
from localflow.hotkeys import HotkeyListener


class FakeTranscriber:
    def __init__(self, *a, **kw):
        pass

    def load(self):
        pass

    def transcribe(self, audio):
        return "hello"


class FakeOutput:
    def __init__(self, *a, **kw):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class SlowRecorder:
    """A microphone that takes ages to open, as PortAudio does after sleep."""

    OPEN_SECONDS = 1.5

    def __init__(self, *a, **kw):
        self.recording = False

    def start(self):
        time.sleep(self.OPEN_SECONDS)
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(0, dtype=np.float32)


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(app_module, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(app_module, "TextOutput", FakeOutput)
    monkeypatch.setattr(app_module, "Recorder", SlowRecorder)
    engine = DictationApp(Config())
    engine._start_worker()
    engine._start_audio_worker()
    yield engine
    engine.stop()


def test_hotkey_callback_returns_immediately(engine):
    """The event-tap callback must never wait on the microphone.

    macOS disables a tap whose callback overruns its timeout, so blocking
    here for a slow device open is what made the hotkey die for good.
    """
    started = time.monotonic()
    engine._on_start()
    press_elapsed = time.monotonic() - started

    started = time.monotonic()
    engine._on_stop()
    release_elapsed = time.monotonic() - started

    # SlowRecorder takes 1.5s to open; neither callback may wait for it.
    assert press_elapsed < 0.1, f"press blocked the tap for {press_elapsed:.2f}s"
    assert release_elapsed < 0.1, f"release blocked the tap for {release_elapsed:.2f}s"

    # The work still happens, just on the audio thread instead.
    assert _wait_for(lambda: engine._audio_cmds.empty())


def test_recording_survives_a_slow_microphone(engine):
    """A slow open must still produce a transcription, just later."""
    engine._on_start()
    assert _wait_for(lambda: engine.recorder.recording)
    engine._started_at = time.monotonic() - 2.0  # a real-length utterance
    engine.recorder.stop = lambda: np.zeros(16000, dtype=np.float32)
    engine._on_stop()
    assert _wait_for(lambda: engine.output.sent == ["hello "])


class FakeTap:
    """Stands in for a pynput listener whose tap macOS can switch off."""

    def __init__(self):
        self.enabled = True
        self.rearms = 0
        self.on_tap_recovered = None

    def is_alive(self):
        return True

    def stop(self):
        self.enabled = False

    @property
    def tap_enabled(self):
        return self.enabled

    def rearm_tap(self):
        self.rearms += 1
        self.enabled = True
        return True


def test_deaf_tap_is_reported_unhealthy_and_rearmed(engine):
    listener = HotkeyListener(
        hotkey="cmd_r", mode="hold", on_start=lambda: None, on_stop=lambda: None
    )
    tap = FakeTap()
    listener._listener = tap
    engine._listener = listener

    assert engine.healthy

    # macOS switches the tap off; the thread stays alive, so liveness alone
    # would still call this healthy.
    tap.enabled = False
    assert listener.alive
    assert not listener.tap_enabled
    assert not engine.healthy, "a live but deaf tap must not read as healthy"

    assert listener.rearm()
    assert tap.rearms == 1
    assert engine.healthy


def test_watchdog_rearms_a_deaf_tap(engine, monkeypatch):
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_SECONDS", 0.05)
    listener = HotkeyListener(
        hotkey="cmd_r", mode="hold", on_start=lambda: None, on_stop=lambda: None
    )
    tap = FakeTap()
    tap.enabled = False
    listener._listener = tap
    engine._listener = listener

    engine._watchdog_thread = threading.Thread(target=engine._watchdog, daemon=True)
    engine._watchdog_thread.start()

    assert _wait_for(lambda: tap.rearms >= 1), "watchdog never re-armed the tap"
    assert engine.healthy


def test_recovery_clears_a_stuck_hold():
    """A hold interrupted by the tap dying must not wedge the next press."""
    interrupted = []
    listener = HotkeyListener(
        hotkey="cmd_r",
        mode="hold",
        on_start=lambda: None,
        on_stop=lambda: None,
        on_interrupt=lambda: interrupted.append(True),
    )
    listener._active = True  # a hold was in progress when the tap died

    listener._handle_tap_recovered()

    # Without this reset the next press is swallowed as auto-repeat and
    # dictation never starts again.
    assert listener._active is False
    assert interrupted == [True]
