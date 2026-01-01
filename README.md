# LighthouseLayoutCoach

Windows desktop Python app to help optimize **SteamVR Base Station 1.0** placement and reduce **Vive Tracker occlusion** for a hybrid setup (Quest Pro via Virtual Desktop → SteamVR, with OpenVR Space Calibrator alignment already done).

This app uses **SteamVR/OpenVR as the source of truth** (no Meta/Quest APIs).

## Install

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

## Run

1) Start Virtual Desktop → SteamVR
2) Ensure Quest Pro + Vive Trackers are visible in SteamVR
3) Run:

```powershell
python -m lighthouse_layout_coach
```

This opens a small launcher window with:
- **Desktop App** (the existing PySide6 UI)
- **VR Overlay Mode** (starts a local JSON state server + a SteamVR dashboard overlay panel)

### CLI

- Desktop UI: `python -m lighthouse_layout_coach --desktop`
- VR overlay: `python -m lighthouse_layout_coach --vr` (alias: `--overlay`)

## Typical workflow

1) **Devices tab**: verify SteamVR connection and device list updates live.
2) **Select Trackers**: label exactly 3 trackers as Left Foot / Right Foot / Waist (persisted by serial).
3) **Select Base Stations**: confirm Station A/B (persisted by serial).
4) **Layout tab**: review play area, station facing arrows, live tracker points, and estimated foot/waist coverage heatmap.
5) **Diagnostics tab**:
   - Run the guided 60s diagnostic test.
   - Save session (auto-saved to `%APPDATA%\LighthouseLayoutCoach\sessions\`).
   - Optionally pick any saved session as a **Baseline** and compare.
   - Use **Export Report** to write `*_summary.txt` + `*_session.json` to `%APPDATA%\LighthouseLayoutCoach\export\`.

## Notes / limitations

- Coverage heatmap and station-to-station visibility are **heuristics** (geometric FOV estimate), not sensor-accurate.
- Base Station 1.0 may require line-of-sight for optical sync; the app flags likely sync issues as a heuristic.

## VR Overlay Mode

VR Overlay Mode runs:
- A local state server at `http://127.0.0.1:17835/state`
- A SteamVR **dashboard overlay panel** that renders at ~20 FPS

The overlay shows:
- Station A/B: height, yaw, pitch, aim error to play area centroid
- Coverage overlap: foot and waist
- Live tracker OK/not OK + dropouts + rolling jitter
- Actionable Station A/B recommendations
- Button to trigger the same guided 60s diagnostic

### Troubleshooting

- SteamVR must be running before starting VR Overlay Mode (the launcher will keep retrying internally).
- Allow localhost traffic if a firewall prompts (server binds to `127.0.0.1` only).
- If the overlay panel does not appear in the SteamVR dashboard, restart SteamVR and try VR Overlay Mode again.

## First-Run Wizard

On first launch, the desktop app shows a setup wizard to:
- Confirm SteamVR connection
- Select and label 3 trackers + 2 base stations (persisted by serial)
- Confirm play area/chaperone bounds
- Optionally run a short baseline capture

You can re-run it from **Help → Re-run Setup Wizard…**

## Auto Updates (Approach A)

The app can check GitHub Releases for a newer version and (if found) download and run the installer.
- **Help → Check for Updates…**
- Also checks automatically at startup (at most once per 24h)

Note: builds are unsigned by default; Windows SmartScreen may warn on download/run.

## Build & Installer (Windows)

Build with PyInstaller:

```powershell
.\scripts\build_windows.ps1
```

Outputs:
- `dist\LighthouseLayoutCoach.exe`
- `dist\Installer\LighthouseLayoutCoach_Setup.exe` (if Inno Setup compiler `ISCC.exe` is installed)

Release assets (only these two files; suitable for GitHub Releases uploads):
- `dist\release_assets\LighthouseLayoutCoach.exe`
- `dist\release_assets\LighthouseLayoutCoach_Setup.exe`

## Releasing (GitHub Actions)

1) Update `VERSION` to `X.Y.Z`
2) Commit and push to `main`
3) Create and push a tag `vX.Y.Z`

GitHub Actions builds on tag push and uploads only the two files from `dist\release_assets\` to the GitHub Release.
