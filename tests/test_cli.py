from pathlib import Path

from localflow import cli


def test_init_writes_example_config(tmp_path: Path, capsys):
    path = tmp_path / "config.toml"
    assert cli.main(["init", "--config", str(path)]) == 0
    assert 'model = "base.en"' in path.read_text()


def test_init_refuses_overwrite(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("model = 'small'\n")
    assert cli.main(["init", "--config", str(path)]) == 1
    assert path.read_text() == "model = 'small'\n"


def test_transcribe_missing_file(tmp_path: Path, capsys):
    rc = cli.main(
        ["transcribe", "--config", str(tmp_path / "none.toml"), "missing.wav"]
    )
    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_transcribe_pipeline(tmp_path: Path, capsys, monkeypatch):
    """CLI wires file -> transcriber -> post-processing -> stdout."""

    class FakeTranscriber:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def transcribe(self, audio):
            return "hello new line world"

    monkeypatch.setattr("localflow.transcriber.Transcriber", FakeTranscriber)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00")
    config = tmp_path / "config.toml"
    config.write_text('model = "tiny.en"\n')

    rc = cli.main(["transcribe", "--config", str(config), str(audio)])
    assert rc == 0
    assert capsys.readouterr().out == "hello\nworld\n"


def test_config_overrides_from_flags(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeTranscriber:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def transcribe(self, audio):
            return ""

    monkeypatch.setattr("localflow.transcriber.Transcriber", FakeTranscriber)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"\x00")
    rc = cli.main(
        [
            "transcribe",
            "--config", str(tmp_path / "none.toml"),
            "--model", "small",
            "--language", "en",
            str(audio),
        ]
    )
    assert rc == 0
    assert captured["model"] == "small"
    assert captured["language"] == "en"
