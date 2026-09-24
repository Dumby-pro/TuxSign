import datetime as dt
import os
import plistlib
import stat
import zipfile
from pathlib import Path

import pytest

from tuxsign import build, bundle, config, ipa, provision, scaffold, sdk, sign
from tuxsign.util import TuxError


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "SHELL_DIR", tmp_path / "home" / "shell")
    monkeypatch.setattr(sdk, "SDK_DIR", tmp_path / "home" / "sdks")


def make_app(root: Path, name="Shell", exe="Shell", bundle_id="com.example.shell") -> Path:
    app = root / f"{name}.app"
    app.mkdir(parents=True)
    (app / exe).write_bytes(b"\xcf\xfa\xed\xfe fake mach-o")
    (app / exe).chmod(0o755)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": exe, "CFBundleIdentifier": bundle_id}))
    return app


def test_scaffold_and_config(tmp_path):
    for kind in ("swiftui", "html"):
        proj = scaffold.create(tmp_path / kind, "My Cool App", kind)
        p = config.load(proj)
        assert p.kind == kind
        assert p.executable == "MyCoolApp"
        assert p.bundle_id == "com.tuxsign.mycoolapp"
        assert (proj / ".github/workflows/tuxsign-build.yml").is_file()
        assert "{{" not in "".join(f.read_text() for f in proj.rglob("*") if f.is_file())
    assert "MyCoolAppApp" in (tmp_path / "swiftui/Sources/App.swift").read_text()


def test_scaffold_refuses_nonempty(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f").write_text("")
    with pytest.raises(TuxError):
        scaffold.create(tmp_path / "x", "X", "html")


def test_config_validation(tmp_path):
    (tmp_path / "tuxsign.toml").write_text('[app]\nname="A"\nbundle_id="bad id!"\nkind="html"\n')
    with pytest.raises(TuxError, match="bundle_id"):
        config.load(tmp_path)


def test_info_plist_has_sensor_keys(tmp_path):
    proj = scaffold.create(tmp_path / "a", "A", "swiftui")
    plist = bundle.info_plist(config.load(proj))
    for key in config.DEFAULT_USAGE:
        assert key in plist
    assert plist["MinimumOSVersion"] == "26.0"
    assert "UIInterfaceOrientationLandscapeRight" in plist["UISupportedInterfaceOrientations"]


def test_ipa_roundtrip_keeps_exec_and_symlinks(tmp_path):
    app = make_app(tmp_path / "src")
    fw = app / "Frameworks" / "X.framework"
    fw.mkdir(parents=True)
    (fw / "X").write_text("bin")
    (app / "link").symlink_to("Frameworks/X.framework/X")
    out = ipa.pack(app, tmp_path / "out.ipa")
    names = zipfile.ZipFile(out).namelist()
    assert "Payload/Shell.app/Info.plist" in names
    back = ipa.unpack(out, tmp_path / "unz")
    assert os.stat(back / "Shell").st_mode & stat.S_IXUSR
    assert (back / "link").is_symlink()
    assert ipa.inspect(out)["bundle_id"] == "com.example.shell"


def test_html_build_with_prebuilt_shell(tmp_path):
    shell_src = make_app(tmp_path / "shellsrc", "TuxShell", "TuxShell")
    sdk.add_shell(shell_src)
    proj = scaffold.create(tmp_path / "web", "Web Demo", "html")
    out = build.build(config.load(proj), prebuilt_shell=True)
    app = ipa.unpack(out, tmp_path / "unz")
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "WebDemo"
    assert info["CFBundleIdentifier"] == "com.tuxsign.webdemo"
    assert os.stat(app / "WebDemo").st_mode & stat.S_IXUSR
    assert (app / "www" / "index.html").is_file()
    assert not (app / "TuxShell").exists()


def test_swift_build_without_toolchain_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(build.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build, "which", lambda *_: None)
    proj = scaffold.create(tmp_path / "s", "S", "swiftui")
    with pytest.raises(TuxError, match="swiftc"):
        build.build(config.load(proj))


# ---- signing -------------------------------------------------------------

def make_identity(tmp_path, password=b"pw"):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Apple Development: Test (ABCDE12345)")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + dt.timedelta(days=365))
            .sign(key, hashes.SHA256()))
    p12 = tmp_path / "cert.p12"
    p12.write_bytes(pkcs12.serialize_key_and_certificates(
        b"t", key, cert, None, serialization.BestAvailableEncryption(password)))
    return p12, cert.public_bytes(serialization.Encoding.DER)


