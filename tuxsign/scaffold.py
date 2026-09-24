"""`tuxsign new` - create projects from the bundled templates."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from tuxsign.util import TuxError, ok

TEMPLATES = Path(__file__).parent / "templates"
COMMON = TEMPLATES / "common"


def create(dest: Path, name: str, kind: str, bundle_id: str | None = None) -> Path:
    if kind not in ("swiftui", "html"):
        raise TuxError("template must be 'swiftui' or 'html'")
    if dest.exists() and any(dest.iterdir()):
        raise TuxError(f"{dest} already exists and is not empty")
    ident = re.sub(r"[^A-Za-z0-9]", "", name) or "App"
    values = {
        "NAME": name,
        "IDENT": ident,
        "BUNDLE_ID": bundle_id or f"com.tuxsign.{ident.lower()}",
        "KIND": kind,
    }
    for src_root in (COMMON, TEMPLATES / kind):
        for src in src_root.rglob("*"):
            if src.is_dir() or "__pycache__" in src.parts:
                continue
            rel = Path(*(part.replace("_dot_", ".") for part in src.relative_to(src_root).parts))
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                text = src.read_text()
            except UnicodeDecodeError:
                shutil.copyfile(src, target)
                continue
            for key, val in values.items():
                text = text.replace("{{" + key + "}}", val)
            target.write_text(text)
    ok(f"created {kind} app '{name}' in {dest}")
    return dest
