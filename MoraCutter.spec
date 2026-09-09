# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

root = Path(SPEC).resolve().parent
whisper_assets = collect_data_files("faster_whisper", includes=["assets/*"])
tkdnd_datas, tkdnd_binaries, tkdnd_hiddenimports = collect_all("tkinterdnd2")
cuda_binaries = collect_dynamic_libs("nvidia.cublas", destdir=".")

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=tkdnd_binaries + cuda_binaries,
    datas=whisper_assets + tkdnd_datas,
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
