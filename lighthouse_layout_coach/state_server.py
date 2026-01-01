from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

import openvr

from .chaperone import PlayArea, get_play_area
from .coverage import CoverageResult, StationPose, compute_coverage, station_yaw_pitch_deg
from .metrics import SessionMetrics, analyze_diagnostic_session
from .recommendations import generate_recommendations
from .storage import load_config, save_config, save_session

log = logging.getLogger("lighthouse_layout_coach.state_server")

Vec3 = Tuple[float, float, float]
Mat3 = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


def _safe_call(obj, pascal: str, camel: str, *args, **kwargs):
    if hasattr(obj, camel):
        return getattr(obj, camel)(*args, **kwargs)
    return getattr(obj, pascal)(*args, **kwargs)


def _angle_diff_deg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def _aim_yaw_deg(from_xy: Tuple[float, float], to_xy: Tuple[float, float]) -> float:
    dx = to_xy[0] - from_xy[0]
    dy = to_xy[1] - from_xy[1]
    return math.degrees(math.atan2(dy, dx))


@dataclass(frozen=True)
class Pose:
    position_m: Vec3
    rotation_3x3: Mat3
    pose_valid: bool
    tracking_result: int

    @property
    def yaw_deg(self) -> float:
        # OpenVR forward is -Z; yaw in XY plane.
        fwd = (-self.rotation_3x3[0][2], -self.rotation_3x3[1][2], -self.rotation_3x3[2][2])
        return math.degrees(math.atan2(fwd[1], fwd[0]))


def _matrix34_to_pose(tracked_pose) -> Pose:
    m34 = tracked_pose.mDeviceToAbsoluteTracking
    m = getattr(m34, "m", None) or m34
    r00, r01, r02, tx = m[0]
    r10, r11, r12, ty = m[1]
    r20, r21, r22, tz = m[2]
    rot: Mat3 = ((r00, r01, r02), (r10, r11, r12), (r20, r21, r22))
    return Pose(
        position_m=(float(tx), float(ty), float(tz)),
        rotation_3x3=rot,
        pose_valid=bool(tracked_pose.bPoseIsValid),
        tracking_result=int(tracked_pose.eTrackingResult),
    )


def _diagnostic_stage(t: float) -> str:
    if t < 10.0:
        return "0–10s: Stand still at center"
    if t < 25.0:
        return "10–25s: Slow 360° turn"
    if t < 35.0:
        return "25–35s: Squat + stand"
    if t < 50.0:
        return "35–50s: Step side-to-side"
    if t < 55.0:
        return "50–55s: Face Station A"
    if t < 60.0:
        return "55–60s: Face Station B"
    return "Finishing…"


def _compute_jitter(window: List[Tuple[float, Vec3, float]]) -> Tuple[float, float]:
    if not window or len(window) < 5:
        return 0.0, 0.0
    xs = [p[0] for _, p, _ in window]
    ys = [p[1] for _, p, _ in window]
    zs = [p[2] for _, p, _ in window]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    mz = sum(zs) / len(zs)
    vx = sum((x - mx) ** 2 for x in xs) / len(xs)
    vy = sum((y - my) ** 2 for y in ys) / len(ys)
    vz = sum((z - mz) ** 2 for z in zs) / len(zs)
    pos_rms_m = math.sqrt(vx + vy + vz)

    yaws = [yaw for _, _, yaw in window]
    ssum = sum(math.sin(math.radians(yy)) for yy in yaws)
    csum = sum(math.cos(math.radians(yy)) for yy in yaws)
    mean = math.degrees(math.atan2(ssum, csum)) if (ssum != 0.0 or csum != 0.0) else yaws[0]
    diffs = [((yy - mean + 180.0) % 360.0) - 180.0 for yy in yaws]
    yaw_std = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    return pos_rms_m * 1000.0, float(yaw_std)


@dataclass
class TrackerLiveStats:
    prev_ok: bool = False
    dropouts: int = 0
    window: List[Tuple[float, Vec3, float]] = field(default_factory=list)
    connected: bool = False
    tracking_ok: bool = False
    jitter_pos_mm: float = 0.0
    jitter_yaw_deg: float = 0.0
    last_pos_m: Optional[Vec3] = None
    last_yaw_deg: float = 0.0


