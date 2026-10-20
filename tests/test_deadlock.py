"""macOS can deadlock inside CoreAudio while a stream is being closed.

Seen in the wild on 2026-10-20: the audio worker sat in PortAudio's
FinishStoppingStream -> HALB_Mutex::Lock for five days, holding every
later dictation behind it. The thread stays alive, so liveness checks
call it healthy. A thread blocked in a kernel mutex cannot be killed, so
the engine must bound the close and then relaunch instead of pretending
it recovered.
"""

from __future__ import annotations

import threading
import time
import types

import numpy as np
import pytest

from localflow import app as app_module
from localflow import recovery as recovery_module
from localflow.app import DictationApp
from localflow.config import Config


class FakeTranscriber:
    def __init__(self, *a, **kw):
        self.calls = 0

    def load(self):
        pass

    def transcribe(self, audio):
        self.calls += 1
        return "hello"


class FakeOutput:
    def __init__(self, *a, **kw):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class WedgedRecorder:
    """Its close never returns, exactly as CoreAudio's does."""

    last_device_name = "Yealink SP92 Speaker"
    last_peak = 0.0

    def __init__(self, *a, **kw):
        self.recording = False

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(0, dtype=np.float32)

    def stop_with_timeout(self, timeout):
        self.recording = False
        return None, True


class SilentRecorder:
    last_device_name = "MacBook Pro Microphone"

    def __init__(self, *a, **kw):
        self.recording = False
        self.last_peak = 0.0

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(16000, dtype=np.float32)

    def stop_with_timeout(self, timeout):
        audio = self.stop()
        self.last_peak = 0.0
        return audio, False


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def restarts(monkeypatch):
    """Capture restart requests instead of relaunching the app."""
    calls = []
    fake = types.SimpleNamespace(
        restart=lambda reason, **kw: (calls.append(reason), True)[1],
        dump_stacks=lambda reason: None,
    )
    monkeypatch.setattr(app_module, "recovery", fake, raising=False)
    return calls


def _engine(monkeypatch, recorder_cls):
    monkeypatch.setattr(app_module, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(app_module, "TextOutput", FakeOutput)
    monkeypatch.setattr(app_module, "Recorder", recorder_cls)
    engine = DictationApp(Config())
    engine._start_worker()
    engine._start_audio_worker()
    return engine


def test_deadlocked_close_does_not_wedge_the_worker(monkeypatch, restarts):
    engine = _engine(monkeypatch, WedgedRecorder)
    try:
        engine._on_start()
        assert _wait_for(lambda: engine.recorder.recording)
        engine._started_at = time.monotonic() - 2.0
        engine._on_stop()

        # The worker must come back for air and ask for a relaunch.
        assert _wait_for(lambda: bool(restarts)), "no restart was requested"
        assert "locked up" in restarts[0]
        assert _wait_for(lambda: engine._audio_inflight is None), "worker still busy"
        assert engine._audio_thread.is_alive()
        # Garbage audio must never reach the transcriber.
        assert engine.transcriber.calls == 0
    finally:
        engine.stop()


def test_real_recorder_bounds_a_blocking_close(monkeypatch):
    """The timeout lives in Recorder, against a stream that never closes."""
    from localflow.recorder import Recorder

    blocked = threading.Event()

    class BlockingStream:
        device = 0

        def start(self):
            pass

        def stop(self):
            blocked.wait(30)  # never set during the test

        def close(self):
            pass

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.PortAudioError = type("PortAudioError", (Exception,), {})
    fake_sd.InputStream = lambda **kw: BlockingStream()
    fake_sd.query_devices = lambda *a, **kw: {"name": "Yealink SP92 Speaker"}
    fake_sd._initialized = 1
    fake_sd._initialize = lambda: None
    fake_sd._terminate = lambda: None
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", fake_sd)

    rec = Recorder()
    rec.start()
    assert rec.recording

    started = time.monotonic()
    audio, timed_out = rec.stop_with_timeout(0.3)
    elapsed = time.monotonic() - started

    assert timed_out is True
    assert audio is None
    assert elapsed < 2.0, f"stop_with_timeout blocked for {elapsed:.1f}s"
    # The stream reference is dropped first, so nothing thinks it is live.
    assert not rec.recording
    blocked.set()


def test_silent_capture_is_named_not_transcribed(monkeypatch, restarts, capsys):
    engine = _engine(monkeypatch, SilentRecorder)
    logged = []
    monkeypatch.setattr(app_module, "log", lambda m: logged.append(m))
    try:
        engine._on_start()
        assert _wait_for(lambda: engine.recorder.recording)
        engine._started_at = time.monotonic() - 2.0
        engine._on_stop()
        assert _wait_for(lambda: any("silence" in m for m in logged))

        message = next(m for m in logged if "silence" in m)
        assert "MacBook Pro Microphone" in message, "the device must be named"
        assert "Sound" in message, "the message must say how to fix it"
        # Whisper would have called this "no speech detected" in 0.1s.
        assert engine.transcriber.calls == 0
        assert not any("too short" in m for m in logged)
    finally:
        engine.stop()


def test_watchdog_restarts_a_stuck_audio_worker(monkeypatch, restarts):
    engine = _engine(monkeypatch, WedgedRecorder)
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(app_module, "STUCK_AUDIO_SECONDS", 0.05)
    try:
        # Pretend a command has been in flight far too long.
        engine._audio_inflight = ("stop", time.monotonic() - 10.0)
        engine._watchdog_thread = threading.Thread(
            target=engine._watchdog, daemon=True
        )
        engine._watchdog_thread.start()

        assert _wait_for(lambda: bool(restarts)), "watchdog ignored a stuck worker"
        assert "stuck" in restarts[0]
    finally:
        engine.stop()


def test_restart_is_rate_limited(monkeypatch, tmp_path):
    """A relaunch loop would be worse than a dead hotkey."""
    monkeypatch.setattr(recovery_module, "SUPPORT_DIR", tmp_path)
    monkeypatch.setattr(recovery_module, "RESTART_LOG", tmp_path / "restarts.json")
    now = 1_000_000.0
    for _ in range(recovery_module.MAX_RESTARTS):
        assert recovery_module.restart_allowed(now)
        recovery_module._record_restart(now)
    assert not recovery_module.restart_allowed(now)
    # Outside the window the budget resets.
    assert recovery_module.restart_allowed(now + recovery_module.RESTART_WINDOW_SECONDS + 1)


def test_bundle_path_from_executable():
    assert (
        recovery_module.bundle_path("/Applications/LocalFlow.app/Contents/MacOS/LocalFlow")
        == "/Applications/LocalFlow.app"
    )
    assert recovery_module.bundle_path("/Users/Matt/localflow/.venv/bin/python") is None
