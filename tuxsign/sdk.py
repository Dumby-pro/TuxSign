"""Managing iOS SDKs and the prebuilt HTML shell."""

from __future__ import annotations

import plistlib
import shutil
from pathlib import Path

from tuxsign.util import DATA_DIR, TuxError, ok

SDK_DIR = DATA_DIR / "sdks"
SHELL_DIR = DATA_DIR / "shell"
SHELL_URL = "https://github.com/Dumby-pro/TuxSign/releases/latest/download/TuxShell.app.zip"


def sdk_version(sdk: Path) -> str:
    settings = sdk / "SDKSettings.plist"
    if settings.is_file():
        return str(plistlib.loads(settings.read_bytes()).get("Version", "?"))
    return "?"


def add_sdk(src: Path) -> Path:
    """Register an iPhoneOS.sdk directory (copied out of Xcode on any Mac, or a CI artifact)."""
    src = src.resolve()
    if src.is_dir() and (src / "Platforms").is_dir():  # handed Xcode.app/Contents/Developer
        src = src / "Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk"
    if not (src / "usr" / "include").is_dir():
        raise TuxError(f"{src} is not an iPhoneOS SDK (no usr/include)")
    version = sdk_version(src)
    dest = SDK_DIR / f"iPhoneOS{version}.sdk"
    if dest.exists():
        shutil.rmtree(dest)
    SDK_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=True)
    ok(f"added iOS {version} SDK → {dest}")
    return dest


def list_sdks() -> list[tuple[str, Path]]:
    if not SDK_DIR.is_dir():
        return []
    sdks = [(sdk_version(p), p) for p in SDK_DIR.glob("iPhoneOS*.sdk")]
    return sorted(sdks, key=lambda t: [int(x) if x.isdigit() else 0 for x in t[0].split(".")], reverse=True)


def pick_sdk(min_ios: str) -> Path:
    sdks = list_sdks()
    if not sdks:
        raise TuxError("no iOS SDK installed - run `tuxsign sdk add <iPhoneOS.sdk>` "
                       "or build in the cloud with the generated GitHub Actions workflow")
    return sdks[0][1]


def shell_app() -> Path:
    """Path to the prebuilt HTML shell (.app), fetching it if needed."""
    app = SHELL_DIR / "TuxShell.app"
    if app.is_dir():
        return app
    import io
    import urllib.request
    import zipfile
    try:
        with urllib.request.urlopen(SHELL_URL, timeout=60) as resp:
            data = resp.read()
    except OSError as exc:
        raise TuxError(f"could not download the HTML shell ({exc}); "
                       "use `tuxsign shell add <TuxShell.app or .zip>`") from exc
    return add_shell_zip(io.BytesIO(data))


def add_shell(src: Path) -> Path:
    if src.suffix == ".zip":
        with open(src, "rb") as fh:
            return add_shell_zip(fh)
    if not (src / "Info.plist").is_file():
        raise TuxError(f"{src} is not an .app bundle")
    dest = SHELL_DIR / "TuxShell.app"
    if dest.exists():
        shutil.rmtree(dest)
    SHELL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=True)
    ok(f"installed HTML shell → {dest}")
    return dest


def add_shell_zip(fh) -> Path:
    import tempfile
    import zipfile
    from tuxsign.ipa import unpack
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = tmp / "shell.zip"
        zpath.write_bytes(fh.read())
        names = zipfile.ZipFile(zpath).namelist()
        if any(n.startswith("Payload/") for n in names):
            app = unpack(zpath, tmp / "x")
        else:
            (tmp / "x" / "Payload").mkdir(parents=True)
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(tmp / "x" / "Payload")
            for zi in zipfile.ZipFile(zpath).infolist():
                if (zi.external_attr >> 16) & 0o111:
                    (tmp / "x" / "Payload" / zi.filename).chmod(0o755)
            apps = list((tmp / "x" / "Payload").glob("*.app"))
            if not apps:
                raise TuxError("zip does not contain an .app")
            app = apps[0]
        return add_shell(app)
