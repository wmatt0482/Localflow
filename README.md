# LocalFlow

A private, fully-local voice dictation app — an open alternative to Whisper Flow.
Hold a hotkey, speak, release: your words are transcribed by a **local Whisper
model** and typed into whatever app has focus. No account, no subscription, and
**no audio ever leaves your machine**.

## How it works

```
hotkey (pynput) ──> mic capture (sounddevice, 16 kHz mono)
                        │ release / toggle off
                        ▼
        faster-whisper (CTranslate2, runs on CPU or CUDA)
                        │ text
                        ▼
   post-processing (voice commands, custom replacements)
                        │
                        ▼
  clipboard paste or simulated keystrokes into the focused app
```

## Install

Requires Python 3.10+ and a working microphone.

```bash
pip install .
```

Platform notes:

- **Linux**: needs PortAudio (`sudo apt install libportaudio2`) and, for the
  clipboard, `xclip` or `xsel` (`sudo apt install xclip`). Global hotkeys work
  out of the box on X11 sessions; on pure Wayland, pynput needs XWayland.
- **macOS**: grant your terminal **Accessibility** and **Microphone**
  permissions (System Settings → Privacy & Security). Both are required for
  global hotkeys and keystroke injection.
- **Windows**: works out of the box.

The first run downloads the Whisper model (~75 MB for `base.en`) to the local
Hugging Face cache; after that it's fully offline.

## Use

```bash
localflow                 # start the dictation daemon
```

Hold **Right Ctrl**, speak, release — the transcribed text appears at your
cursor. `Ctrl+C` quits.

Options:

```bash
localflow run --model small.en --hotkey f9 --mode toggle
localflow transcribe meeting.m4a        # transcribe a file to stdout
localflow init                          # write an example config file
```

## Configuration

`localflow init` writes `~/.config/localflow/config.toml`:

```toml
model = "base.en"        # tiny/base/small/medium/large-v3 (+.en variants)
device = "auto"          # "auto", "cpu" or "cuda"

hotkey = "ctrl_r"        # e.g. "ctrl_r", "f9", "pause", "scroll_lock"
mode = "hold"            # "hold" (push-to-talk) or "toggle"

output = "paste"         # "paste" (Ctrl+V) or "type" (simulated keystrokes)
trailing_space = true
restore_clipboard = true

voice_commands = true    # say "new line" / "new paragraph"

[replacements]           # fix words Whisper mishears, case-insensitive
"local flow" = "LocalFlow"
```

### Picking a model

| Model      | Size    | Speed on CPU | Quality              |
|------------|---------|--------------|----------------------|
| `tiny.en`  | ~39 MB  | fastest      | okay for quick notes |
| `base.en`  | ~75 MB  | fast         | good default         |
| `small.en` | ~250 MB | moderate     | very good            |
| `medium.en`| ~770 MB | slow on CPU  | excellent            |
| `large-v3` | ~1.6 GB | needs GPU    | best, multilingual   |

With CUDA (`device = "cuda"`), even `large-v3` transcribes a sentence in well
under a second.

## Voice commands

While dictating you can say **"new line"** or **"new paragraph"** to insert
line breaks. Whisper itself handles punctuation and capitalization.

## Development

```bash
pip install -e .[dev]
pytest
```

The audio, hotkey and clipboard dependencies are imported lazily, so
`localflow transcribe` and the test suite also work on headless machines.

## License

MIT. Not affiliated with Whisper Flow — this is an independent, local
reimplementation of the same idea on top of OpenAI's open-source Whisper
models.
