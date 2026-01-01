# PyInstaller spec to build an onedir app folder for the installer.
# This avoids onefile _MEI extraction issues (DLL load errors / temp cleanup races).

import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# When PyInstaller exec()'s the spec, __file__ may not be set in some environments.
# The build script runs from the repo root, so use CWD as the project base.
basedir = os.path.abspath(os.getcwd())

hiddenimports = []
hiddenimports += collect_submodules("vr_overlay")
hiddenimports += ["openvr"]

binaries = []
# openvr uses ctypes to load libopenvr_api_64.dll at runtime; bundle the DLL explicitly.
binaries += collect_dynamic_libs("openvr")

datas = [
    (os.path.join(basedir, "VERSION"), "."),
    (os.path.join(basedir, "assets", "icons", "app_icon.ico"), os.path.join("assets", "icons")),
]

a = Analysis(
    [os.path.join(basedir, "lighthouse_layout_coach", "__main__.py")],
    pathex=[basedir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LighthouseLayoutCoach",
    icon=os.path.join(basedir, "assets", "icons", "app_icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LighthouseLayoutCoach",
)

