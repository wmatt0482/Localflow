"""Microphone capture.

PortAudio's device snapshot and CoreAudio's stop path are both
hazards here; see the comments in start() and stop_with_timeout().

Records mono float32 audio at 16 kHz (what Whisper expects) into memory.
Import of ``sounddevice`` is deferred so file-only workflows (e.g.
``localflow transcribe file.wav``) work on machines without PortAudio.
"""

from __future__ import annotations

import threading
import time

import numpy as np

# How long the cached device list may go unused before a refresh.
REFRESH_AFTER_IDLE_SECONDS = 30.0


class Recorder:
    """Start/stop microphone recording; returns captured audio as ndarray."""

    def __init__(self, sample_rate: int = 16000, device: str | int | None = None):
        self.sample_rate = sample_rate
        self.device = device
        self._frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        # What the last capture actually got, for the silence check.
        self.last_device_name: str | None = None
        self.last_peak = 0.0
        self._last_refresh = 0.0

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

        # PortAudio snapshots the device list and the default input at
        # initialisation and never revisits them. After a device is slept,
        # unplugged or replugged, the cached default can point at a device
        # that is gone or silent, and opening it raises nothing - it just
        # records zeros. Re-initialising costs about 5 ms, so do it
        # whenever the snapshot has had time to go stale.
        now = time.monotonic()
        if now - self._last_refresh > REFRESH_AFTER_IDLE_SECONDS:
            try:
                if getattr(sd, "_initialized", 0) > 0:
                    sd._terminate()
                sd._initialize()
                self._last_refresh = now
            except Exception as e:
                # A failed refresh must not stop us trying the open.
                print(f"[localflow] could not refresh audio devices: {e}", flush=True)

        def open_stream():
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.device,
                callback=callback,
            )
            stream.start()
            return stream

        try:
            self._stream = open_stream()
        except (sd.PortAudioError, ValueError):
            # PortAudio's device state goes stale after the machine sleeps
            # or audio devices come and go, and every open then fails with
            # an internal error (-9986) until PortAudio is reinitialized.
            print(
                "[localflow] audio device list stale — reinitializing",
                flush=True,
            )
            sd._terminate()
            sd._initialize()
            self._last_refresh = time.monotonic()
            self._stream = open_stream()
        try:
            self.last_device_name = sd.query_devices(self._stream.device)["name"]
        except Exception:
            self.last_device_name = None

    def stop(self) -> np.ndarray:
        """Stop recording and return the audio as a 1-D float32 array."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            frames, self._frames = self._frames, []
        if not frames:
            self.last_peak = 0.0
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(frames).reshape(-1)
        self.last_peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        return audio

    def stop_with_timeout(self, timeout: float):
        """Stop the stream, giving up if CoreAudio deadlocks.

        macOS can block forever inside PortAudio's FinishStoppingStream
        when the device disappears mid-stop, holding a HAL mutex that is
        never released. The blocked thread cannot be killed, so run the
        stop somewhere disposable and abandon it on timeout rather than
        wedging the audio worker for the rest of the session.

        Returns (audio, timed_out). On timeout the caller must assume the
        whole PortAudio state is unusable.
        """
        result: dict = {}

        def run() -> None:
            try:
                result["audio"] = self.stop()
            except BaseException as e:  # noqa: BLE001 - reported to the caller
                result["error"] = e

        # self.stop() clears the stream reference first, so `recording` is
        # False as soon as this starts, even if the close blocks.
        worker = threading.Thread(
            target=run, name="localflow-mic-stop", daemon=True
        )
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return None, True
        if "error" in result:
            raise result["error"]
        return result.get("audio", np.zeros(0, dtype=np.float32)), False
