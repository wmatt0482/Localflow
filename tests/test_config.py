from pathlib import Path

import pytest

from localflow.config import Config, load_config


def test_defaults_when_no_file(tmp_path: Path):
    config = load_config(tmp_path / "missing.toml")
    assert config.model == "base.en"
    assert config.mode == "hold"
    assert config.output == "paste"


def test_load_from_toml(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        'model = "small"\n'
        'hotkey = "f9"\n'
        'mode = "toggle"\n'
        "[replacements]\n"
        '"local flow" = "LocalFlow"\n'
    )
    config = load_config(path)
    assert config.model == "small"
    assert config.hotkey == "f9"
    assert config.mode == "toggle"
    assert config.replacements == {"local flow": "LocalFlow"}


def test_unknown_key_rejected(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('modell = "small"\n')
    with pytest.raises(ValueError, match="modell"):
        load_config(path)


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        Config(mode="sideways")


def test_invalid_output_rejected():
    with pytest.raises(ValueError, match="output"):
        Config(output="telepathy")
