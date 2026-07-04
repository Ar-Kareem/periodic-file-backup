# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


env_dir = Path.cwd() / 'env'
tcl_dir = env_dir / 'Library' / 'lib' / 'tcl8.6'
tk_dir = env_dir / 'Library' / 'lib' / 'tk8.6'
tcl_dll = env_dir / 'Library' / 'bin' / 'tcl86t.dll'
tk_dll = env_dir / 'Library' / 'bin' / 'tk86t.dll'
icon_file = Path.cwd() / 'periodic-file-backup.ico'


a = Analysis(
    ['src/gui.py'],
    pathex=[],
    binaries=[
        (str(tcl_dll), '.'),
        (str(tk_dll), '.'),
    ],
    datas=[
        (str(tcl_dir), '_tcl_data'),
        (str(tk_dir), '_tk_data'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['src/pyi_rth_tcl_tk.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='periodic-file-backup',
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
    icon=str(icon_file),
)
