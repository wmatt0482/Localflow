# PyInstaller spec that bundles LocalFlow into a standalone macOS app.
# Build with:  pyinstaller --noconfirm packaging/LocalFlow.spec
# (or just run ./build_app.command)

import os

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# These packages ship native libraries and data files PyInstaller's
# static analysis misses.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
]

a = Analysis(
    [os.path.join(SPECPATH, "tray_entry.py")],
    pathex=[os.path.join(SPECPATH, "..")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="LocalFlow",
    console=False,
    target_arch=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name="LocalFlow")

app = BUNDLE(
    coll,
    name="LocalFlow.app",
    icon=None,
    bundle_identifier="io.github.wmatt0482.localflow",
    info_plist={
        # Menu-bar-only app: no Dock icon, no app switcher entry.
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": (
            "LocalFlow records your voice while you hold the dictation "
            "hotkey. Audio never leaves this Mac."
        ),
        "NSHumanReadableCopyright": "MIT license",
    },
)
