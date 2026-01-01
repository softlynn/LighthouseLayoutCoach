# PyInstaller spec to build a single launcher EXE that can start:
# - Desktop UI mode
# - VR overlay mode (state server + overlay client)

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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LighthouseLayoutCoach",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
