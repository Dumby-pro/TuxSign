"""IPA packaging and inspection."""

from __future__ import annotations

import plistlib
import shutil
import tempfile
import zipfile
from pathlib import Path

from tuxsign.util import TuxError

# Already-compressed files gain nothing from deflate; storing them is faster.
_STORED = {".png", ".jpg", ".jpeg", ".car", ".mp3", ".mp4", ".m4a", ".mov", ".zip", ".gz", ".webp", ".heic"}


def pack(app_dir: Path, out: Path, level: int = 6) -> Path:
    """Zip an .app into Payload/<Name>.app inside an .ipa."""
    app_dir = Path(app_dir)
    if app_dir.suffix != ".app" or not app_dir.is_dir():
        raise TuxError(f"{app_dir} is not an .app bundle")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".ipa.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for path in sorted(app_dir.rglob("*")):
            arc = f"Payload/{app_dir.name}/{path.relative_to(app_dir).as_posix()}"
            if path.is_symlink():
                # Keep symlinks as symlinks (frameworks rely on them).
                zi = zipfile.ZipInfo(arc)
                zi.create_system = 3
                zi.external_attr = (0o120777 << 16)
                zf.writestr(zi, str(path.readlink()))
            elif path.is_dir():
                continue
            else:
                ctype = zipfile.ZIP_STORED if path.suffix.lower() in _STORED else zipfile.ZIP_DEFLATED
                zf.write(path, arc, compress_type=ctype)
    tmp.replace(out)
    return out


def unpack(ipa: Path, dest: Path) -> Path:
    """Extract an .ipa and return the path of its .app bundle (keeps exec bits)."""
    with zipfile.ZipFile(ipa) as zf:
        for zi in zf.infolist():
            target = dest / zi.filename
            if not target.resolve().is_relative_to(dest.resolve()):
                raise TuxError(f"unsafe path in ipa: {zi.filename}")
            mode = zi.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(zf.read(zi).decode())
                continue
            zf.extract(zi, dest)
            if mode & 0o111:
                target.chmod(mode & 0o777)
    apps = list((dest / "Payload").glob("*.app"))
    if len(apps) != 1:
        raise TuxError(f"{ipa}: expected exactly one Payload/*.app, found {len(apps)}")
    return apps[0]


def read_info(app_dir: Path) -> dict:
    path = app_dir / "Info.plist"
    if not path.is_file():
        raise TuxError(f"{app_dir} has no Info.plist")
    return plistlib.loads(path.read_bytes())


def inspect(ipa: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        app = unpack(ipa, Path(tmp))
        info = read_info(app)
        nested = [str(p.relative_to(app)) for p in app.rglob("*")
                  if p.suffix in (".appex", ".framework", ".dylib")]
        signed = (app / "_CodeSignature" / "CodeResources").is_file()
        return {
            "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
            "bundle_id": info.get("CFBundleIdentifier"),
            "version": f"{info.get('CFBundleShortVersionString')} ({info.get('CFBundleVersion')})",
            "min_ios": info.get("MinimumOSVersion"),
            "executable": info.get("CFBundleExecutable"),
            "signed": signed,
            "embedded_profile": (app / "embedded.mobileprovision").is_file(),
            "nested": nested,
            "size_mb": round(ipa.stat().st_size / 1e6, 2),
        }


def copy_app(src: Path, dest_dir: Path) -> Path:
    dest = dest_dir / src.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)
    return dest
