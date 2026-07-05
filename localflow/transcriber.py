"""Local speech-to-text built on faster-whisper (CTranslate2 Whisper).

The model is loaded once and kept warm; transcription accepts either a
numpy array of 16 kHz mono float32 audio or a path to an audio file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class Transcriber:
    def __init__(
        self,
        model: str = "base.en",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
    ):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def load(self) -> None:
        """Load the Whisper model (downloads it on first use)."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        compute_type = self.compute_type
        if compute_type == "auto":
            # int8 is the best speed/quality trade-off on CPU; let
            # CTranslate2 decide ("default") when a GPU is in play.
            compute_type = "int8" if self.device in ("cpu", "auto") else "default"
        self._model = WhisperModel(
            self.model_name, device=self.device, compute_type=compute_type
        )

    def transcribe(self, audio: np.ndarray | str | Path) -> str:
        """Transcribe audio and return the raw text (Whisper already adds
        punctuation and capitalization)."""
        self.load()
        if isinstance(audio, Path):
            audio = str(audio)
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
