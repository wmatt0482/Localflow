"""PyInstaller entry point for the LocalFlow menu-bar app."""

import multiprocessing
import sys

# multiprocessing helpers re-exec this same binary. Left unhandled, every
# helper boots the full tray app, which spawns a helper of its own — a fork
# bomb. freeze_support() intercepts spawned workers; the block below
# intercepts the resource tracker / forkserver, which are launched as
#   LocalFlow -B -S -I -c "from multiprocessing.resource_tracker import main;main(fd)"
# and which PyInstaller's own runtime hook fails to divert here.
multiprocessing.freeze_support()

if "-c" in sys.argv[1:]:
    _i = sys.argv.index("-c")
    _cmd = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else ""
    if _cmd.startswith(
        ("from multiprocessing", "import sys; from multiprocessing")
    ):
        sys.argv[:] = sys.argv[:1] + sys.argv[_i + 2 :]
        exec(_cmd)
        sys.exit(0)

from localflow.tray import main

raise SystemExit(main())
