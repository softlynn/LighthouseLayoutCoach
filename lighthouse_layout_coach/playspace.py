from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .chaperone import PlayArea, get_play_area

log = logging.getLogger("lighthouse_layout_coach.playspace")

Vec3 = Tuple[float, float, float]
Mat3x4 = Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float], Tuple[float, float, float, float]]


@dataclass(frozen=True)
class ResolvedPlayspace:
    play_area: PlayArea
    universe: str  # "standing"
    seated_to_standing: Optional[Mat3x4]
    source_detail: str


def _try_get_seated_to_standing(vr_system) -> Optional[Mat3x4]:
    if vr_system is None:
        return None
    fn = getattr(vr_system, "GetSeatedZeroPoseToStandingAbsoluteTrackingPose", None) or getattr(
        vr_system, "getSeatedZeroPoseToStandingAbsoluteTrackingPose", None
    )
    if fn is None:
        return None
    try:
        m = fn()
        mm = getattr(m, "m", None) or m
        return (
            (float(mm[0][0]), float(mm[0][1]), float(mm[0][2]), float(mm[0][3])),
            (float(mm[1][0]), float(mm[1][1]), float(mm[1][2]), float(mm[1][3])),
            (float(mm[2][0]), float(mm[2][1]), float(mm[2][2]), float(mm[2][3])),
        )
    except Exception:
        return None


def _try_openvrpaths_config_dir() -> Optional[Path]:
    # Best-effort: find SteamVR config paths from OpenVR's vrpath registry (local machine).
    # This is used only for diagnostic purposes (e.g., to report where SteamVR/Space Calibrator files would live).
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    vrpath = Path(base) / "openvr" / "openvrpaths.vrpath"
    if not vrpath.exists():
        return None
    try:
        obj = json.loads(vrpath.read_text(encoding="utf-8", errors="replace"))
        cfgs = obj.get("config") or []
        if cfgs and isinstance(cfgs, list):
            return Path(str(cfgs[0]))
    except Exception:
        return None
    return None


def resolve_playspace(vr_system, vr_chaperone, vr_chaperone_setup) -> ResolvedPlayspace:
    """
    Resolves the playspace bounds/origin in SteamVR standing-universe coordinates.

    Notes:
    - SteamVR chaperone bounds are treated as authoritative when available.
    - Quest/Virtual Desktop/Space Calibrator alignment is assumed to be represented by SteamVR's standing origin.
      When additional alignment sources are not detectable, we log what would be used (config locations) but do not
      invent transforms.
    """
    play_area = get_play_area(vr_chaperone, vr_chaperone_setup)
    seated_to_standing = _try_get_seated_to_standing(vr_system)

    cfg_dir = _try_openvrpaths_config_dir()
    if cfg_dir is not None:
        detail = f"{play_area.source}; steamvr_config={cfg_dir}"
    else:
        detail = play_area.source

    if play_area.source != "chaperone":
        log.info("Playspace: using default bounds (%s)", play_area.warning)
    else:
        log.info("Playspace: using SteamVR chaperone bounds")

    log.info("Playspace resolver source detail: %s", detail)
    return ResolvedPlayspace(
        play_area=play_area,
        universe="standing",
        seated_to_standing=seated_to_standing,
        source_detail=detail,
    )

