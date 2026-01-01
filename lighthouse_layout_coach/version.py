from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []

    # PyInstaller
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        roots.append(Path(mei))

    # Next to the executable
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass

    # Source checkout (repo root is parent of package)
    try:
        roots.append(Path(__file__).resolve().parents[1])
    except Exception:
        pass

    # Deduplicate while preserving order
    seen = set()
    out = []
    for r in roots:
        rr = str(r)
        if rr in seen:
            continue
        seen.add(rr)
        out.append(r)
    return out


def read_version() -> str:
    """
    Reads the app version from the root `VERSION` file (bundled into the build).
    """
    for root in _candidate_roots():
        p = root / "VERSION"
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                continue
    return "0.0.0"


def parse_semver(tag: str) -> Optional[tuple[int, int, int]]:
    s = tag.strip()
    if s.startswith("v"):
        s = s[1:]
    parts = s.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def is_newer(remote_tag: str, local_version: str) -> bool:
    r = parse_semver(remote_tag)
    l = parse_semver(local_version)
    if r is None or l is None:
        return False
    return r > l

