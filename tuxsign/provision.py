"""Reading .mobileprovision files and .p12 certificates."""

from __future__ import annotations

import datetime as dt
import fnmatch
import plistlib
from dataclasses import dataclass
from pathlib import Path

from tuxsign.util import TuxError


@dataclass
class Profile:
    path: Path
    name: str
    uuid: str
    team_id: str
    app_id: str          # e.g. "ABCDE12345.com.example.*"
    expires: dt.datetime
    devices: list[str]
    entitlements: dict
    cert_fingerprints: list[str]  # SHA-1 hex of each allowed signing certificate
    all_devices: bool

    @property
    def bundle_pattern(self) -> str:
        return self.app_id.split(".", 1)[1] if "." in self.app_id else self.app_id

    @property
    def expired(self) -> bool:
        return self.expires < dt.datetime.now(dt.timezone.utc)

    def matches(self, bundle_id: str) -> bool:
        return fnmatch.fnmatchcase(bundle_id, self.bundle_pattern)

    def entitlements_for(self, bundle_id: str) -> dict:
        """Profile entitlements with the wildcard application-identifier made concrete."""
        ents = dict(self.entitlements)
        ents["application-identifier"] = f"{self.team_id}.{bundle_id}"
        if "keychain-access-groups" in ents:
            ents["keychain-access-groups"] = [
                g.replace("*", bundle_id) if g.endswith("*") else g for g in ents["keychain-access-groups"]
            ]
        return ents


def _sha1(der: bytes) -> str:
    import hashlib
    return hashlib.sha1(der).hexdigest().upper()


def load_profile(path: Path | str) -> Profile:
    path = Path(path)
    raw = path.read_bytes()
    # A profile is a CMS-signed plist; the plist sits in the clear inside it.
    start, end = raw.find(b"<?xml"), raw.find(b"</plist>")
    if start < 0 or end < 0:
        raise TuxError(f"{path} does not look like a .mobileprovision")
    data = plistlib.loads(raw[start:end + len(b"</plist>")])
    expires = data["ExpirationDate"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    ents = data.get("Entitlements", {})
    return Profile(
        path=path,
        name=data.get("Name", ""),
        uuid=data.get("UUID", ""),
        team_id=(data.get("TeamIdentifier") or [""])[0],
        app_id=ents.get("application-identifier", ""),
        expires=expires,
        devices=data.get("ProvisionedDevices", []),
        entitlements=ents,
        cert_fingerprints=[_sha1(c) for c in data.get("DeveloperCertificates", [])],
        all_devices=bool(data.get("ProvisionsAllDevices")),
    )


@dataclass
class Identity:
    common_name: str
    fingerprint: str
    not_after: dt.datetime


def load_p12(path: Path | str, password: str | None) -> Identity:
    try:
        from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
    except ImportError as exc:  # pragma: no cover
        raise TuxError("reading .p12 files needs the `cryptography` package (pip install cryptography)") from exc
    try:
        key, cert, _ = pkcs12.load_key_and_certificates(
            Path(path).read_bytes(), password.encode() if password else None)
    except ValueError as exc:
        raise TuxError(f"{path}: could not open .p12 (wrong password?)") from exc
    if cert is None or key is None:
        raise TuxError(f"{path}: .p12 must contain a certificate and its private key")
    from cryptography.x509.oid import NameOID
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return Identity(
        common_name=cn[0].value if cn else "?",
        fingerprint=_sha1(cert.public_bytes(Encoding.DER)),
        not_after=cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc")
        else cert.not_valid_after.replace(tzinfo=dt.timezone.utc),
    )
