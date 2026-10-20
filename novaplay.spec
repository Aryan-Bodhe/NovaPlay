# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("assets", "assets")
]
datas += collect_data_files("babelfish")
hiddenimports = collect_submodules("babelfish")


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Use the host's LibVLC installation on Debian/Ubuntu.
# VLC must be declared as a package dependency.
VLC_SYSTEM_LIBRARIES = {
    "libvlc.so.5",
    "libvlccore.so.9",
}

a.binaries = [
    entry for entry in a.binaries
    if entry[0] not in VLC_SYSTEM_LIBRARIES
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='novaplay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.png'],
)
