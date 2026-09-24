"""Project configuration (tuxsign.toml)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tuxsign.util import TuxError

CONFIG_NAME = "tuxsign.toml"

# Usage strings for every privacy-gated sensor/API. iOS kills the app if one
# of these APIs is touched without its key, so templates ship with all of them.
DEFAULT_USAGE = {
    "NSMotionUsageDescription": "Reads motion sensors (accelerometer, gyroscope, barometer, pedometer).",
    "NSLocationWhenInUseUsageDescription": "Shows your GPS position and compass heading.",
    "NSCameraUsageDescription": "Shows a live camera preview.",
    "NSMicrophoneUsageDescription": "Measures sound level from the microphone.",
    "NSFaceIDUsageDescription": "Unlocks with Face ID.",
    "NSBluetoothAlwaysUsageDescription": "Scans for nearby Bluetooth devices.",
    "NSPhotoLibraryAddUsageDescription": "Saves images to your photo library.",
}


@dataclass
class Project:
    root: Path
    name: str
    bundle_id: str
    kind: str  # "swiftui" | "html"
    version: str = "1.0"
    build: str = "1"
    min_ios: str = "26.0"
    display_name: str | None = None
    sources: str = "Sources"
    web_root: str = "www"
    icon: str | None = None
    orientation: list[str] = field(default_factory=lambda: ["portrait", "landscape"])
    frameworks: list[str] = field(default_factory=list)
    usage: dict[str, str] = field(default_factory=dict)
    info_plist: dict = field(default_factory=dict)
    entitlements: dict = field(default_factory=dict)

    @property
    def executable(self) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "", self.name) or "App"

    @property
    def build_dir(self) -> Path:
        return self.root / "build"


def load(root: Path | str = ".") -> Project:
    root = Path(root).resolve()
    path = root / CONFIG_NAME
    if not path.is_file():
        raise TuxError(f"no {CONFIG_NAME} in {root} (create a project with `tuxsign new`)")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise TuxError(f"{path}: {exc}") from exc

    app = data.get("app", {})
    for key in ("name", "bundle_id", "kind"):
        if key not in app:
            raise TuxError(f"{path}: [app] is missing `{key}`")
    if app["kind"] not in ("swiftui", "html"):
        raise TuxError(f"{path}: kind must be 'swiftui' or 'html'")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", app["bundle_id"]):
        raise TuxError(f"{path}: invalid bundle_id {app['bundle_id']!r}")

    known = {f for f in Project.__dataclass_fields__ if f not in ("root", "usage", "info_plist", "entitlements")}
    return Project(
        root=root,
        **{k: v for k, v in app.items() if k in known},
        usage={**DEFAULT_USAGE, **data.get("usage", {})},
        info_plist=data.get("info_plist", {}),
        entitlements=data.get("entitlements", {}),
    )
