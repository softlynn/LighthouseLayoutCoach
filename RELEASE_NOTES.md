# Release Notes

## ✅ Brand asset pipeline
- Generate PNG/ICO assets from the locked `lighthousecoach-logo.svg` via `scripts/generate_brand_assets.py`.

## 🧰 Updated icons
- App EXE icon + window icon updated to the generated brand icon.
- Installer icon updated to the generated installer icon.

## 🛠️ VR overlay stability
- Stabilized the SteamVR dashboard overlay lifecycle (no per-frame `ShowDashboard`, recreate cooldown + backoff).
- Hardened `SetOverlayRaw` submission with validation, retries/backoff, and clearer logs.
- Fixed `PollNextOverlayEvent` wrapper-compatibility and improved handling of `OverlayError_InvalidHandle` to reduce flicker.
- Fixed launcher UI freezes caused by blocking overlay stdout reads.
- Added `--overlay-test` for submitting a single test frame.

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
