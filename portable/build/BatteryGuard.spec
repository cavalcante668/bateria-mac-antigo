# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import ast
import importlib.util

ROOT = Path.home() / "Projects" / "macbook-battery-guard"
APP_SRC = ROOT / "portable" / "app"
LAUNCHER = ROOT / "portable" / "launcher" / "launcher.py"

# ------------------------------------------------------------
# Descobre automaticamente os imports dos scripts executados
# dinamicamente pelo launcher via runpy.
# ------------------------------------------------------------

hidden = set()

for script in APP_SRC.glob("*.py"):
    source = script.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script))

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                hidden.add(alias.name)

        elif isinstance(node, ast.ImportFrom) and node.module:
            hidden.add(node.module)

            # Se o elemento importado também for um módulo real,
            # adiciona o submódulo.
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"

                try:
                    if importlib.util.find_spec(candidate) is not None:
                        hidden.add(candidate)
                except (
                    ImportError,
                    ModuleNotFoundError,
                    AttributeError,
                    ValueError
                ):
                    pass

hiddenimports = sorted(hidden)

print()
print("=== HIDDEN IMPORTS ===")
for item in hiddenimports:
    print(item)
print("======================")
print()

a = Analysis(
    [str(LAUNCHER)],
    pathex=[
        str(ROOT),
        str(APP_SRC),
    ],
    binaries=[],
    datas=[
        (str(APP_SRC), "app"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
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
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Battery Guard",
)

app = BUNDLE(
    coll,
    name="Battery Guard.app",
    icon=None,
    bundle_identifier="com.cavalcante.batteryguard",
)
