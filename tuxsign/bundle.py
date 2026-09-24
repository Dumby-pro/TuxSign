"""Assembling .app bundles: Info.plist generation, resources, icons."""

from __future__ import annotations

import plistlib
import shutil
from pathlib import Path

from tuxsign.config import Project

_ORIENT = {
    "portrait": "UIInterfaceOrientationPortrait",
    "upside_down": "UIInterfaceOrientationPortraitUpsideDown",
    "landscape": "UIInterfaceOrientationLandscapeLeft",
    "landscape_right": "UIInterfaceOrientationLandscapeRight",
}


def info_plist(p: Project) -> dict:
    orient = []
    for o in p.orientation:
        orient.append(_ORIENT.get(o, o))
        if o == "landscape":
            orient.append(_ORIENT["landscape_right"])
    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": p.executable,
        "CFBundleIdentifier": p.bundle_id,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": p.name,
        "CFBundleDisplayName": p.display_name or p.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": p.version,
        "CFBundleVersion": p.build,
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "DTPlatformName": "iphoneos",
        "DTSDKName": f"iphoneos{p.min_ios}",
        "DTPlatformVersion": p.min_ios,
        "MinimumOSVersion": p.min_ios,
        "LSRequiresIPhoneOS": True,
        "UIDeviceFamily": [1, 2],
        "UIRequiredDeviceCapabilities": ["arm64"],
        "UILaunchScreen": {},
        "UIApplicationSceneManifest": {"UIApplicationSupportsMultipleScenes": True},
        "UISupportedInterfaceOrientations": orient,
        "UISupportedInterfaceOrientations~ipad": list(_ORIENT.values()),
        "ITSAppUsesNonExemptEncryption": False,
        **p.usage,
    }
    if p.icon:
        # Loose PNG icons work without an asset catalog (actool is macOS-only).
        plist["CFBundleIcons"] = {"CFBundlePrimaryIcon": {"CFBundleIconFiles": ["AppIcon60x60"]}}
        plist["CFBundleIcons~ipad"] = {"CFBundlePrimaryIcon": {"CFBundleIconFiles": ["AppIcon60x60", "AppIcon76x76"]}}
    plist.update(p.info_plist)
    return plist


def write_plist(path: Path, data: dict, binary: bool = True) -> None:
    path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML))


def copy_icon(p: Project, app_dir: Path) -> None:
    if not p.icon:
        return
    src = p.root / p.icon
    # iOS scales down from the largest provided file; ship it under every name it looks for.
    for name in ("AppIcon60x60@2x.png", "AppIcon60x60@3x.png", "AppIcon76x76@2x~ipad.png"):
        shutil.copyfile(src, app_dir / name)


def copy_resources(p: Project, app_dir: Path) -> None:
    res = p.root / "Resources"
    if res.is_dir():
        shutil.copytree(res, app_dir, dirs_exist_ok=True)
