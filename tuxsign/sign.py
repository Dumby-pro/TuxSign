"""Code signing with a certificate (.p12) and provisioning profile.

The Mach-O/CMS work is delegated to a native signer, whichever is installed:
  * zsign     - fast C++ signer   (https://github.com/zhlynn/zsign)
  * rcodesign - Rust apple-codesign (https://github.com/indygreg/apple-platform-rs)
TuxSign does the validation and bundle preparation around it.
"""

from __future__ import annotations

import plistlib
import shutil
import tempfile
from pathlib import Path

from tuxsign import ipa as ipa_mod
from tuxsign.provision import Profile, load_p12, load_profile
from tuxsign.util import TuxError, info, ok, run, warn, which


def find_signer(prefer: str | None = None) -> tuple[str, str]:
    order = [prefer] if prefer else ["zsign", "rcodesign"]
    for name in order:
        path = which(name)
        if path:
            return name, path
    raise TuxError("no signer found: install zsign or rcodesign (see `tuxsign doctor`)")


def _nested_bundles(app: Path) -> list[Path]:
    """Nested code, deepest first (inner code must be signed before outer)."""
    found = [p for p in app.rglob("*") if p.suffix in (".appex", ".framework", ".dylib", ".app") and p != app]
    return sorted(found, key=lambda p: len(p.parts), reverse=True)


def prepare(app: Path, profile: Profile, bundle_id: str | None, display_name: str | None) -> tuple[str, dict]:
    """Rewrite identifiers, embed the profile and return (bundle id, entitlements)."""
    info_path = app / "Info.plist"
    plist = plistlib.loads(info_path.read_bytes())
    old_id = plist["CFBundleIdentifier"]
    new_id = bundle_id or old_id
    if not profile.matches(new_id):
        if bundle_id is None and "*" not in profile.bundle_pattern:
            new_id = profile.bundle_pattern
            warn(f"profile is for {new_id}; changing bundle id from {old_id}")
        else:
            raise TuxError(f"profile '{profile.name}' ({profile.app_id}) does not cover bundle id {new_id}")
    plist["CFBundleIdentifier"] = new_id
    if display_name:
        plist["CFBundleDisplayName"] = display_name
    info_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_BINARY))

    # Extensions keep their suffix under the new parent id.
    for ext in app.rglob("*.appex"):
        ep = ext / "Info.plist"
        eplist = plistlib.loads(ep.read_bytes())
        eid = eplist.get("CFBundleIdentifier", "")
        if eid.startswith(old_id):
            eplist["CFBundleIdentifier"] = new_id + eid[len(old_id):]
            ep.write_bytes(plistlib.dumps(eplist, fmt=plistlib.FMT_BINARY))

    shutil.copyfile(profile.path, app / "embedded.mobileprovision")
    for stale in app.rglob("_CodeSignature"):
        shutil.rmtree(stale)
    return new_id, profile.entitlements_for(new_id)


def sign_ipa(src: Path, out: Path, *, p12: Path, password: str | None, profile_path: Path,
             bundle_id: str | None = None, display_name: str | None = None,
             signer: str | None = None, extra_entitlements: dict | None = None) -> Path:
    profile = load_profile(profile_path)
    ident = load_p12(p12, password)
    info(f"certificate: {ident.common_name}")
    info(f"profile:     {profile.name} (team {profile.team_id}, expires {profile.expires:%Y-%m-%d})")
    if profile.expired:
        raise TuxError(f"provisioning profile expired on {profile.expires:%Y-%m-%d}")
    if profile.cert_fingerprints and ident.fingerprint not in profile.cert_fingerprints:
        raise TuxError("the .p12 certificate is not included in this provisioning profile")

    name, exe = find_signer(signer)
    with tempfile.TemporaryDirectory(prefix="tuxsign-") as tmp:
        tmp = Path(tmp)
        app = ipa_mod.unpack(src, tmp) if src.suffix == ".ipa" else ipa_mod.copy_app(src, tmp / "Payload")
        new_id, ents = prepare(app, profile, bundle_id, display_name)
        ents.update(extra_entitlements or {})
        ent_file = tmp / "entitlements.plist"
        ent_file.write_bytes(plistlib.dumps(ents))
        info(f"signing {new_id} with {name}")

        if name == "zsign":
            cmd = [exe, "-k", p12, "-m", profile_path, "-e", ent_file, "-o", out]
            if password:
                cmd += ["-p", password]
            run(cmd + [app])
        else:
            cmd = [exe, "sign", "--p12-file", p12, "--entitlements-xml-path", ent_file]
            if password:
                cmd += ["--p12-password", password]
            run(cmd + [app])
            ipa_mod.pack(app, out)
    ok(f"signed → {out}")
    return out
