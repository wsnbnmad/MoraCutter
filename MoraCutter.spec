# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPEC).resolve().parent
tkdnd_datas, tkdnd_binaries, tkdnd_hiddenimports = collect_all("tkinterdnd2")

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=tkdnd_binaries,
    datas=tkdnd_datas + [(str(root / "resources"), "resources"), (str(root / "ffmpeg-manifest.json"), ".")],
    hiddenimports=tkdnd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pandas", "PIL", "lxml", "openpyxl", "tensorflow", "pykakasi", "jaconv"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MoraCutter",
    icon=str(root / "resources" / "moracutter.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(root / "windows_version_info.txt"),
    manifest=str(root / "windows.manifest"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MoraCutter",
)
