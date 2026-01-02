# LighthouseLayoutCoach

![LighthouseLayoutCoach](assets/brand/logo_512.png)

[Latest Release](https://github.com/Softlynn/LighthouseLayoutCoach/releases/latest)

Windows desktop app and Unity VR Coach to help optimize **SteamVR Base Station 1.0** placement and reduce **Vive Tracker occlusion** for hybrid setups (Quest Pro via Virtual Desktop → SteamVR, with OpenVR Space Calibrator alignment already done).

This project uses **SteamVR/OpenXR as the source of truth** (no Meta/Quest APIs).

## ✨ Features
- Desktop device/status view (stations + trackers)
- Guided setup (pick 2 base stations + label trackers)
- (Unity) VR Coach: standalone OpenXR app with clickable VR UI
- Optional SteamVR overlay mode (legacy / troubleshooting)

## 📦 Download
- Latest release: https://github.com/Softlynn/LighthouseLayoutCoach/releases/latest

## 🛠️ Build / Dev (Windows)

Python app:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m lighthouse_layout_coach
```

Unity VR Coach:
- See `docs/unity_vr_coach.md`
- Scripted build:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_unity_vr_coach.ps1
```

Packaged EXE + installer (PyInstaller + Inno Setup):
```powershell
.\scripts\build_windows.ps1
```

Outputs:
- `dist\LighthouseLayoutCoach.exe`
- `dist\Installer\LighthouseLayoutCoach_Setup.exe` (if Inno Setup compiler `ISCC.exe` is installed)
- Release assets: `dist\release_assets\`

## 🧩 VR Notes

Unity VR Coach (recommended):
- Use the launcher button **Launch VR Coach (Unity)**, or run `releases\VRCoach_Windows\LighthouseLayoutCoachVRCoach.exe` directly.

SteamVR overlay mode (legacy):
- VR overlay: `python -m lighthouse_layout_coach --vr` (alias: `--overlay`)
- Overlay smoke submit: `python -m lighthouse_layout_coach --overlay-test`

## 📁 Logs (Historical Data)
- Prior runs are stored in `%APPDATA%\LighthouseLayoutCoach\sessions\*.json`

