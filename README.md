# LighthouseLayoutCoach

![LighthouseLayoutCoach](assets/brand/logo_512.png)

[Latest Release](https://github.com/Softlynn/LighthouseLayoutCoach/releases/latest)

Windows desktop app to help optimize **SteamVR Base Station 1.0** placement and reduce **Vive Tracker occlusion** for a hybrid setup (Quest Pro via Virtual Desktop → SteamVR, with OpenVR Space Calibrator alignment already done).

This app uses **SteamVR/OpenVR as the source of truth** (no Meta/Quest APIs).

## ✨ Features

- Live SteamVR device status (stations + trackers)
- Guided setup (pick 2 base stations + label 3 trackers by serial)
- Play-area layout view + heuristic coverage visualization
- VR Overlay Mode: SteamVR dashboard panel fed by a local state server

## 📦 Download

- Latest release: https://github.com/Softlynn/LighthouseLayoutCoach/releases/latest

## 🛠️ Build / Dev (Windows)

1) Install Python 3.10+ (64-bit recommended)
2) Create and activate a venv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3) Install dependencies:

```powershell
pip install -r requirements.txt
```

4) Run:

```powershell
python -m lighthouse_layout_coach
```

Build EXE + optional installer:

```powershell
.\scripts\build_windows.ps1
```

Outputs:
- `dist\LighthouseLayoutCoach.exe`
- `dist\Installer\LighthouseLayoutCoach_Setup.exe` (if Inno Setup compiler `ISCC.exe` is installed)
- Release assets: `dist\release_assets\`

## 🧩 VR Overlay Notes

Commands:
- Desktop UI: `python -m lighthouse_layout_coach --desktop`
- VR overlay: `python -m lighthouse_layout_coach --vr` (alias: `--overlay`)
- Overlay smoke submit: `python -m lighthouse_layout_coach --overlay-test`

Requirements:
- SteamVR running before starting VR Overlay Mode
- Allow localhost traffic if prompted (binds to `127.0.0.1` only)

Troubleshooting:
- If the overlay panel doesn’t appear in the SteamVR dashboard, restart SteamVR and try again.

