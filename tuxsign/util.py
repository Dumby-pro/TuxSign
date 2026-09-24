"""Small shared helpers: logging, subprocess, paths."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("TUXSIGN_HOME", Path.home() / ".local" / "share" / "tuxsign"))

_COLOR = sys.stderr.isatty() and not os.environ.get("NO_COLOR")


class TuxError(Exception):
    """An expected, user-facing error (printed without a traceback)."""


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(msg: str) -> None:
    print(_paint("1;34", "==>") + " " + msg, file=sys.stderr)


def ok(msg: str) -> None:
    print(_paint("1;32", " ✓ ") + msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(_paint("1;33", " ! ") + msg, file=sys.stderr)


def which(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
        capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command, raising TuxError with its output if it fails."""
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        raise TuxError(f"command failed ({proc.returncode}): {' '.join(map(str, cmd))}"
                       + (f"\n{detail}" if detail else ""))
    return proc
