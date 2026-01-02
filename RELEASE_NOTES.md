# Release Notes

## 🕹️ Unity VR Coach (new)
- Adds a standalone Unity/OpenXR VR Coach app (no SteamVR overlays) and a launcher button to start it.
- Build via `scripts/build_unity_vr_coach.ps1` (outputs to `releases/VRCoach_Windows/` and is bundled by the installer when present).

## ✅ Brand asset pipeline
- Generate PNG/ICO assets from the locked `lighthousecoach-logo.svg` via `scripts/generate_brand_assets.py`.

## 🧰 Updated icons
- App EXE icon + window icon updated to the generated brand icon.
- Installer icon updated to the generated installer icon.

## 🛠️ VR overlay stability (legacy)
- Stabilized the SteamVR dashboard overlay lifecycle (no per-frame `ShowDashboard`, recreate cooldown + backoff).
- Hardened `SetOverlayRaw` submission with validation, retries/backoff, and clearer logs.
- Fixed `PollNextOverlayEvent` signature mismatch so overlay input events are handled (clicks now register).
- Reduced flicker by avoiding dashboard overlay recreate unless there's a sustained submission outage.
- Fixed launcher UI freezes caused by blocking overlay stdout reads.
- Added `--overlay-test` for submitting a single test frame.
  - `--overlay-test` exits cleanly when no HMD is detected (no traceback).
- Event polling checks both dashboard handles (main + thumbnail) and logs the first event name per handle to diagnose input routing.
- Mouse event coordinates are interpreted correctly whether SteamVR provides normalized (0..1) or pixel-space values.

## 📦 Installer/runtime
- Bundles VC++ Redistributable (x64) and installs it automatically if missing.
- Uses a stable runtime extraction directory under `%LOCALAPPDATA%\LighthouseLayoutCoach\tmp` to reduce Temp cleanup issues.
- Ships the app as an onedir build (no onefile extraction), which avoids intermittent `Failed to load Python DLL (python311.dll)` errors caused by `_MEI*` extraction/AV contention.
- Bundles the Unity VR Coach build under `{app}\VRCoach\` when present at build time.

## 🔄 Updates
- Launcher includes a `Check for Updates.` button (same update check used in the desktop app).