class StateEngine:
    """
    Background OpenVR poller + diagnostics runner. Designed for use by an in-VR overlay and an HTTP JSON API.
    """

    def __init__(self, poll_hz: float = 30.0) -> None:
        self._poll_hz = float(poll_hz)
        self._lock = threading.RLock()
        self._stop = threading.Event()

        self._cfg = load_config()
        self._connected = False
        self._last_error: Optional[str] = None

        self._vr_system = None
        self._vr_chaperone = None
        self._vr_chaperone_setup = None

        self._play_area: Optional[PlayArea] = None
        self._stations: List[StationPose] = []
        self._coverage: Optional[CoverageResult] = None
        self._coverage_key: Optional[tuple] = None

        self._tracker_stats: Dict[str, TrackerLiveStats] = {}

        self._diag_lock = threading.Lock()
        self._diag_running = False
        self._diag_progress: Dict[str, object] = {"stage": "Idle", "t_s": 0.0}
        self._last_metrics: Optional[SessionMetrics] = None
        self._last_session: Optional[dict] = None

        self._thread = threading.Thread(target=self._run, name="StateEngine", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            openvr.shutdown()
        except Exception:
            pass

    def get_state(self) -> Dict[str, object]:
        with self._lock:
            pa = self._play_area
            centroid = pa.centroid if pa else (0.0, 0.0)
            stations = []
            for i, s in enumerate(self._stations[:2]):
                label = "Station A" if i == 0 else "Station B"
                yaw, pitch = station_yaw_pitch_deg(s)
                aim = _aim_yaw_deg((s.position_m[0], s.position_m[1]), centroid)
                stations.append(
                    {
                        "label": label,
                        "serial": s.serial,
                        "pos_m": list(s.position_m),
                        "height_m": s.position_m[2],
                        "yaw_deg": yaw,
                        "pitch_deg": pitch,
                        "aim_yaw_deg": aim,
                        "aim_error_deg": _angle_diff_deg(aim, yaw),
                    }
                )

            cov = self._coverage
            coverage = None
            heatmap = None
            if cov is not None:
                coverage = {
                    "overlap_pct_foot": cov.overlap_pct_foot,
                    "overlap_pct_waist": cov.overlap_pct_waist,
                    "overall_score": cov.overall_score,
                    "sync_warning": cov.station_sync_warning,
                }
                # Compact heatmap payload for overlay rendering.
                # Use -1 for cells outside the play area polygon.
                foot = [(-1 if not m else int(s)) for m, s in zip(cov.inside_mask, cov.score_foot)]
                waist = [(-1 if not m else int(s)) for m, s in zip(cov.inside_mask, cov.score_waist)]
                heatmap = {
                    "origin_m": list(cov.grid_origin_m),
                    "step_m": cov.grid_step_m,
                    "w": cov.grid_w,
                    "h": cov.grid_h,
                    "foot": foot,
                    "waist": waist,
                }

            trackers = []
            for serial, role in self._tracker_roles_by_serial().items():
                st = self._tracker_stats.get(serial, TrackerLiveStats())
                trackers.append(
                    {
                        "role": role,
                        "serial": serial,
                        "connected": st.connected,
                        "tracking_ok": st.tracking_ok,
                        "dropouts": st.dropouts,
                        "jitter_pos_mm": st.jitter_pos_mm,
                        "jitter_yaw_deg": st.jitter_yaw_deg,
                        "pos_m": list(st.last_pos_m) if st.last_pos_m else None,
                        "yaw_deg": st.last_yaw_deg,
                    }
                )

            pa_json = None
            if pa is not None:
                pa_json = {"corners_m": [list(p) for p in pa.corners_m], "source": pa.source, "warning": pa.warning}

            recs = generate_recommendations(
                pa or PlayArea([(-1, -1), (1, -1), (1, 1), (-1, 1)], source="default"),
                self._stations,
                self._coverage,
                self._last_metrics,
                station_labels_by_serial=self._station_labels_by_serial(),
            )
            rec_lines = [f"{r.target} [{r.confidence}]: {r.text}" for r in recs]

            diag = dict(self._diag_progress)
            diag["running"] = bool(self._diag_running)
            diag["last_session_timestamp"] = self._last_session.get("timestamp") if self._last_session else None

            return {
                "connected": bool(self._connected),
                "last_error": self._last_error,
                "play_area": pa_json,
                "stations": stations,
                "coverage": coverage,
                "heatmap": heatmap,
                "trackers": trackers,
                "recommendations": rec_lines,
                "diagnostic": diag,
            }

    def force_recompute(self) -> None:
        with self._lock:
            self._coverage_key = None
            self._coverage = None

    def trigger_diagnostic(self, duration_s: float = 60.0, poll_hz: float = 90.0) -> Dict[str, object]:
        with self._diag_lock:
            if self._diag_running:
                return {"ok": False, "error": "Diagnostic already running"}
            self._diag_running = True
            self._diag_progress = {"stage": "Starting", "t_s": 0.0}
        t = threading.Thread(target=self._run_diagnostic, args=(float(duration_s), float(poll_hz)), daemon=True)
        t.start()
        return {"ok": True}

    def _station_labels_by_serial(self) -> Dict[str, str]:
        st = self._cfg.get("base_stations", {})
        out: Dict[str, str] = {}
        if st.get("station_a"):
            out[st["station_a"]] = "Station A"
        if st.get("station_b"):
            out[st["station_b"]] = "Station B"
        return out

    def _tracker_roles_by_serial(self) -> Dict[str, str]:
        tr = self._cfg.get("trackers", {})
        out: Dict[str, str] = {}
        if tr.get("left_foot"):
            out[tr["left_foot"]] = "Left Foot"
        if tr.get("right_foot"):
            out[tr["right_foot"]] = "Right Foot"
        if tr.get("waist"):
            out[tr["waist"]] = "Waist"
        return out

    def _run(self) -> None:
        target_dt = 1.0 / max(1.0, self._poll_hz)
        next_retry = 0.0
        while not self._stop.is_set():
            start = time.perf_counter()
            try:
                if not self._connected:
                    now = time.perf_counter()
                    if now >= next_retry:
                        ok = self._try_init()
                        if not ok:
                            next_retry = now + 1.0
                    time.sleep(0.1)
                    continue
                self._poll_once()
            except Exception as e:
                with self._lock:
                    self._connected = False
                    self._last_error = f"{type(e).__name__}: {e}"
                try:
                    openvr.shutdown()
                except Exception:
                    pass
            elapsed = time.perf_counter() - start
            time.sleep(max(0.0, target_dt - elapsed))

    def _try_init(self) -> bool:
        try:
            # Server is just a data source; overlay creation runs in a separate process.
            openvr.init(openvr.VRApplication_Background)
            with self._lock:
                self._vr_system = openvr.VRSystem()
                self._vr_chaperone = openvr.VRChaperone()
                try:
                    self._vr_chaperone_setup = openvr.VRChaperoneSetup()
                except Exception:
                    self._vr_chaperone_setup = None
                self._connected = True
                self._last_error = None
            return True
        except Exception as e:
            with self._lock:
                self._connected = False
                self._last_error = f"{type(e).__name__}: {e}"
            try:
                openvr.shutdown()
            except Exception:
                pass
            return False

    def _poll_once(self) -> None:
        vr = self._vr_system
        poses = _safe_call(
            vr,
            "GetDeviceToAbsoluteTrackingPose",
            "getDeviceToAbsoluteTrackingPose",
            openvr.TrackingUniverseStanding,
            0.0,
            openvr.k_unMaxTrackedDeviceCount,
        )
        if isinstance(poses, tuple) and poses and isinstance(poses[0], (list, tuple)):
            poses = poses[0]

        devices: List[Tuple[int, int, str, Optional[Pose]]] = []
        for i in range(int(openvr.k_unMaxTrackedDeviceCount)):
            try:
                connected = bool(_safe_call(vr, "IsTrackedDeviceConnected", "isTrackedDeviceConnected", i))
            except Exception:
                connected = False
            if not connected:
                continue
            try:
                cls = int(_safe_call(vr, "GetTrackedDeviceClass", "getTrackedDeviceClass", i))
            except Exception:
                cls = -1
            try:
                serial = _safe_call(vr, "GetStringTrackedDeviceProperty", "getStringTrackedDeviceProperty", i, openvr.Prop_SerialNumber_String)
                if isinstance(serial, tuple) and serial:
                    serial = serial[0]
                serial = str(serial)
            except Exception:
                serial = ""
            pose = _matrix34_to_pose(poses[i]) if poses and poses[i] is not None else None
            devices.append((i, cls, serial, pose))

        with self._lock:
            self._cfg = load_config()
            self._play_area = get_play_area(self._vr_chaperone, self._vr_chaperone_setup)
            self._stations = self._select_station_poses(devices)
            self._update_tracker_stats(devices)
            self._coverage = self._maybe_recompute_coverage()

    def _select_station_poses(self, devices) -> List[StationPose]:
        want_a = self._cfg.get("base_stations", {}).get("station_a")
        want_b = self._cfg.get("base_stations", {}).get("station_b")
        refs = [(serial, pose) for _, cls, serial, pose in devices if cls == int(openvr.TrackedDeviceClass_TrackingReference) and serial and pose and pose.pose_valid]
        refs_by_serial = {s: p for s, p in refs}
        out: List[StationPose] = []
        for serial in [want_a, want_b]:
            if serial and serial in refs_by_serial:
                p = refs_by_serial[serial]
                out.append(StationPose(serial=serial, position_m=p.position_m, rotation_3x3=p.rotation_3x3))
        if len(out) < 2 and len(refs) >= 2:
            chosen = [refs[0][0], refs[1][0]]
            if not want_a or not want_b:
                self._cfg.setdefault("base_stations", {})
                self._cfg["base_stations"]["station_a"] = chosen[0]
                self._cfg["base_stations"]["station_b"] = chosen[1]
                save_config(self._cfg)
            for s in chosen:
                p = refs_by_serial.get(s)
                if p is not None and all(ss.serial != s for ss in out):
                    out.append(StationPose(serial=s, position_m=p.position_m, rotation_3x3=p.rotation_3x3))
        return out[:2]

    def _update_tracker_stats(self, devices) -> None:
        roles = self._tracker_roles_by_serial()
        if len(roles) != 3:
            trs = [(serial, pose) for _, cls, serial, pose in devices if cls == int(openvr.TrackedDeviceClass_GenericTracker) and serial]
            if len(trs) >= 3:
                self._cfg.setdefault("trackers", {})
                self._cfg["trackers"]["left_foot"] = trs[0][0]
                self._cfg["trackers"]["right_foot"] = trs[1][0]
                self._cfg["trackers"]["waist"] = trs[2][0]
                save_config(self._cfg)
                roles = self._tracker_roles_by_serial()

        by_serial = {serial: pose for _, _, serial, pose in devices if serial}
        now = time.perf_counter()
        for serial, role in roles.items():
            pose = by_serial.get(serial)
            ok = bool(pose is not None and pose.pose_valid and int(pose.tracking_result) == int(openvr.TrackingResult_Running_OK))
            st = self._tracker_stats.setdefault(serial, TrackerLiveStats())
            if st.prev_ok and not ok:
                st.dropouts += 1
            st.prev_ok = ok
            st.connected = bool(pose is not None)
            st.tracking_ok = ok
            if ok and pose is not None:
                st.window.append((now, pose.position_m, float(pose.yaw_deg)))
                t_min = now - 1.0
                while st.window and st.window[0][0] < t_min:
                    st.window.pop(0)
                st.last_pos_m = pose.position_m
                st.last_yaw_deg = float(pose.yaw_deg)
            elif pose is not None:
                st.last_pos_m = pose.position_m
                st.last_yaw_deg = float(pose.yaw_deg)
            st.jitter_pos_mm, st.jitter_yaw_deg = _compute_jitter(st.window)

    def _maybe_recompute_coverage(self) -> Optional[CoverageResult]:
        if not (self._play_area and len(self._stations) == 2):
            self._coverage_key = None
            return None
        corners_key = tuple((round(x, 3), round(y, 3)) for x, y in self._play_area.corners_m)
        stations_key = tuple(
            (
                s.serial,
                round(s.position_m[0], 3),
                round(s.position_m[1], 3),
                round(s.position_m[2], 3),
                tuple(round(v, 3) for row in s.rotation_3x3 for v in row),
            )
            for s in self._stations
        )
        key = (corners_key, stations_key)
        if key == self._coverage_key and self._coverage is not None:
            return self._coverage
        self._coverage_key = key
        return compute_coverage(self._play_area, self._stations)

    def _run_diagnostic(self, duration_s: float, poll_hz: float) -> None:
        try:
            roles = self._tracker_roles_by_serial()
            tracker_serials = list(roles.keys())
            if len(tracker_serials) != 3:
                raise RuntimeError("Trackers not selected.")
            if not (self._play_area and len(self._stations) == 2):
                raise RuntimeError("Stations/play area not ready.")

            start = time.perf_counter()
            dt = 1.0 / max(1.0, poll_hz)
            samples: List[dict] = []
            vr = self._vr_system

            while not self._stop.is_set():
                t = time.perf_counter() - start
                if t >= duration_s:
                    break
                with self._lock:
                    self._diag_progress = {"stage": _diagnostic_stage(t), "t_s": float(t)}

                poses = _safe_call(
                    vr,
                    "GetDeviceToAbsoluteTrackingPose",
                    "getDeviceToAbsoluteTrackingPose",
                    openvr.TrackingUniverseStanding,
                    0.0,
                    openvr.k_unMaxTrackedDeviceCount,
                )
                if isinstance(poses, tuple) and poses and isinstance(poses[0], (list, tuple)):
                    poses = poses[0]

                by_serial: Dict[str, Pose] = {}
                for i in range(int(openvr.k_unMaxTrackedDeviceCount)):
                    try:
                        connected = bool(_safe_call(vr, "IsTrackedDeviceConnected", "isTrackedDeviceConnected", i))
                    except Exception:
                        connected = False
                    if not connected:
                        continue
                    try:
                        serial = _safe_call(
                            vr, "GetStringTrackedDeviceProperty", "getStringTrackedDeviceProperty", i, openvr.Prop_SerialNumber_String
                        )
                        if isinstance(serial, tuple) and serial:
                            serial = serial[0]
                        serial = str(serial)
                    except Exception:
                        continue
                    if poses and poses[i] is not None:
                        by_serial[serial] = _matrix34_to_pose(poses[i])

                # HMD yaw (best-effort)
                hmd_yaw = None
                for i in range(int(openvr.k_unMaxTrackedDeviceCount)):
                    try:
                        cls = int(_safe_call(vr, "GetTrackedDeviceClass", "getTrackedDeviceClass", i))
                    except Exception:
                        continue
                    if cls != int(openvr.TrackedDeviceClass_HMD):
                        continue
                    if poses and poses[i] is not None:
                        p = _matrix34_to_pose(poses[i])
                        if p.pose_valid:
                            hmd_yaw = float(p.yaw_deg)
                            break

                trk: Dict[str, dict] = {}
                for serial in tracker_serials:
                    p = by_serial.get(serial)
                    if p is None:
                        trk[serial] = {"ok": False}
                    else:
                        ok = bool(p.pose_valid and int(p.tracking_result) == int(openvr.TrackingResult_Running_OK))
                        trk[serial] = {"pos": list(p.position_m), "yaw_deg": float(p.yaw_deg), "ok": ok}

                samples.append({"t_s": float(t), "hmd_yaw_deg": hmd_yaw, "trackers": trk})
                time.sleep(dt)

            with self._lock:
                pa = self._play_area
                stations = list(self._stations)
                cov = self._coverage

            session = {
                "timestamp": time.strftime("%Y%m%d_%H%M%S"),
                "duration_s": float(duration_s),
                "tracker_roles_by_serial": roles,
                "stations": [{"serial": s.serial, "pos": list(s.position_m), "rot": [list(r) for r in s.rotation_3x3]} for s in stations],
                "play_area": {"corners_m": [list(p) for p in pa.corners_m], "source": pa.source, "warning": pa.warning} if pa else None,
                "coverage_summary": None
                if cov is None
                else {"overlap_pct_foot": cov.overlap_pct_foot, "overlap_pct_waist": cov.overlap_pct_waist, "overall_score": cov.overall_score},
                "samples": samples,
            }
            metrics = analyze_diagnostic_session(samples, roles, stations)
            save_session(session)
            with self._lock:
                self._last_session = session
                self._last_metrics = metrics
        except Exception as e:
            log.exception("Diagnostic failed")
            with self._lock:
                self._last_error = f"Diagnostic: {type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._diag_running = False
                self._diag_progress = {"stage": "Idle", "t_s": 0.0}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/state"):
            self._write_json(200, self.server.engine.get_state())  # type: ignore[attr-defined]
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path.startswith("/run_diagnostic"):
            self._write_json(200, self.server.engine.trigger_diagnostic())  # type: ignore[attr-defined]
            return
        if self.path.startswith("/recompute"):
            self.server.engine.force_recompute()  # type: ignore[attr-defined]
            self._write_json(200, {"ok": True})
            return
        if self.path.startswith("/shutdown"):
            self._write_json(200, {"ok": True})
            self.server.shutdown_requested.set()  # type: ignore[attr-defined]
            return
        self._write_json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP: " + fmt, *args)

    def _write_json(self, code: int, obj: Dict[str, object]) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class StateHTTPServer(ThreadingHTTPServer):
    def __init__(self, addr, handler, engine: StateEngine) -> None:
        super().__init__(addr, handler)
        self.engine = engine
        self.shutdown_requested = threading.Event()


def serve_state(engine: StateEngine, host: str = "127.0.0.1", port: int = 17835) -> StateHTTPServer:
    server = StateHTTPServer((host, int(port)), _Handler, engine)
    t = threading.Thread(target=server.serve_forever, name="StateHTTPServer", daemon=True)
    t.start()
    return server
