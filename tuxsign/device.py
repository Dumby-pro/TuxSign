"""Talking to iPhones/iPads over USB or Wi-Fi via libimobiledevice."""

from __future__ import annotations

from pathlib import Path

from tuxsign.util import TuxError, info, ok, run, which


def _need(tool: str) -> str:
    path = which(tool)
    if not path:
        raise TuxError(f"{tool} not found - install libimobiledevice "
                       "(e.g. `apt install libimobiledevice-utils ideviceinstaller usbmuxd`)")
    return path


def list_devices() -> list[dict]:
    exe = _need("idevice_id")
    devices = []
    for flag, conn in (("-l", "usb"), ("-n", "network")):
        out = run([exe, flag], capture=True).stdout
        for udid in filter(None, (l.strip() for l in out.splitlines())):
            if any(d["udid"] == udid for d in devices):
                continue
            name = run([_need("ideviceinfo"), "-u", udid, "-k", "DeviceName"], capture=True).stdout.strip()
            ver = run([_need("ideviceinfo"), "-u", udid, "-k", "ProductVersion"], capture=True).stdout.strip()
            devices.append({"udid": udid, "name": name, "ios": ver, "connection": conn})
    return devices


def install(ipa: Path, udid: str | None = None) -> None:
    exe = _need("ideviceinstaller")
    cmd = [exe]
    if udid:
        cmd += ["-u", udid]
    info(f"installing {ipa.name} on {udid or 'the connected device'}")
    # Newer ideviceinstaller dropped -i in favour of the `install` subcommand.
    help_text = run([exe, "--help"], capture=True).stdout
    run(cmd + (["install", str(ipa)] if "install PATH" in help_text or "\n  install" in help_text else ["-i", str(ipa)]))
    ok("installed")


def syslog(udid: str | None, match: str | None) -> None:
    import subprocess
    cmd = [_need("idevicesyslog")]
    if udid:
        cmd += ["-u", udid]
    if match:
        cmd += ["-m", match]
    subprocess.run(cmd)
