from __future__ import annotations

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional


PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def _import_pillow():
    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Missing dependency: pillow. Install with: pip install pillow"
        ) from e
    return Image


def _try_render_cairosvg(svg_path: Path, size_px: int):
    Image = _import_pillow()
    try:
        import cairosvg  # type: ignore
    except Exception:
        return None

    try:
        png_bytes = cairosvg.svg2png(
            url=str(svg_path),
            output_width=int(size_px),
            output_height=int(size_px),
        )
    except OSError:
        # Common on Windows when the Cairo runtime DLLs are not installed.
        return None

    img = Image.open(BytesIO(png_bytes))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    if img.size != (size_px, size_px):
        raise RuntimeError(
            f"Rendered size mismatch for {svg_path}: expected {(size_px, size_px)}, got {img.size}"
        )
    return img


def _try_render_qt(svg_path: Path, size_px: int):
    Image = _import_pillow()
    try:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except Exception:
        return None

    img = QImage(size_px, size_px, QImage.Format.Format_RGBA8888)
    img.fill(QColor(0, 0, 0, 0))

    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        return None

    p = QPainter(img)
    renderer.render(p, QRectF(0, 0, size_px, size_px))
    p.end()

    buf = img.bits()
    raw = buf.tobytes()
    if len(raw) != img.sizeInBytes():
        return None
    pil = Image.frombuffer("RGBA", (size_px, size_px), raw, "raw", "RGBA", 0, 1)
    if pil.mode != "RGBA":
        pil = pil.convert("RGBA")
    return pil


def _render_rgba_png(svg_path: Path, size_px: int):
    rendered = _try_render_cairosvg(svg_path, size_px=size_px)
    if rendered is not None:
        return rendered

    rendered = _try_render_qt(svg_path, size_px=size_px)
    if rendered is not None:
        return rendered

    raise RuntimeError(
        "Failed to render SVG.\n"
        "- Preferred: install cairo runtime for cairosvg (Windows) and ensure `pip install cairosvg pillow` works.\n"
        "- Fallback: install PySide6 with QtSvg to render via Qt."
    )


def _write_png(svg_path: Path, out_path: Path, size_px: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = _render_rgba_png(svg_path, size_px=size_px)
    img.save(out_path, format="PNG")


def _write_ico(svg_path: Path, out_path: Path, sizes: Iterable[int]) -> None:
    _import_pillow()
    size_list = sorted({int(s) for s in sizes})
    if not size_list:
        raise ValueError("ICO sizes list is empty")

    images_by_size = {s: _render_rgba_png(svg_path, size_px=s) for s in size_list}

    # Prefer embedding pre-rendered images for each size to avoid post-resize blur.
    # Pillow's ICO plugin supports multi-image saving via append_images (implementation-dependent).
    ordered = [images_by_size[s] for s in sorted(size_list, reverse=True)]
    base, rest = ordered[0], ordered[1:]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(
        out_path,
        format="ICO",
        append_images=rest,
        sizes=[(s, s) for s in size_list],
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="Generate LighthouseLayoutCoach brand PNGs/ICOs from the locked SVG.")
    ap.add_argument(
        "--input",
        default=None,
        help="Path to source SVG (defaults to repo-root lighthousecoach-logo.svg).",
    )
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    svg_path = Path(args.input).resolve() if args.input else (repo_root / "lighthousecoach-logo.svg")
    if not svg_path.exists():
        print(f"ERROR: SVG not found: {svg_path}", file=sys.stderr)
        return 2

    icons_dir = repo_root / "assets" / "icons"
    installer_dir = repo_root / "assets" / "installer"
    brand_dir = repo_root / "assets" / "brand"

    # App PNG set
    for s in PNG_SIZES:
        _write_png(svg_path, icons_dir / f"app_icon_{s}.png", size_px=s)

    # Brand logo sizes (explicit names)
    _write_png(svg_path, brand_dir / "logo_512.png", size_px=512)
    _write_png(svg_path, brand_dir / "logo_1024.png", size_px=1024)

    # ICOs
    _write_ico(svg_path, icons_dir / "app_icon.ico", sizes=ICO_SIZES)
    _write_ico(svg_path, installer_dir / "installer_icon.ico", sizes=ICO_SIZES)

    print("Generated:")
    print(f"- {icons_dir / 'app_icon.ico'}")
    for s in PNG_SIZES:
        print(f"- {icons_dir / f'app_icon_{s}.png'}")
    print(f"- {installer_dir / 'installer_icon.ico'}")
    print(f"- {brand_dir / 'logo_512.png'}")
    print(f"- {brand_dir / 'logo_1024.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
