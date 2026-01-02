# Release Notes

## ✅ Brand asset pipeline
- Generate PNG/ICO assets from the locked `lighthousecoach-logo.svg` via `scripts/generate_brand_assets.py`.

## 🧰 Updated icons
- App EXE icon + window icon updated to the generated brand icon.
- Installer icon updated to the generated installer icon.

## 🛠️ VR overlay stability
- Stabilized the SteamVR dashboard overlay lifecycle (no per-frame `ShowDashboard`, recreate cooldown + backoff).
- Hardened `SetOverlayRaw` submission with validation, retries/backoff, and clearer logs.
- Fixed `PollNextOverlayEvent` signature mismatch so overlay input events are handled (clicks now register).
- Reduced flicker by avoiding dashboard overlay recreate unless there’s a sustained submission outage.
- Fixed launcher UI freezes caused by blocking overlay stdout reads.
- Added `--overlay-test` for submitting a single test frame.
  - `--overlay-test` now exits cleanly when no HMD is detected (no traceback).
  - Dashboard overlay input is explicitly enabled via OpenVR overlay flags and mouse-scale mapping.
  - Event polling now checks both dashboard handles (main + thumbnail) and logs the first event name per handle to diagnose input routing.

## 🧭 Playspace + data
- Playspace resolution uses SteamVR chaperone bounds when available (with clear source logging).
- Optional historical log ingestion from `%APPDATA%\\LighthouseLayoutCoach\\sessions\\*.json` for tracking-quality heatmaps.

## 🧩 Dual-mode VR
- Dashboard Panel: lightweight controls + quick status.
- VR Coach: separate world overlay showing playspace + base stations + trackers, with toggles for heatmap/body suggestions.

## 📘 Documentation
- README updated with a prominent latest-release link, dual-mode notes, and log/playspace documentation.

## Installer/runtime
- Bundles VC++ Redistributable (x64) and installs it automatically if missing.
- Uses a stable runtime extraction directory under `%LOCALAPPDATA%\\LighthouseLayoutCoach\\tmp` to reduce Temp cleanup issues.

## Updates
- Launcher now includes a `Check for Updates…` button (same update check used in the desktop app).

## Temp cleanup mitigation
- Added an optional onedir `LighthouseLayoutCoachOverlay.exe` helper to avoid PyInstaller onefile `_MEI*` temp cleanup warnings when starting/stopping VR mode.

## Installer stability
- Installer now ships the app as an onedir build (no onefile extraction), which avoids intermittent `Failed to load Python DLL (python311.dll)` errors caused by `_MEI*` extraction/AV contention.
