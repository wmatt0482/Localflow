"""Microphone capture.

Records mono float32 audio at 16 kHz (what Whisper expects) into memory.
Import of ``sounddevice`` is deferred so file-only workflows (e.g.
``localflow transcribe file.wav``) work on machines without PortAudio.
"""

from __future__ import annotations

import threading

import numpy as np


class Recorder:
    """Start/stop microphone recording; returns captured audio as ndarray."""

    def __init__(self, sample_rate: int = 16000, device: str | int | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        self._frames = []

        def callback(indata, frames, time_info, status):
            if status:
                # Overflows etc. are worth surfacing but not fatal.
                print(f"[localflow] audio status: {status}", flush=True)
            with self._lock:
                self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return the audio as a 1-D float32 array."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            frames, self._frames = self._frames, []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).reshape(-1)
