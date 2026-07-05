"""Configuration loading for LocalFlow.

Settings are read from a TOML file (default:
``~/.config/localflow/config.toml``), then overridden by CLI flags.
"""

from __future__ import annotations

import dataclasses
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "localflow" / "config.toml"


@dataclass
class Config:
    # Whisper model: tiny/base/small/medium/large-v3, or the *.en variants,
    # or a path/HF repo id accepted by faster-whisper.
    model: str = "base.en"
    # "auto" picks CUDA if available, else CPU.
    device: str = "auto"
    # "auto" picks a sensible precision for the device (int8 on CPU).
    compute_type: str = "auto"
    # Language code like "en"; None lets Whisper auto-detect.
    language: str | None = None

    # Hotkey that starts/stops recording. Names from pynput's Key enum
    # (e.g. "ctrl_r", "f9", "pause") or a single character.
    hotkey: str = "ctrl_r"
    # "hold": record while the key is held. "toggle": press to start,
    # press again to stop.
    mode: str = "hold"

    # "paste": copy to clipboard and press Ctrl+V (fast, reliable with
    # emoji/accents). "type": simulate individual keystrokes.
    output: str = "paste"
    # Append this after each utterance so consecutive dictations don't
    # run together.
    trailing_space: bool = True
    # Restore the previous clipboard contents after pasting.
    restore_clipboard: bool = True

    # Microphone device index or name substring; None = system default.
    input_device: str | int | None = None
    sample_rate: int = 16000

    # Spoken commands like "new line" / "new paragraph".
    voice_commands: bool = True
    # Case-insensitive text replacements applied after transcription,
    # e.g. { "local flow" = "LocalFlow" }. Useful for names and jargon
    # Whisper gets wrong.
    replacements: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ("hold", "toggle"):
            raise ValueError(f"mode must be 'hold' or 'toggle', got {self.mode!r}")
        if self.output not in ("paste", "type"):
            raise ValueError(f"output must be 'paste' or 'type', got {self.output!r}")


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults for missing keys.

    Unknown keys are rejected so typos don't fail silently.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if config_path.is_file():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

    known = {f.name for f in dataclasses.fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"Unknown config key(s) in {config_path}: {', '.join(sorted(unknown))}"
        )
    return Config(**data)
