from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .coverage import StationPose, station_sees_point
from .steamvr_io import Pose


@dataclass(frozen=True)
class DropoutEvent:
    start_s: float
    end_s: float
    duration_s: float
    hmd_yaw_deg: Optional[float]
    likely_station_serial: Optional[str]
    station_margins_deg: Dict[str, float]


@dataclass(frozen=True)
class TrackerMetrics:
    serial: str
    role: str
    dropout_count: int
    dropout_duration_s: float
    jitter_pos_rms_m_p50: float
    jitter_pos_rms_m_p95: float
    jitter_yaw_deg_p50: float
    jitter_yaw_deg_p95: float
    dropout_yaw_bins: Dict[str, int]  # "0-10", "10-20", ...
    dropouts: List[DropoutEvent]


@dataclass(frozen=True)
class SessionMetrics:
    per_tracker: List[TrackerMetrics]


def is_tracking_ok(pose: Optional[Pose]) -> bool:
    if pose is None:
        return False
    return bool(pose.pose_valid and int(pose.tracking_result) == 200)  # TrackingResult_Running_OK is 200


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = int(round((pct / 100.0) * (len(xs) - 1)))
    k = max(0, min(len(xs) - 1, k))
    return float(xs[k])


def _wrap_deg(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return a


def _yaw_bin_label(yaw_deg: float, bin_deg: int = 10) -> str:
    y = yaw_deg % 360.0
    start = int(y // bin_deg) * bin_deg
    end = start + bin_deg
    return f"{start}-{end}"


def _infer_likely_station(
    stations: List[StationPose],
    tracker_pose: Pose,
) -> Tuple[Optional[str], Dict[str, float]]:
    margins: Dict[str, float] = {}
    visible: Dict[str, bool] = {}
    for s in stations:
        ok, margin = station_sees_point(s, tracker_pose.position_m)
        margins[s.serial] = float(margin)
        visible[s.serial] = bool(ok)
    if len(stations) == 2:
        s0, s1 = stations[0].serial, stations[1].serial
        if visible.get(s0) and not visible.get(s1):
            return s1, margins
        if visible.get(s1) and not visible.get(s0):
            return s0, margins
    return None, margins


def analyze_diagnostic_session(
    samples: List[Dict],
    tracker_roles_by_serial: Dict[str, str],
    stations: List[StationPose],
) -> SessionMetrics:
    """
    Analyzes a diagnostic capture.

    Expected `samples` elements:
      {
        "t_s": float,
        "hmd_yaw_deg": float|None,
        "trackers": { serial: { "pos": [x,y,z], "yaw_deg": float, "ok": bool } }
      }
    """
    per_tracker: List[TrackerMetrics] = []

    tracker_serials = list(tracker_roles_by_serial.keys())
    tracker_serials.sort()

    for serial in tracker_serials:
        role = tracker_roles_by_serial.get(serial, "Unknown")

        ok_prev = False
        dropout_start: Optional[float] = None
        dropout_yaw: Optional[float] = None
        dropout_pose: Optional[Pose] = None
        dropouts: List[DropoutEvent] = []
        yaw_bins: Dict[str, int] = {}

        pos_jitter: List[float] = []
        yaw_jitter: List[float] = []

        # Rolling 1s window buffers (time, pos, yaw), filtered to OK poses.
        window: List[Tuple[float, Tuple[float, float, float], float]] = []

        for s in samples:
            t = float(s["t_s"])
            hmd_yaw = s.get("hmd_yaw_deg", None)
            tr = s.get("trackers", {}).get(serial, None)
            if tr is None:
                ok = False
                pose = None
            else:
                ok = bool(tr.get("ok", False))
                pos = tr.get("pos", [0.0, 0.0, 0.0])
                yaw = float(tr.get("yaw_deg", 0.0))
                pose = Pose(position_m=(float(pos[0]), float(pos[1]), float(pos[2])), rotation_3x3=((1, 0, 0), (0, 1, 0), (0, 0, 1)), pose_valid=True, tracking_result=200)  # rot not required here

            if ok and tr is not None:
                pos = tuple(tr.get("pos", [0.0, 0.0, 0.0]))
                yaw = float(tr.get("yaw_deg", 0.0))
                window.append((t, (float(pos[0]), float(pos[1]), float(pos[2])), yaw))

                # keep last 1s
                t_min = t - 1.0
                while window and window[0][0] < t_min:
                    window.pop(0)

                if len(window) >= 5:
                    mx = sum(p[0] for _, p, _ in window) / len(window)
                    my = sum(p[1] for _, p, _ in window) / len(window)
                    mz = sum(p[2] for _, p, _ in window) / len(window)
                    vx = sum((p[0] - mx) ** 2 for _, p, _ in window) / len(window)
                    vy = sum((p[1] - my) ** 2 for _, p, _ in window) / len(window)
                    vz = sum((p[2] - mz) ** 2 for _, p, _ in window) / len(window)
                    pos_rms = math.sqrt(vx + vy + vz)
                    pos_jitter.append(pos_rms)

                    # circular yaw stddev approximation via wrapped diffs to mean yaw
                    yaws = [yy for _, _, yy in window]
                    ssum = sum(math.sin(math.radians(yy)) for yy in yaws)
                    csum = sum(math.cos(math.radians(yy)) for yy in yaws)
                    mean = math.degrees(math.atan2(ssum, csum)) if (ssum != 0.0 or csum != 0.0) else yaws[0]
                    diffs = [_wrap_deg(yy - mean) for yy in yaws]
                    yaw_std = math.sqrt(sum(d * d for d in diffs) / len(diffs))
                    yaw_jitter.append(float(yaw_std))

            # Dropout detection on "OK" state
            if ok_prev and not ok:
                dropout_start = t
                dropout_yaw = float(hmd_yaw) if hmd_yaw is not None else None
                if dropout_yaw is not None:
                    lab = _yaw_bin_label(dropout_yaw)
                    yaw_bins[lab] = yaw_bins.get(lab, 0) + 1
                dropout_pose = pose
            elif (not ok_prev) and ok and dropout_start is not None:
                end = t
                dur = max(0.0, end - dropout_start)
                likely_station, margins = (None, {})
                if dropout_pose is not None and stations:
                    likely_station, margins = _infer_likely_station(stations, dropout_pose)
                dropouts.append(
                    DropoutEvent(
                        start_s=float(dropout_start),
                        end_s=float(end),
                        duration_s=float(dur),
                        hmd_yaw_deg=dropout_yaw,
                        likely_station_serial=likely_station,
                        station_margins_deg=margins,
                    )
                )
                dropout_start = None
                dropout_yaw = None
                dropout_pose = None

            ok_prev = ok

        # If session ends during dropout, close it at last timestamp
        if dropout_start is not None and samples:
            end = float(samples[-1]["t_s"])
            dur = max(0.0, end - dropout_start)
            likely_station, margins = (None, {})
            if dropout_pose is not None and stations:
                likely_station, margins = _infer_likely_station(stations, dropout_pose)
            dropouts.append(
                DropoutEvent(
                    start_s=float(dropout_start),
                    end_s=float(end),
                    duration_s=float(dur),
                    hmd_yaw_deg=dropout_yaw,
                    likely_station_serial=likely_station,
                    station_margins_deg=margins,
                )
            )

        per_tracker.append(
            TrackerMetrics(
                serial=serial,
                role=role,
                dropout_count=len(dropouts),
                dropout_duration_s=sum(d.duration_s for d in dropouts),
                jitter_pos_rms_m_p50=_percentile(pos_jitter, 50),
                jitter_pos_rms_m_p95=_percentile(pos_jitter, 95),
                jitter_yaw_deg_p50=_percentile(yaw_jitter, 50),
                jitter_yaw_deg_p95=_percentile(yaw_jitter, 95),
                dropout_yaw_bins=yaw_bins,
                dropouts=dropouts,
            )
        )

    return SessionMetrics(per_tracker=per_tracker)
