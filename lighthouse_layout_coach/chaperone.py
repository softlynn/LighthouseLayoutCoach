from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


Point2 = Tuple[float, float]


@dataclass(frozen=True)
class PlayArea:
    corners_m: List[Point2]  # polygon in standing universe, clockwise or CCW
    source: str  # "chaperone" | "default"
    warning: Optional[str] = None

    @property
    def centroid(self) -> Point2:
        xs = [p[0] for p in self.corners_m]
        ys = [p[1] for p in self.corners_m]
        return (sum(xs) / max(1, len(xs)), sum(ys) / max(1, len(ys)))


def _vec3_to_xy(v) -> Point2:
    # v may be HmdVector3_t with v[0], v[1], v[2], or an object with .v
    if hasattr(v, "v"):
        vv = v.v
        return (float(vv[0]), float(vv[1]))
    return (float(v[0]), float(v[1]))


def get_play_area(vr_chaperone, vr_chaperone_setup) -> PlayArea:
    """
    Returns the play area bounds as a 2D polygon in meters (standing universe).

    Preferred source is IVRChaperone.GetPlayAreaRect() which yields a quad.
    If unavailable, returns a default 2m x 2m square centered at origin with warning.
    """
    # 1) Try live play area rect (most common and stable)
    try:
        if vr_chaperone is not None:
            quad = getattr(vr_chaperone, "GetPlayAreaRect", None) or getattr(vr_chaperone, "getPlayAreaRect", None)
            if quad is not None:
                res = quad()
                if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool):
                    ok, rect = res
                else:
                    ok, rect = True, res
                if ok and rect is not None:
                    corners = [_vec3_to_xy(rect.vCorners[i]) for i in range(4)]
                    return PlayArea(corners_m=corners, source="chaperone")
    except Exception:
        pass

    # 2) Try collision bounds as a polygon (best-effort)
    try:
        if vr_chaperone_setup is not None:
            getter = getattr(vr_chaperone_setup, "GetLiveCollisionBoundsInfo", None) or getattr(
                vr_chaperone_setup, "getLiveCollisionBoundsInfo", None
            )
            if getter is not None:
                ok, quads = getter()
                if ok and quads:
                    # Use the first quad as an approximation (many rooms provide multiple quads).
                    corners = [_vec3_to_xy(quads[0].vCorners[i]) for i in range(4)]
                    return PlayArea(corners_m=corners, source="chaperone")
    except Exception:
        pass

    half = 1.0
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    return PlayArea(
        corners_m=corners,
        source="default",
        warning="Chaperone bounds unavailable; using default 2m x 2m square centered at origin.",
    )
