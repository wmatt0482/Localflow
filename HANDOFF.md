# HANDOFF — for a Claude Code session running locally on Matt's Mac

You are picking up work started in a cloud session that could not touch
this machine. Read this whole file before running anything. The goal:
finish turning LocalFlow into an installed, always-available Mac app,
and fix one unrelated broken launchd service. Work autonomously; verify
each step by actually exercising it.

## Machine facts (learned the hard way — trust these)

- Mac hostname `NightHawk11`, user `Matt`, login shell is **bash**, not zsh.
- `python3` is **Homebrew Python 3.12** and is externally managed:
  bare `pip install` fails with `externally-managed-environment`.
  Always use the repo's `.venv` (already created at `~/localflow/.venv`).
- There is **no `pip` on PATH** outside a venv.
- Keyboard is a Mac keyboard — **no right Ctrl key**. The dictation
  hotkey default is `cmd_r` (right ⌘) on macOS for this reason.
- Terminal.app had NOT been granted Accessibility as of handoff; the
  user was walked through System Settings → Privacy & Security →
  Accessibility → enable Terminal, but the final state is unverified.
  pynput prints "This process is not trusted!" when it's missing.

## Project 1: LocalFlow (~/localflow, github.com/wmatt0482/localflow)

Private, fully-local voice dictation (open Whisper Flow alternative).
Hold right ⌘ → mic records → faster-whisper transcribes on-device →
text is pasted into the focused app. Python 3.10+, MIT.

Architecture (all small files, read them as needed):

- `localflow/app.py` — DictationApp engine: `start()/pause()/resume()/stop()`
  lifecycle + blocking `run()` for the CLI. Transcription happens on a
  worker thread fed by a queue.
- `localflow/recorder.py` — sounddevice mic capture, 16 kHz mono f32.
- `localflow/transcriber.py` — faster-whisper wrapper (model `base.en`
  default, int8 on CPU, `vad_filter=True`). First use downloads ~75 MB
  from Hugging Face to the HF cache.
- `localflow/hotkeys.py` — pynput global hotkey; hold and toggle modes.
- `localflow/output.py` — clipboard-paste (Cmd+V on macOS, restores old
  clipboard) or keystroke typing.
- `localflow/textproc.py` — "new line"/"new paragraph" voice commands,
  user replacement dictionary.
- `localflow/tray.py` — rumps menu-bar app (🎤 idle / 🔴 recording /
  ⏳ loading / ⏸ paused). UI state synced via rumps.Timer polling —
  do not touch AppKit from worker threads.
- `localflow/cli.py` — `localflow` (run daemon), `localflow transcribe
  FILE`, `localflow init` (writes example config). Config lives at
  `~/.config/localflow/config.toml`, TOML, CLI flags override.
- `LocalFlow.command` — double-click launcher: creates .venv, editable
  install, runs CLI daemon.
- `build_app.command` + `packaging/LocalFlow.spec` + `packaging/tray_entry.py`
  — PyInstaller build of standalone `dist/LocalFlow.app` (menu-bar only,
  LSUIElement, NSMicrophoneUsageDescription set).
- `tests/` — 27 tests, all passing on Linux. `python -m pytest tests/ -q`.

Current verified state: CLI dictation ran on this Mac up to the
Accessibility permission step (model downloaded, hotkey armed, then
"process is not trusted"). Everything below is **not yet verified**.

### Task 1 (main): build, install, and verify LocalFlow.app

1. `cd ~/localflow && git pull`.
2. Run `./build_app.command`. It pip-installs `.[macapp]` (rumps,
   pyinstaller) into .venv and runs PyInstaller on
   `packaging/LocalFlow.spec`.
3. Expect PyInstaller trouble; the spec was written blind on Linux.
   Known risk areas: `collect_all` for `faster_whisper`, `ctranslate2`,
   `onnxruntime`, `av`, `tokenizers`; pynput darwin backends are added
   as hiddenimports. Fix the spec as needed and keep it working for
   rebuilds.
4. Smoke-test the bundle from a terminal first:
   `./dist/LocalFlow.app/Contents/MacOS/LocalFlow` — watch stdout for
   the model load and any missing-module tracebacks.
5. Install: `cp -R dist/LocalFlow.app /Applications/` (or drag).
6. Launch from Spotlight. Verify: ⏳ appears in the menu bar, becomes 🎤.
   macOS will prompt for Microphone; Accessibility must be granted to
   **LocalFlow** (System Settings → Privacy & Security → Accessibility).
   The app may need a relaunch after granting.
7. End-to-end check: open Notes, hold right ⌘, speak "testing local
   flow new line second line", release. Text should appear with a line
   break. Also verify 🔴 shows while held and Pause/Resume/Quit work
   from the menu.
8. If the user wants it at login: System Settings → General → Login
   Items → add LocalFlow.
9. Commit and push any spec/build fixes to `main`.

### LocalFlow gotchas

- The venv at ~/localflow/.venv already has the non-editable install
  from earlier; `LocalFlow.command`/`build_app.command` reinstall
  editable — that's intended.
- If dictation types nothing but the log shows a transcription, it's
  the Accessibility permission on whatever process is delivering
  keystrokes (Terminal for CLI, LocalFlow.app for the bundle).
- Whisper `base.en` is the default; `small.en` is noticeably better if
  the user complains about accuracy (config: `model = "small.en"`).
- pyperclip uses pbcopy/pbpaste on macOS — no extra deps needed.

## Project 2: fix the "Extra" launchd service (~/extra, github.com/wmatt0482/Extra)

Separate Next.js app (Todoist/Outlook dashboard) from another session.
Its installer (`scripts/install-mac.sh`, branch `claude/extra-v0`)
manages a launchd agent `com.wmatt.extra` (plist at
`~/Library/LaunchAgents/com.wmatt.extra.plist`, serves
http://localhost:3000, logs to `~/Library/Logs/extra.log`).

Symptoms at handoff:
- Third reinstall printed `Load failed: 5: Input/output error` from
  `launchctl bootstrap`, then the 30 s health check failed.
- `launchctl kickstart -k gui/$(id -u)/com.wmatt.extra` →
  "Could not find service" — so nothing is loaded now.

To do:
1. Diagnose locally: `plutil -lint` the plist, check
   `launchctl print-disabled gui/$(id -u)` for the label,
   `launchctl enable` + `launchctl bootstrap gui/$(id -u) <plist>`,
   read `~/Library/Logs/extra.log`. Get it serving on :3000.
2. Patch `scripts/install-mac.sh` so reinstalls are idempotent:
   `launchctl bootout gui/$(id -u)/com.wmatt.extra 2>/dev/null || true`
   before bootstrap, plus `launchctl enable`, and make the health check
   distinguish "old instance still running" from "new instance up".
   Commit/push to the branch the repo is on (`claude/extra-v0`).
3. SECURITY: the user's Todoist API token was pasted into a chat
   session and may be compromised. If they haven't rotated it, remind
   them: Todoist → Settings → Integrations → Developer → reset, then
   update `~/extra/.env.local` and restart the service.

## Loose ends, small

- `wmatt0482/blender_mcp` has a stale remote branch
  `claude/local-whisper-flow-k4fi9t` (its PR #1 is closed; the code
  moved to the localflow repo). Delete it: the "Delete branch" button
  on the closed PR, or `git push origin --delete ...` from a machine
  with normal GitHub credentials.

## Working agreements

- Ask before anything destructive or system-level beyond what's listed.
- Verify by running the actual flow, not just builds/tests.
- Push working fixes to the repos so the cloud session stays in sync.
