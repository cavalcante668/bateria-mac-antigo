# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).parent.parent
APP = ROOT / "portable" / "app"
LAUNCHER = ROOT / "portable" / "launcher" / "launcher.py"
ICON = ROOT / "portable" / "assets" / "BatteryGuard.icns"

hiddenimports = []

for package in [
    "webview",
    "objc",
    "AppKit",
    "Foundation",
    "WebKit",
    "PyObjCTools",
]:
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

datas = [
    (str(APP), "app"),
]

try:
    datas += collect_data_files("webview")
except Exception:
    pass


a = Analysis(
    [str(LAUNCHER)],
    pathex=[
        str(ROOT),
        str(APP),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Battery Guard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Battery Guard",
)

app = BUNDLE(
    coll,
    name="Battery Guard.app",
    icon=str(ICON),
    bundle_identifier="com.batteryguard.app",
    info_plist={
        "CFBundleName": "Battery Guard",
        "CFBundleDisplayName": "Battery Guard",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "NSHighResolutionCapable": True,
    },
)
