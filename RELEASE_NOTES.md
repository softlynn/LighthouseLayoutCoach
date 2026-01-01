# Release Notes

## ✅ Brand asset pipeline
- Generate PNG/ICO assets from the locked `lighthousecoach-logo.svg` via `scripts/generate_brand_assets.py`.

## 🧰 Updated icons
- App EXE icon + window icon updated to the generated brand icon.
- Installer icon updated to the generated installer icon.

## 🛠️ VR overlay stability
- Hardened `SetOverlayRaw` submission with validation, retries/backoff, overlay handle recreation, and clearer logs.
- Added `--overlay-test` for submitting a single test frame.

## 📘 Documentation
- README updated with a prominent latest-release link and quick sections.

