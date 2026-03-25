# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


pil_datas = collect_data_files('PIL')
pil_hiddenimports = collect_submodules('PIL')


a = Analysis(
    ['vm_agent\\src\\service\\agent_service.py'],
    pathex=['.'],
    binaries=[],
    datas=pil_datas,
    hiddenimports=['win32serviceutil', 'win32service', 'win32timezone', 'win32event', 'servicemanager', 'PIL', 'PIL.Image', *pil_hiddenimports],
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
    a.binaries,
    a.datas,
    [],
    name='agent_service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