def make_profile(tmp_path, cert_der, app_id="TEAM123456.com.example.*", days=7):
    data = {
        "Name": "Test Profile", "UUID": "1234", "TeamIdentifier": ["TEAM123456"],
        "ExpirationDate": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(days=days),
        "DeveloperCertificates": [cert_der],
        "ProvisionedDevices": ["00008030-000000000000002E"],
        "Entitlements": {"application-identifier": app_id, "get-task-allow": True,
                         "com.apple.developer.team-identifier": "TEAM123456",
                         "keychain-access-groups": ["TEAM123456.*"]},
    }
    path = tmp_path / "test.mobileprovision"
    path.write_bytes(b"0\x80\x06\x09fake-cms-header" + plistlib.dumps(data) + b"\x00\x00trailer")
    return path


def test_profile_parsing(tmp_path):
    _, der = make_identity(tmp_path)
    prof = provision.load_profile(make_profile(tmp_path, der))
    assert prof.team_id == "TEAM123456"
    assert prof.matches("com.example.app") and not prof.matches("org.other.app")
    ents = prof.entitlements_for("com.example.app")
    assert ents["application-identifier"] == "TEAM123456.com.example.app"
    assert ents["keychain-access-groups"] == ["TEAM123456.com.example.app"]
    assert not prof.expired


def test_sign_pipeline_with_fake_signer(tmp_path, monkeypatch):
    p12, der = make_identity(tmp_path)
    profile = make_profile(tmp_path, der)
    src = ipa.pack(make_app(tmp_path / "src"), tmp_path / "in.ipa")

    calls = []

    def fake_run(cmd, **kw):
        calls.append([str(c) for c in cmd])
        app = Path(cmd[-1])
        (app / "_CodeSignature").mkdir()
        (app / "_CodeSignature" / "CodeResources").write_text("signed")

    monkeypatch.setattr(sign, "find_signer", lambda prefer=None: ("rcodesign", "/usr/bin/rcodesign"))
    monkeypatch.setattr(sign, "run", fake_run)
    out = sign.sign_ipa(src, tmp_path / "out.ipa", p12=p12, password="pw", profile_path=profile,
                        display_name="Renamed")
    report = ipa.inspect(out)
    assert report["signed"] and report["embedded_profile"]
    assert report["name"] == "Renamed"
    assert "--p12-password" in calls[0]


def test_sign_rejects_wrong_cert_and_bundle(tmp_path, monkeypatch):
    p12, _ = make_identity(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _, other_der = make_identity(other)
    src = ipa.pack(make_app(tmp_path / "src"), tmp_path / "in.ipa")
    monkeypatch.setattr(sign, "find_signer", lambda prefer=None: ("rcodesign", "x"))
    with pytest.raises(TuxError, match="not included"):
        sign.sign_ipa(src, tmp_path / "o.ipa", p12=p12, password="pw", profile_path=make_profile(tmp_path, other_der))
    _, der = make_identity(tmp_path)
    p12b = tmp_path / "cert.p12"
    with pytest.raises(TuxError, match="does not cover"):
        sign.sign_ipa(src, tmp_path / "o.ipa", p12=p12b, password="pw", bundle_id="org.nope.app",
                      profile_path=make_profile(tmp_path, der))


def test_bad_p12_password(tmp_path):
    p12, _ = make_identity(tmp_path)
    with pytest.raises(TuxError, match="password"):
        provision.load_p12(p12, "wrong")
