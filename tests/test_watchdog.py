"""The engine must survive failures that used to silently kill dictation.

Historically a single bad recording could kill the transcription worker,
and macOS could tear down the hotkey listener, in both cases leaving an
app that looks alive (icon still blinks) but never produces text again.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from localflow import app as app_module
from localflow.app import DictationApp
from localflow.config import Config


class FakeTranscriber:
    def __init__(self, *a, **kw):
        self.calls = 0
        self.raise_on_call = 0

    def load(self):
        pass

    def transcribe(self, audio):
        self.calls += 1
        if self.calls == self.raise_on_call:
            raise RuntimeError("boom")
        return "hello"


class FakeOutput:
    def __init__(self, *a, **kw):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class FakeRecorder:
    def __init__(self, *a, **kw):
        self.recording = False

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(0, dtype=np.float32)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(app_module, "Transcriber", FakeTranscriber)
    monkeypatch.setattr(app_module, "TextOutput", FakeOutput)
    monkeypatch.setattr(app_module, "Recorder", FakeRecorder)
    engine = DictationApp(Config())
    engine._start_worker()
    yield engine
    engine.stop()


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_worker_survives_a_failing_transcription(engine):
    """One bad utterance must not stop later ones from working."""
    engine.transcriber.raise_on_call = 1
    engine._jobs.put(np.zeros(16000, dtype=np.float32))
    engine._jobs.put(np.zeros(16000, dtype=np.float32))

    assert _wait_for(lambda: engine.output.sent == ["hello "])
    assert engine._worker_thread.is_alive()


def test_worker_survives_an_unexpected_error(engine, monkeypatch):
    """Errors outside transcription must not kill the worker either."""
    boom = iter([True, False])

    original = app_module.textproc.process

    def flaky(*args, **kwargs):
        if next(boom, False):
            raise ValueError("unexpected")
        return original(*args, **kwargs)

    monkeypatch.setattr(app_module.textproc, "process", flaky)
    engine._jobs.put(np.zeros(16000, dtype=np.float32))
    engine._jobs.put(np.zeros(16000, dtype=np.float32))

    assert _wait_for(lambda: engine.output.sent == ["hello "])
    assert engine._worker_thread.is_alive()


def test_healthy_reports_a_dead_worker(engine):
    engine._jobs.put(None)  # ask the worker to exit
    assert _wait_for(lambda: not engine._worker_thread.is_alive())
    assert not engine.healthy


def test_watchdog_restarts_a_dead_worker(engine, monkeypatch):
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_SECONDS", 0.05)
    engine._listener = None
    engine._paused = True  # only exercise the worker half here
    import threading

    engine._watchdog_thread = threading.Thread(target=engine._watchdog, daemon=True)
    engine._watchdog_thread.start()

    dead = engine._worker_thread
    engine._jobs.put(None)
    assert _wait_for(lambda: not dead.is_alive())

    assert _wait_for(lambda: engine._worker_thread is not dead)
    assert engine._worker_thread.is_alive()
    assert engine.healthy

    # and the replacement actually works
    engine._jobs.put(np.zeros(16000, dtype=np.float32))
    assert _wait_for(lambda: engine.output.sent == ["hello "])


def test_pause_during_model_load_is_not_undone_by_start(monkeypatch):
    """Pausing while the model loads must not arm the hotkey afterwards.

    The menu is live while the model loads, so this window is seconds
    long (minutes on first run) — pressing Pause there used to leave a
    paused-looking app that still pasted text at the cursor.
    """
    started = []

    class SlowTranscriber(FakeTranscriber):
        def load(self):
            engine.pause()  # user clicks Pause while we're loading

    class RecordingListener:
        def __init__(self, **kw):
            self.alive = False

        def start(self):
            started.append(1)
            self.alive = True

        def stop(self):
            self.alive = False

    monkeypatch.setattr(app_module, "Transcriber", SlowTranscriber)
    monkeypatch.setattr(app_module, "TextOutput", FakeOutput)
    monkeypatch.setattr(app_module, "Recorder", FakeRecorder)
    monkeypatch.setattr(app_module, "HotkeyListener", RecordingListener)

    engine = DictationApp(Config())
    engine.start()
    try:
        assert started == [], "hotkey was armed despite being paused"
        assert engine._paused
    finally:
        engine.stop()


def test_quit_during_model_load_does_not_arm_the_hotkey(monkeypatch):
    class QuittingTranscriber(FakeTranscriber):
        def load(self):
            engine.stop()  # user quits while we're loading

    monkeypatch.setattr(app_module, "Transcriber", QuittingTranscriber)
    monkeypatch.setattr(app_module, "TextOutput", FakeOutput)
    monkeypatch.setattr(app_module, "Recorder", FakeRecorder)

    engine = DictationApp(Config())
    engine.start()
    assert engine._listener is None
    assert engine._watchdog_thread is None


def test_watchdog_discards_a_recording_orphaned_by_a_dead_listener(
    engine, monkeypatch
):
    """A listener that dies mid-hold must not leave the mic open.

    The release event never arrives, so without reconciliation the
    stream stays open, the buffer grows forever, and the next dictation
    pastes all of that stale audio at the cursor.
    """
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_SECONDS", 0.05)

    class DeadListener:
        alive = False

        def start(self):
            type(self).alive = True

        def stop(self):
            type(self).alive = False

    engine._listener = DeadListener()
    engine._paused = False
    engine.recorder.start()  # simulate a hold in progress
    assert engine.recorder.recording

    import threading

    engine._watchdog_thread = threading.Thread(target=engine._watchdog, daemon=True)
    engine._watchdog_thread.start()

    assert _wait_for(lambda: not engine.recorder.recording), "mic left open"
    assert DeadListener.alive, "listener was not restarted"


def test_watchdog_leaves_a_paused_listener_alone(engine, monkeypatch):
    """Pause must not be fought by the watchdog restarting the listener."""
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_SECONDS", 0.05)

    class FakeListener:
        def __init__(self):
            self.starts = 0
            self.alive = False

        def start(self):
            self.starts += 1
            self.alive = True

        def stop(self):
            self.alive = False

    listener = FakeListener()
    engine._listener = listener
    engine._paused = True
    import threading

    engine._watchdog_thread = threading.Thread(target=engine._watchdog, daemon=True)
    engine._watchdog_thread.start()
    time.sleep(0.3)
    assert listener.starts == 0

    # ...but a dead listener that is NOT paused gets revived
    engine._paused = False
    assert _wait_for(lambda: listener.starts >= 1)
