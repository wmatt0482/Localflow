"""The LocalFlow dictation loop: hotkey -> record -> transcribe -> type."""

from __future__ import annotations

import queue
import threading
import time

from .applog import exception as log_exception, log
from .config import Config
from .hotkeys import HotkeyListener
from .output import TextOutput
from .recorder import Recorder
from . import textproc
from .transcriber import Transcriber

# Ignore blips shorter than this (accidental taps of the hotkey).
MIN_UTTERANCE_SECONDS = 0.3

# How often to check that the background threads are still alive.
WATCHDOG_INTERVAL_SECONDS = 15.0


class DictationApp:
    def __init__(self, config: Config):
        self.config = config
        self.recorder = Recorder(
            sample_rate=config.sample_rate, device=config.input_device
        )
        self.transcriber = Transcriber(
            model=config.model,
            device=config.device,
            compute_type=config.compute_type,
            language=config.language,
        )
        self.output = TextOutput(
            method=config.output, restore_clipboard=config.restore_clipboard
        )
        self._jobs: queue.Queue = queue.Queue()
        self._started_at = 0.0
        self._listener: HotkeyListener | None = None
        self._worker_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._paused = False
        self.ready = False

    # -- hotkey callbacks ------------------------------------------------

    def _on_start(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            log(f"[localflow] could not open microphone: {e}")
            return
        self._started_at = time.monotonic()
        log("● recording... (release to transcribe)" if self.config.mode == "hold"
            else "● recording... (press hotkey again to stop)")

    def _on_stop(self) -> None:
        audio = self.recorder.stop()
        duration = time.monotonic() - self._started_at
        if duration < MIN_UTTERANCE_SECONDS or audio.size == 0:
            log("  (too short, ignored)")
            return
        self._jobs.put(audio)

    # -- transcription worker ---------------------------------------------

    def _handle_job(self, audio) -> None:
        t0 = time.monotonic()
        try:
            raw = self.transcriber.transcribe(audio)
        except Exception as e:
            log_exception(f"[localflow] transcription failed: {e}")
            return
        text = textproc.process(
            raw,
            voice_commands=self.config.voice_commands,
            replacements=self.config.replacements,
            trailing_space=self.config.trailing_space,
        )
        elapsed = time.monotonic() - t0
        if not text:
            log(f"  (no speech detected, {elapsed:.1f}s)")
            return
        log(f"→ {text.strip()}  [{elapsed:.1f}s]")
        try:
            self.output.send(text)
        except Exception as e:
            log_exception(f"[localflow] could not deliver text: {e}")

    def _worker(self) -> None:
        while True:
            audio = self._jobs.get()
            if audio is None:
                return
            # A single bad utterance must never take the worker down with
            # it: if this thread dies the hotkey still records and the icon
            # still blinks, but no text is ever produced again.
            try:
                self._handle_job(audio)
            except Exception as e:
                log_exception(f"[localflow] error handling recording: {e}")

    # -- watchdog ----------------------------------------------------------

    @property
    def healthy(self) -> bool:
        """Whether both background threads are running (or intentionally
        paused)."""
        worker_ok = self._worker_thread is not None and self._worker_thread.is_alive()
        listener_ok = self._paused or (
            self._listener is not None and self._listener.alive
        )
        return worker_ok and listener_ok

    def _abort_recording(self) -> None:
        """Drop an in-flight recording that can never be completed.

        If the listener dies mid-hold, no release event will arrive, so
        the microphone would stay open forever, the buffer would grow
        without bound, and the next dictation would paste all of that
        stale audio at the cursor. Throw it away instead.
        """
        if self.recorder.recording:
            self.recorder.stop()
            log("[localflow] discarded an interrupted recording")

    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(
            target=self._worker, name="localflow-transcriber", daemon=True
        )
        self._worker_thread.start()

    def _watchdog(self) -> None:
        """Revive background threads that died.

        Long-running sessions lose the pynput event tap (macOS disables it
        after a system event or a slow callback) and, before the hardening
        above, could lose the transcription worker to an unhandled error.
        Both failures are silent, so poll instead of trusting them.
        """
        while not self._stopping.wait(WATCHDOG_INTERVAL_SECONDS):
            try:
                if self._worker_thread is not None and not self._worker_thread.is_alive():
                    log("[localflow] transcription worker died — restarting")
                    self._start_worker()
                if (
                    not self._paused
                    and self._listener is not None
                    and not self._listener.alive
                ):
                    log("[localflow] hotkey listener died — restarting")
                    # Do this BEFORE restarting: the restart clears the
                    # listener's "key is held" state, so the release that
                    # would have stopped this recording never arrives.
                    self._abort_recording()
                    self._listener.start()
            except Exception as e:
                log_exception(f"[localflow] watchdog error: {e}")

    # -- lifecycle ---------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self.recorder.recording

    def start(self) -> None:
        """Load the model and begin listening (non-blocking)."""
        self.transcriber.load()
        # Loading the model takes seconds (minutes on the first run, which
        # downloads it), and the menu is live the whole time. Honour a
        # Pause or Quit chosen during that window instead of arming a
        # hotkey the user has already switched off.
        if self._stopping.is_set():
            return
        self._start_worker()
        self._listener = HotkeyListener(
            hotkey=self.config.hotkey,
            mode=self.config.mode,
            on_start=self._on_start,
            on_stop=self._on_stop,
        )
        if not self._paused:
            self._listener.start()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog, name="localflow-watchdog", daemon=True
        )
        self._watchdog_thread.start()
        self.ready = True

    def pause(self) -> None:
        """Temporarily stop reacting to the hotkey."""
        self._paused = True
        if self._listener is not None:
            self._listener.stop()
        if self.recorder.recording:
            self.recorder.stop()

    def resume(self) -> None:
        self._paused = False
        if self._listener is not None:
            self._listener.start()

    def stop(self) -> None:
        self._stopping.set()
        self.pause()
        self._jobs.put(None)

    def run(self) -> None:
        """Blocking CLI mode."""
        from .applog import setup as setup_logging
        from .hotkeys import prime_keycode_context

        setup_logging()
        prime_keycode_context()
        log(f"[localflow] loading model '{self.config.model}'...")
        self.start()
        action = "hold" if self.config.mode == "hold" else "press"
        log(
            f"[localflow] ready — {action} '{self.config.hotkey}' to dictate "
            f"(Ctrl+C to quit)"
        )
        try:
            while not self._stopping.is_set():
                # Not listener.join(): the watchdog may replace the
                # listener object, and joining a stale one would return
                # early and quit the app while it is still working.
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            print("\n[localflow] bye", flush=True)
