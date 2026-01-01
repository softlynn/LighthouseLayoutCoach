from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .chaperone import PlayArea
from .steamvr_io import Mat3, Pose, Vec3, forward_from_rotation, mat3_mul_vec3, rot_transpose, vec_norm, vec_sub


Point2 = Tuple[float, float]


@dataclass(frozen=True)
class StationPose:
    serial: str
    position_m: Vec3
    rotation_3x3: Mat3


@dataclass(frozen=True)
class CoverageResult:
    grid_origin_m: Point2
    grid_step_m: float
    grid_w: int
    grid_h: int
    inside_mask: List[bool]
    score_foot: List[int]  # 0/1/2 per grid cell
    score_waist: List[int]  # 0/1/2 per grid cell
    overlap_pct_foot: float
    overlap_pct_waist: float
    overall_score: float  # 0..100
    station_sync_warning: Optional[str] = None


FOV_YAW_DEG = 60.0
FOV_PITCH_DEG = 45.0


def point_in_poly(pt: Point2, poly: List[Point2]) -> bool:
    # Ray casting algorithm.
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if ((y0 > y) != (y1 > y)) and (x < (x1 - x0) * (y - y0) / (y1 - y0 + 1e-12) + x0):
            inside = not inside
    return inside


def _yaw_pitch_from_station_to_point(station_rot: Mat3, station_pos: Vec3, point: Vec3) -> Tuple[float, float]:
    """
    Returns (yaw_deg, pitch_deg) of the point direction in the station's local frame,
    where local forward is -Z, right is +X, up is +Y.
    """
    dir_world = vec_norm(vec_sub(point, station_pos))
    local = mat3_mul_vec3(rot_transpose(station_rot), dir_world)
    yaw = math.degrees(math.atan2(local[0], -local[2]))
    pitch = math.degrees(math.atan2(local[1], -local[2]))
    return yaw, pitch


def station_sees_point(station: StationPose, point: Vec3) -> Tuple[bool, float]:
    """
    Returns (likely_visible, margin_deg).
    margin is the minimum remaining angular headroom to the conservative FOV edge.
    Negative margin means outside the FOV.
    """
    yaw, pitch = _yaw_pitch_from_station_to_point(station.rotation_3x3, station.position_m, point)
    margin = min(FOV_YAW_DEG - abs(yaw), FOV_PITCH_DEG - abs(pitch))
    return (margin >= 0.0), margin


def station_to_station_visibility(stations: List[StationPose]) -> Optional[str]:
    if len(stations) != 2:
        return None
    a, b = stations
    a_sees, a_margin = station_sees_point(a, b.position_m)
    b_sees, b_margin = station_sees_point(b, a.position_m)
    if a_sees and b_sees:
        return None
    return (
        "Heuristic sync check: Station A/B may not have line-of-sight to each other. "
        "Base Station 1.0 often requires optical sync; consider re-aiming or using a sync cable."
        f" (A→B margin {a_margin:.1f}°, B→A margin {b_margin:.1f}°)"
    )


def compute_coverage(
    play_area: PlayArea,
    stations: List[StationPose],
    grid_step_m: float = 0.10,
    foot_z_m: float = 0.15,
    waist_z_m: float = 1.00,
) -> CoverageResult:
    corners = play_area.corners_m
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    w = max(1, int(math.ceil((max_x - min_x) / grid_step_m)) + 1)
    h = max(1, int(math.ceil((max_y - min_y) / grid_step_m)) + 1)

    inside: List[bool] = []
    score_foot: List[int] = []
    score_waist: List[int] = []

    inside_count = 0
    overlap2_foot = 0
    overlap2_waist = 0

    centroid = play_area.centroid
    max_r = max(1e-6, max(math.hypot(x - centroid[0], y - centroid[1]) for x, y in corners))

    weighted_sum = 0.0
    weighted_max = 0.0

    for yi in range(h):
        y = min_y + yi * grid_step_m
        for xi in range(w):
            x = min_x + xi * grid_step_m
            in_poly = point_in_poly((x, y), corners)
            inside.append(in_poly)
            if not in_poly:
                score_foot.append(0)
                score_waist.append(0)
                continue

            inside_count += 1

            foot_pt = (x, y, foot_z_m)
            waist_pt = (x, y, waist_z_m)

            f_vis = 0
            w_vis = 0
            for s in stations:
                if station_sees_point(s, foot_pt)[0]:
                    f_vis += 1
                if station_sees_point(s, waist_pt)[0]:
                    w_vis += 1
            f_vis = min(2, f_vis)
            w_vis = min(2, w_vis)
            score_foot.append(f_vis)
            score_waist.append(w_vis)

            if f_vis == 2:
                overlap2_foot += 1
            if w_vis == 2:
                overlap2_waist += 1

            # Weighting heuristic: trackers spend a lot of time near center but also get occluded
            # at edges; foot coverage matters more than waist for FBT stability.
            r = math.hypot(x - centroid[0], y - centroid[1]) / max_r
            center_w = (1.0 - min(1.0, r)) ** 2
            edge_w = 1.0 - center_w
            cell_w = 0.6 * (0.7 * center_w + 0.3 * edge_w) + 0.4 * (0.9 * center_w + 0.1 * edge_w)

            cell_score = 0.6 * (f_vis / 2.0) + 0.4 * (w_vis / 2.0)
            weighted_sum += cell_w * cell_score
            weighted_max += cell_w

    overlap_pct_foot = 0.0 if inside_count == 0 else 100.0 * overlap2_foot / inside_count
    overlap_pct_waist = 0.0 if inside_count == 0 else 100.0 * overlap2_waist / inside_count
    overall = 0.0 if weighted_max <= 1e-9 else 100.0 * (weighted_sum / weighted_max)

    return CoverageResult(
        grid_origin_m=(min_x, min_y),
        grid_step_m=grid_step_m,
        grid_w=w,
        grid_h=h,
        inside_mask=inside,
        score_foot=score_foot,
        score_waist=score_waist,
        overlap_pct_foot=overlap_pct_foot,
        overlap_pct_waist=overlap_pct_waist,
        overall_score=overall,
        station_sync_warning=station_to_station_visibility(stations),
    )


def station_yaw_pitch_deg(station: StationPose) -> Tuple[float, float]:
    fwd = forward_from_rotation(station.rotation_3x3)
    yaw = math.degrees(math.atan2(fwd[1], fwd[0]))
    pitch = math.degrees(math.atan2(fwd[2], math.sqrt(fwd[0] * fwd[0] + fwd[1] * fwd[1])))
    return yaw, pitch

