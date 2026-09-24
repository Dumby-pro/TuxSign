"""Building projects into .app bundles and .ipa files.

SwiftUI apps are compiled with swiftc against an iPhoneOS SDK:
  * on Linux: the swift.org toolchain + a registered SDK, linked with ld64.lld
  * on macOS (incl. the GitHub Actions workflow): Xcode's toolchain via xcrun
HTML apps reuse the native TuxShell (compiled from tuxsign/shell or prebuilt),
so they can be built on Linux with no SDK at all.
"""

from __future__ import annotations

import json
import plistlib
import platform
import shutil
import time
from pathlib import Path

from tuxsign import bundle, ipa, sdk
from tuxsign.config import Project
from tuxsign.util import TuxError, info, ok, run, which

SHELL_SOURCES = Path(__file__).parent / "shell" / "Sources"


def _swift_cmd(p: Project, sources: list[Path], out: Path, release: bool) -> list[str]:
    target = f"arm64-apple-ios{p.min_ios}"
    if platform.system() == "Darwin":
        sdk_path = run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], capture=True).stdout.strip()
        cmd = ["xcrun", "--sdk", "iphoneos", "swiftc"]
    else:
        swiftc = which("swiftc")
        if not swiftc:
            raise TuxError("swiftc not found - install the Swift toolchain from swift.org "
                           "(or push the project to GitHub and use the cloud build workflow)")
        sdk_path = str(sdk.pick_sdk(p.min_ios))
        if not which("ld64.lld"):
            raise TuxError("ld64.lld not found - install lld (e.g. `apt install lld`)")
        cmd = [swiftc, "-use-ld=lld", "-Xlinker", "-platform_version", "-Xlinker", "ios",
               "-Xlinker", p.min_ios, "-Xlinker", p.min_ios]
    cmd += [
        "-target", target, "-sdk", sdk_path,
        "-module-name", p.executable, "-parse-as-library", "-emit-executable",
        "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks",
        "-o", str(out),
    ]
    for fw in p.frameworks:
        cmd += ["-framework", fw]
    cmd += ["-O", "-wmo"] if release else ["-Onone", "-g"]
    return cmd + [str(s) for s in sources]


def _compile(p: Project, sources: list[Path], app_dir: Path, release: bool) -> None:
    if not sources:
        raise TuxError(f"no .swift files found in {p.root / p.sources}")
    info(f"compiling {len(sources)} Swift file(s) for iOS {p.min_ios}+")
    run(_swift_cmd(p, sources, app_dir / p.executable, release))


def _can_compile() -> bool:
    return platform.system() == "Darwin" or bool(which("swiftc") and sdk.list_sdks())


def build(p: Project, *, release: bool = True, out: Path | None = None, prebuilt_shell: bool | None = None) -> Path:
    start = time.monotonic()
    products = p.build_dir
    app_dir = products / "Payload" / f"{p.executable}.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.parent.mkdir(parents=True, exist_ok=True)

    if p.kind == "swiftui":
        app_dir.mkdir()
        _compile(p, sorted((p.root / p.sources).rglob("*.swift")), app_dir, release)
    else:
        web = p.root / p.web_root
        if not (web / "index.html").is_file():
            raise TuxError(f"{web}/index.html not found")
        use_prebuilt = (not _can_compile()) if prebuilt_shell is None else prebuilt_shell
        if use_prebuilt:
            info("using prebuilt TuxShell (no SDK needed)")
            shell = sdk.shell_app()
            shutil.copytree(shell, app_dir, symlinks=True)
            shell_exe = plistlib.loads((shell / "Info.plist").read_bytes())["CFBundleExecutable"]
            (app_dir / shell_exe).rename(app_dir / p.executable)
            for junk in ("_CodeSignature", "embedded.mobileprovision", "www"):
                target = app_dir / junk
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
        else:
            app_dir.mkdir()
            extra = sorted((p.root / p.sources).rglob("*.swift")) if (p.root / p.sources).is_dir() else []
            _compile(p, sorted(SHELL_SOURCES.glob("*.swift")) + extra, app_dir, release)
        shutil.copytree(web, app_dir / "www")
        (app_dir / "www" / "tuxsign.json").write_text(json.dumps({"name": p.name, "bundle_id": p.bundle_id}))

    bundle.write_plist(app_dir / "Info.plist", bundle.info_plist(p))
    (app_dir / "PkgInfo").write_text("APPL????")
    bundle.copy_icon(p, app_dir)
    bundle.copy_resources(p, app_dir)
    if p.entitlements:
        bundle.write_plist(products / "entitlements.plist", p.entitlements, binary=False)

    out = out or products / f"{p.executable}.ipa"
    ipa.pack(app_dir, out)
    ok(f"built {out} ({out.stat().st_size / 1e6:.2f} MB, unsigned) in {time.monotonic() - start:.1f}s")
    return out
