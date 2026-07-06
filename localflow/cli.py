"""Command-line interface for LocalFlow."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, Config, load_config


EXAMPLE_CONFIG = '''\
# LocalFlow configuration. All keys are optional.

model = "base.en"        # tiny/base/small/medium/large-v3 (+.en variants)
device = "auto"          # "auto", "cpu" or "cuda"
# language = "en"        # omit to auto-detect

# hotkey = "cmd_r"       # default: "cmd_r" (right Cmd) on macOS, "ctrl_r"
                         # elsewhere; also e.g. "f9", "pause", "scroll_lock"
mode = "hold"            # "hold" (push-to-talk) or "toggle"

output = "paste"         # "paste" (Ctrl+V) or "type" (simulated keystrokes)
trailing_space = true
restore_clipboard = true

voice_commands = true    # say "new line" / "new paragraph"

[replacements]           # fix words Whisper gets wrong, case-insensitive
# "local flow" = "LocalFlow"
'''


def _add_override_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=None,
                        help=f"config file (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--model", help="Whisper model (e.g. tiny.en, base.en, small)")
    parser.add_argument("--device", help="auto | cpu | cuda")
    parser.add_argument("--language", help="language code, e.g. en")


def _build_config(args: argparse.Namespace) -> Config:
    config = load_config(getattr(args, "config", None))
    for name in ("model", "device", "language", "hotkey", "mode", "output"):
        value = getattr(args, name, None)
        if value is not None:
            config = dataclasses.replace(config, **{name: value})
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="localflow",
        description="Private, fully-local voice dictation. "
        "Hold a key, speak, and the words appear where your cursor is.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start the dictation hotkey daemon (default)")
    _add_override_args(run)
    run.add_argument("--hotkey", help="hotkey name, e.g. ctrl_r or f9")
    run.add_argument("--mode", choices=["hold", "toggle"])
    run.add_argument("--output", choices=["paste", "type"])

    transcribe = sub.add_parser("transcribe", help="transcribe an audio file to stdout")
    _add_override_args(transcribe)
    transcribe.add_argument("file", type=Path, help="audio file (wav/mp3/m4a/...)")

    init = sub.add_parser("init", help="write an example config file")
    init.add_argument("--config", type=Path, default=None,
                      help=f"where to write it (default: {DEFAULT_CONFIG_PATH})")

    args = parser.parse_args(argv)
    command = args.command or "run"

    if command == "init":
        path = args.config or DEFAULT_CONFIG_PATH
        if path.exists():
            print(f"refusing to overwrite existing {path}", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(EXAMPLE_CONFIG)
        print(f"wrote {path}")
        return 0

    if command == "transcribe":
        config = _build_config(args)
        if not args.file.is_file():
            print(f"no such file: {args.file}", file=sys.stderr)
            return 1
        from .transcriber import Transcriber
        from . import textproc

        t = Transcriber(
            model=config.model,
            device=config.device,
            compute_type=config.compute_type,
            language=config.language,
        )
        text = textproc.process(
            t.transcribe(args.file),
            voice_commands=config.voice_commands,
            replacements=config.replacements,
        )
        print(text)
        return 0

    # run (default when no subcommand is given)
    config = _build_config(args)
    from .app import DictationApp

    DictationApp(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
