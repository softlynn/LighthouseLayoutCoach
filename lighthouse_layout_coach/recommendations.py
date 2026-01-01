from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .chaperone import PlayArea
from .coverage import CoverageResult, StationPose, station_yaw_pitch_deg
from .metrics import SessionMetrics


@dataclass(frozen=True)
class Recommendation:
    target: str  # "Station A" | "Station B" | "General"
    text: str
    confidence: str  # "Low" | "Med" | "High"


def _angle_diff_deg(a: float, b: float) -> float:
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def _desired_yaw_deg(from_xy: Tuple[float, float], to_xy: Tuple[float, float]) -> float:
    dx = to_xy[0] - from_xy[0]
    dy = to_xy[1] - from_xy[1]
    return math.degrees(math.atan2(dy, dx))


def generate_recommendations(
    play_area: PlayArea,
    stations: List[StationPose],
    coverage: Optional[CoverageResult],
    metrics: Optional[SessionMetrics],
    station_labels_by_serial: Optional[Dict[str, str]] = None,
) -> List[Recommendation]:
    station_labels_by_serial = station_labels_by_serial or {}
    recs: List[Recommendation] = []

    centroid_xy = play_area.centroid

    # Coverage-driven global hints
    if coverage is not None:
        if coverage.overlap_pct_foot < 55.0:
            recs.append(
                Recommendation(
                    target="General",
                    text=(
                        f"Foot-height 2-station overlap is low ({coverage.overlap_pct_foot:.1f}%). "
                        "Favor higher mounts and slightly more downward tilt to improve tracker visibility near the floor."
                    ),
                    confidence="Med" if coverage.overlap_pct_foot > 35.0 else "High",
                )
            )
        if coverage.station_sync_warning:
            recs.append(Recommendation(target="General", text=coverage.station_sync_warning, confidence="Med"))

    # Diagnostic-derived hints
    likely_station_counts: Dict[str, int] = {}
    worst_yaw_bin: Optional[str] = None
    worst_yaw_bin_count = 0
    if metrics is not None:
        for tm in metrics.per_tracker:
            for d in tm.dropouts:
                if d.likely_station_serial:
                    likely_station_counts[d.likely_station_serial] = likely_station_counts.get(d.likely_station_serial, 0) + 1
            for lab, c in tm.dropout_yaw_bins.items():
                if c > worst_yaw_bin_count:
                    worst_yaw_bin = lab
                    worst_yaw_bin_count = c
        if worst_yaw_bin and worst_yaw_bin_count >= 3:
            recs.append(
                Recommendation(
                    target="General",
                    text=(
                        f"Dropouts cluster at HMD yaw bin {worst_yaw_bin}°. "
                        "Check for body/self-occlusion or reflective surfaces in that direction (mirrors/TV/windows)."
                    ),
                    confidence="Med",
                )
            )

    # Station-specific geometry hints (height/yaw/tilt)
    for idx, s in enumerate(stations[:2]):
        label = station_labels_by_serial.get(s.serial, f"Station {'A' if idx == 0 else 'B'}")
        yaw, pitch = station_yaw_pitch_deg(s)
        desired_yaw = _desired_yaw_deg((s.position_m[0], s.position_m[1]), centroid_xy)
        yaw_err = _angle_diff_deg(desired_yaw, yaw)

        if abs(yaw_err) >= 6.0:
            recs.append(
                Recommendation(
                    target=label,
                    text=f"Yaw {yaw_err:+.0f}° toward play area center (current yaw {yaw:.0f}°, target {desired_yaw:.0f}°).",
                    confidence="Med",
                )
            )

        z = s.position_m[2]
        if z < 2.0:
            recs.append(
                Recommendation(
                    target=label,
                    text=f"Raise mount +{(2.2 - z):.1f}m (current {z:.1f}m; target ~2.1–2.4m) to reduce body occlusion.",
                    confidence="High" if z < 1.7 else "Med",
                )
            )

        # Desired tilt: aim slightly downward toward a point near the center at waist height.
        dx = centroid_xy[0] - s.position_m[0]
        dy = centroid_xy[1] - s.position_m[1]
        horiz = math.hypot(dx, dy)
        target_pitch = math.degrees(math.atan2(1.0 - z, max(1e-6, horiz)))  # point at z=1.0m
        pitch_err = _angle_diff_deg(target_pitch, pitch)
        if abs(pitch_err) >= 6.0:
            direction = "down" if pitch_err < 0 else "up"
            recs.append(
                Recommendation(
                    target=label,
                    text=f"Tilt {direction} ~{abs(pitch_err):.0f}° toward center (current pitch {pitch:.0f}°, target {target_pitch:.0f}°).",
                    confidence="Low" if horiz < 1.0 else "Med",
                )
            )

        # If diagnostics points to a station as likely culprit, surface that prominently.
        c = likely_station_counts.get(s.serial, 0)
        if c >= 3:
            recs.append(
                Recommendation(
                    target=label,
                    text=f"Diagnostics: {c} dropouts were geometrically more consistent with occlusion from this station; consider re-aiming and clearing line-of-sight.",
                    confidence="High" if c >= 6 else "Med",
                )
            )

    if not recs:
        recs.append(
            Recommendation(
                target="General",
                text="No strong issues detected from current geometric estimate; run a 60s diagnostic test to generate evidence-based recommendations.",
                confidence="Low",
            )
        )

    # Keep output stable: Station A/B before General.
    def _sort_key(r: Recommendation) -> Tuple[int, str]:
        if r.target.startswith("Station A"):
            return (0, r.text)
        if r.target.startswith("Station B"):
            return (1, r.text)
        return (2, r.text)

    return sorted(recs, key=_sort_key)

