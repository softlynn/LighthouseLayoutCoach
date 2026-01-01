# Brand assets

`lighthousecoach-logo.svg` (repo root) is the locked source-of-truth. Do not edit its path geometry, viewBox, or proportions.

## Regenerate PNG/ICO assets

Dependencies:

```powershell
pip install cairosvg pillow
```

Note (Windows): `cairosvg` may require the Cairo runtime DLLs. If Cairo is unavailable, the script falls back to Qt SVG rendering (requires `PySide6` with `QtSvg`).

Generate assets (from repo root):

```powershell
python .\scripts\generate_brand_assets.py
```

Outputs:
- `assets/icons/app_icon.ico`
- `assets/icons/app_icon_*.png` (16, 24, 32, 48, 64, 128, 256, 512, 1024)
- `assets/installer/installer_icon.ico`
- `assets/brand/logo_512.png`
- `assets/brand/logo_1024.png`
