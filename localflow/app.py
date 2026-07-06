"""The LocalFlow dictation loop: hotkey -> record -> transcribe -> type."""

from __future__ import annotations

import queue
import threading
import time

from .config import Config
from .hotkeys import HotkeyListener
from .output import TextOutput
from .recorder import Recorder
from . import textproc
from .transcriber import Transcriber

# Ignore blips shorter than this (accidental taps of the hotkey).
MIN_UTTERANCE_SECONDS = 0.3


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
        self.ready = False

    # -- hotkey callbacks ------------------------------------------------

    def _on_start(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            print(f"[localflow] could not open microphone: {e}", flush=True)
            return
        self._started_at = time.monotonic()
        print("● recording... (release to transcribe)" if self.config.mode == "hold"
              else "● recording... (press hotkey again to stop)", flush=True)

    def _on_stop(self) -> None:
        audio = self.recorder.stop()
        duration = time.monotonic() - self._started_at
        if duration < MIN_UTTERANCE_SECONDS or audio.size == 0:
            print("  (too short, ignored)", flush=True)
            return
        self._jobs.put(audio)

    # -- transcription worker ---------------------------------------------

    def _worker(self) -> None:
        while True:
            audio = self._jobs.get()
            if audio is None:
                return
            t0 = time.monotonic()
            try:
                raw = self.transcriber.transcribe(audio)
            except Exception as e:
                print(f"[localflow] transcription failed: {e}", flush=True)
                continue
            text = textproc.process(
                raw,
                voice_commands=self.config.voice_commands,
                replacements=self.config.replacements,
                trailing_space=self.config.trailing_space,
            )
            elapsed = time.monotonic() - t0
            if not text:
                print(f"  (no speech detected, {elapsed:.1f}s)", flush=True)
                continue
            print(f"→ {text.strip()}  [{elapsed:.1f}s]", flush=True)
            try:
                self.output.send(text)
            except Exception as e:
                print(f"[localflow] could not deliver text: {e}", flush=True)

    # -- lifecycle ---------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self.recorder.recording

    def start(self) -> None:
        """Load the model and begin listening (non-blocking)."""
        self.transcriber.load()
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        self._listener = HotkeyListener(
            hotkey=self.config.hotkey,
            mode=self.config.mode,
            on_start=self._on_start,
            on_stop=self._on_stop,
        )
        self._listener.start()
        self.ready = True

    def pause(self) -> None:
        """Temporarily stop reacting to the hotkey."""
        if self._listener is not None:
            self._listener.stop()
        if self.recorder.recording:
            self.recorder.stop()

    def resume(self) -> None:
        if self._listener is not None:
            self._listener.start()

    def stop(self) -> None:
        self.pause()
        self._jobs.put(None)

    def run(self) -> None:
        """Blocking CLI mode."""
        print(f"[localflow] loading model '{self.config.model}'...", flush=True)
        self.start()
        action = "hold" if self.config.mode == "hold" else "press"
        print(
            f"[localflow] ready — {action} '{self.config.hotkey}' to dictate "
            f"(Ctrl+C to quit)",
            flush=True,
        )
        try:
            self._listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            print("\n[localflow] bye", flush=True)
