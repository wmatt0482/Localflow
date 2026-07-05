import pytest

# On headless machines pynput imports but fails to find a display backend.
pynput = pytest.importorskip("pynput", exc_type=ImportError)

from localflow.hotkeys import HotkeyListener, parse_hotkey  # noqa: E402
from pynput.keyboard import Key, KeyCode  # noqa: E402


def test_parse_named_key():
    assert parse_hotkey("ctrl_r") is Key.ctrl_r
    assert parse_hotkey("f9") is Key.f9


def test_parse_single_char():
    key = parse_hotkey("v")
    assert isinstance(key, KeyCode)
    assert key.char == "v"


def test_parse_unknown_raises():
    with pytest.raises(ValueError, match="Unknown hotkey"):
        parse_hotkey("not_a_key")


def _listener(mode: str):
    events: list[str] = []
    listener = HotkeyListener(
        "f9",
        mode,
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
    )
    return listener, events


def test_hold_mode_press_release():
    listener, events = _listener("hold")
    listener._on_press(Key.f9)
    listener._on_release(Key.f9)
    assert events == ["start", "stop"]


def test_hold_mode_ignores_key_repeat():
    listener, events = _listener("hold")
    listener._on_press(Key.f9)
    listener._on_press(Key.f9)  # OS auto-repeat while held
    listener._on_release(Key.f9)
    assert events == ["start", "stop"]


def test_hold_mode_ignores_other_keys():
    listener, events = _listener("hold")
    listener._on_press(Key.f8)
    listener._on_release(Key.f8)
    assert events == []


def test_toggle_mode():
    listener, events = _listener("toggle")
    listener._on_press(Key.f9)
    listener._on_release(Key.f9)
    listener._on_press(Key.f9)
    listener._on_release(Key.f9)
    assert events == ["start", "stop"]
