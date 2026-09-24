"""Command-line interface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import sys
from pathlib import Path

from tuxsign import __version__
from tuxsign.util import TuxError, info, ok, warn, which


def _password(args) -> str | None:
    if args.password is not None:
        return args.password
    env = os.environ.get("TUXSIGN_P12_PASSWORD")
    if env is not None:
        return env
    return getpass.getpass(".p12 password (empty for none): ") if sys.stdin.isatty() else None


def cmd_new(args):
    from tuxsign import scaffold
    scaffold.create(Path(args.path or args.name), args.name, args.template, args.bundle_id)
    print(f"\nnext:\n  cd {args.path or args.name}\n  tuxsign build")


def cmd_build(args):
    from tuxsign import build, config
    p = config.load(args.project)
    prebuilt = True if args.prebuilt_shell else None
    out = build.build(p, release=not args.debug, out=Path(args.output) if args.output else None,
                      prebuilt_shell=prebuilt)
    if args.p12:
        from tuxsign import sign
        sign.sign_ipa(out, out, p12=Path(args.p12), password=_password(args), profile_path=Path(args.profile),
                      extra_entitlements=p.entitlements)
    print(out)


def cmd_sign(args):
    from tuxsign import sign
    src = Path(args.input)
    out = Path(args.output) if args.output else src.with_name(src.stem.removesuffix("-unsigned") + "-signed.ipa")
    sign.sign_ipa(src, out, p12=Path(args.p12), password=_password(args), profile_path=Path(args.profile),
                  bundle_id=args.bundle_id, display_name=args.name, signer=args.signer)
    print(out)


def cmd_install(args):
    from tuxsign import device
    device.install(Path(args.ipa), args.udid)


def cmd_run(args):
    from tuxsign import build, config, device, sign
    p = config.load(args.project)
    out = build.build(p)
    sign.sign_ipa(out, out, p12=Path(args.p12), password=_password(args), profile_path=Path(args.profile),
                  extra_entitlements=p.entitlements)
    device.install(out, args.udid)
    if args.log:
        device.syslog(args.udid, p.executable)


def cmd_inspect(args):
    from tuxsign import ipa, provision
    path = Path(args.file)
    if path.suffix == ".mobileprovision":
        prof = provision.load_profile(path)
        data = {"name": prof.name, "uuid": prof.uuid, "team": prof.team_id, "app_id": prof.app_id,
                "expires": prof.expires.isoformat(), "expired": prof.expired,
                "devices": len(prof.devices) if not prof.all_devices else "all",
                "entitlements": prof.entitlements, "certificates": prof.cert_fingerprints}
    elif path.suffix == ".p12":
        ident = provision.load_p12(path, _password(args))
        data = {"common_name": ident.common_name, "sha1": ident.fingerprint, "expires": ident.not_after.isoformat()}
    else:
        data = ipa.inspect(path)
    print(json.dumps(data, indent=2, default=str))


def cmd_devices(args):
    from tuxsign import device
    devs = device.list_devices()
    if not devs:
        warn("no devices found (plug in via USB, unlock, and tap Trust)")
    for d in devs:
        print(f"{d['udid']}  {d['name']}  iOS {d['ios']}  ({d['connection']})")


def cmd_sdk(args):
    from tuxsign import sdk
    if args.action == "add":
        sdk.add_sdk(Path(args.path))
    else:
        for version, path in sdk.list_sdks():
            print(f"iOS {version}\t{path}")


def cmd_shell(args):
    from tuxsign import sdk
    if args.action == "add":
        sdk.add_shell(Path(args.path))
    else:
        print(sdk.shell_app())


def cmd_serve(args):
    import functools
    import http.server
    from tuxsign import config
    p = config.load(args.project)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(p.root / p.web_root))
    with http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler) as srv:
        ok(f"serving {p.web_root}/ on http://localhost:{args.port} (Ctrl+C to stop)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


def cmd_doctor(args):
    from tuxsign import sdk
    print(f"TuxSign {__version__} · Python {platform.python_version()} · {platform.system()} {platform.machine()}\n")
    checks = [
        ("swiftc", "compile SwiftUI apps locally", "https://swift.org/install"),
        ("ld64.lld", "link iOS binaries", "apt install lld"),
        ("zsign", "sign apps (fast)", "https://github.com/zhlynn/zsign"),
        ("rcodesign", "sign apps (alternative)", "cargo install apple-codesign"),
        ("ideviceinstaller", "install on device", "apt install ideviceinstaller"),
        ("idevice_id", "list devices", "apt install libimobiledevice-utils"),
    ]
    for tool, why, how in checks:
        path = which(tool)
        print(f"  {'✓' if path else '✗'} {tool:<17} {why:<30} {path or 'install: ' + how}")
    try:
        import cryptography  # noqa: F401
        print(f"  ✓ {'cryptography':<17} {'read .p12 certificates':<30}")
    except ImportError:
        print(f"  ✗ {'cryptography':<17} {'read .p12 certificates':<30} install: pip install cryptography")
    sdks = sdk.list_sdks()
    print(f"\n  iOS SDKs: {', '.join(v for v, _ in sdks) or 'none (tuxsign sdk add <iPhoneOS.sdk>)'}")
    shell = sdk.SHELL_DIR / "TuxShell.app"
    print(f"  HTML shell: {'installed' if shell.is_dir() else 'downloaded on first HTML build'}")
    print("\n  No local SDK? Every project includes .github/workflows/tuxsign-build.yml:\n"
          "  push to GitHub → download the unsigned IPA → `tuxsign sign` here.")


def _add_sign_opts(p, required: bool):
    p.add_argument("-c", "--p12", required=required, help="signing certificate + key (.p12)")
    p.add_argument("-m", "--profile", required=required, help="provisioning profile (.mobileprovision)")
    p.add_argument("-p", "--password", help=".p12 password (or $TUXSIGN_P12_PASSWORD)")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tuxsign", description="Build, sign and install iOS apps from Linux.")
    ap.add_argument("--version", action="version", version=f"tuxsign {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a SwiftUI or HTML app")
    p.add_argument("name")
    p.add_argument("-t", "--template", choices=["swiftui", "html"], default="swiftui")
    p.add_argument("-b", "--bundle-id")
    p.add_argument("--path", help="directory (default: ./NAME)")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("build", help="build the project in the current directory into an .ipa")
    p.add_argument("-C", "--project", default=".")
    p.add_argument("-o", "--output")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--release", action="store_true", help="(default)")
    p.add_argument("--prebuilt-shell", action="store_true", help="HTML apps: skip compiling, use prebuilt shell")
    _add_sign_opts(p, required=False)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("sign", help="sign an .ipa or .app")
    p.add_argument("input")
    p.add_argument("-o", "--output")
    p.add_argument("-b", "--bundle-id", help="change the bundle id")
    p.add_argument("-n", "--name", help="change the display name")
    p.add_argument("--signer", choices=["zsign", "rcodesign"])
    _add_sign_opts(p, required=True)
    p.set_defaults(fn=cmd_sign)

    p = sub.add_parser("install", help="install an .ipa on a connected device")
    p.add_argument("ipa")
    p.add_argument("-u", "--udid")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("run", help="build + sign + install")
    p.add_argument("-C", "--project", default=".")
    p.add_argument("-u", "--udid")
    p.add_argument("--log", action="store_true", help="stream the device log afterwards")
    _add_sign_opts(p, required=True)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("inspect", help="show details of an .ipa, .mobileprovision or .p12")
    p.add_argument("file")
    p.add_argument("-p", "--password")
    p.set_defaults(fn=cmd_inspect)

    sub.add_parser("devices", help="list connected devices").set_defaults(fn=cmd_devices)

    p = sub.add_parser("sdk", help="manage iOS SDKs")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_sdk)

    p = sub.add_parser("shell", help="manage the prebuilt HTML shell")
    p.add_argument("action", choices=["add", "path"])
    p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_shell)

    p = sub.add_parser("serve", help="preview an HTML app in the browser")
    p.add_argument("-C", "--project", default=".")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)

    sub.add_parser("doctor", help="check installed tools").set_defaults(fn=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.cmd in ("sdk", "shell") and args.action == "add" and not args.path:
        parser().error(f"{args.cmd} add needs a path")
    if args.cmd == "build" and bool(args.p12) != bool(args.profile):
        parser().error("--p12 and --profile go together")
    try:
        args.fn(args)
    except TuxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
