from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import openvr
from PySide6.QtCore import QThread


Vec3 = Tuple[float, float, float]
Mat3 = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


@dataclass(frozen=True)
class Pose:
    position_m: Vec3
    rotation_3x3: Mat3
    pose_valid: bool
    tracking_result: int

    @property
    def yaw_deg(self) -> float:
        forward = forward_from_rotation(self.rotation_3x3)
        return math.degrees(math.atan2(forward[1], forward[0]))


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    device_class: int
    model: str
    serial: str
    connected: bool
    pose: Optional[Pose]


def _safe_call(obj, pascal: str, camel: str, *args, **kwargs):
    if hasattr(obj, camel):
        return getattr(obj, camel)(*args, **kwargs)
    return getattr(obj, pascal)(*args, **kwargs)


def _matrix34_to_pose(tracked_pose) -> Pose:
    m34 = tracked_pose.mDeviceToAbsoluteTracking
    m = getattr(m34, "m", None)
    if m is None:
        m = m34  # fallback: already a nested list/tuple
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


def forward_from_rotation(rot: Mat3) -> Vec3:
    # OpenVR convention: -Z axis is "forward" for tracked devices.
    z_axis = (rot[0][2], rot[1][2], rot[2][2])
    return (-z_axis[0], -z_axis[1], -z_axis[2])


def rot_transpose(rot: Mat3) -> Mat3:
    return (
        (rot[0][0], rot[1][0], rot[2][0]),
        (rot[0][1], rot[1][1], rot[2][1]),
        (rot[0][2], rot[1][2], rot[2][2]),
    )


def mat3_mul_vec3(rot: Mat3, v: Vec3) -> Vec3:
    return (
        rot[0][0] * v[0] + rot[0][1] * v[1] + rot[0][2] * v[2],
        rot[1][0] * v[0] + rot[1][1] * v[1] + rot[1][2] * v[2],
        rot[2][0] * v[0] + rot[2][1] * v[1] + rot[2][2] * v[2],
    )


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_len(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def vec_norm(v: Vec3) -> Vec3:
    l = vec_len(v)
    if l <= 1e-9:
        return (0.0, 0.0, 0.0)
    return (v[0] / l, v[1] / l, v[2] / l)


class SteamVRRuntime(QThread):
    """
    Background thread that maintains a SteamVR/OpenVR connection and polls poses.

    - Attempts to (re)initialize OpenVR until SteamVR is available.
    - Polls poses continuously and keeps an in-memory snapshot for the UI.
    - If SteamVR closes/restarts, it drops back to a "waiting" state and retries.

    UI code should treat `get_snapshot()` as the source of truth.
    """

    def __init__(self, poll_hz: float = 90.0, parent=None) -> None:
        super().__init__(parent)
        self._poll_hz = float(poll_hz)
        self._lock = threading.RLock()
        self._stop = threading.Event()

        self._connected = False
        self._last_error: Optional[str] = None

        self._vr_system = None
        self._vr_chaperone = None
        self._vr_chaperone_setup = None

        self._device_cache: Dict[int, DeviceInfo] = {}
        self._last_pose_time = 0.0

    def stop(self) -> None:
        self._stop.set()

    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._connected)

    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def get_snapshot(self) -> List[DeviceInfo]:
        with self._lock:
            return list(self._device_cache.values())

    def get_vr_handles(self):
        with self._lock:
            return self._vr_system, self._vr_chaperone, self._vr_chaperone_setup

    def run(self) -> None:
        target_dt = 1.0 / max(1.0, self._poll_hz)
        next_retry_time = 0.0

        while not self._stop.is_set():
            start = time.perf_counter()
            try:
                if not self._connected:
                    now = time.perf_counter()
                    if now >= next_retry_time:
                        ok = self._try_init()
                        if not ok:
                            next_retry_time = now + 1.0
                    time.sleep(0.05)
                    continue

                self._poll_once()
            except Exception as e:
                # Any unexpected OpenVR exception means we should drop the connection
                # and try again (SteamVR may have restarted/closed).
                with self._lock:
                    self._connected = False
                    self._last_error = f"{type(e).__name__}: {e}"
                    self._device_cache = {}
                self._safe_shutdown()

            elapsed = time.perf_counter() - start
            time.sleep(max(0.0, target_dt - elapsed))

        self._safe_shutdown()

    def _try_init(self) -> bool:
        try:
            # Background app keeps it unobtrusive and avoids compositor overlays.
            openvr.init(openvr.VRApplication_Background)
            vr_system = openvr.VRSystem()
            vr_chaperone = openvr.VRChaperone()
            try:
                vr_chaperone_setup = openvr.VRChaperoneSetup()
            except Exception:
                vr_chaperone_setup = None
            with self._lock:
                self._vr_system = vr_system
                self._vr_chaperone = vr_chaperone
                self._vr_chaperone_setup = vr_chaperone_setup
                self._connected = True
                self._last_error = None
            return True
        except Exception as e:
            with self._lock:
                self._connected = False
                self._last_error = f"{type(e).__name__}: {e}"
            self._safe_shutdown()
            return False

    def _safe_shutdown(self) -> None:
        try:
            openvr.shutdown()
        except Exception:
            pass
        with self._lock:
            self._vr_system = None
            self._vr_chaperone = None
            self._vr_chaperone_setup = None

    def _get_device_class(self, index: int) -> int:
        return int(_safe_call(self._vr_system, "GetTrackedDeviceClass", "getTrackedDeviceClass", index))

    def _get_string_prop(self, index: int, prop: int) -> str:
        # openvr's python wrapper has historically exposed both GetX and getX.
        try:
            v = _safe_call(self._vr_system, "GetStringTrackedDeviceProperty", "getStringTrackedDeviceProperty", index, prop)
            if isinstance(v, tuple) and v:
                return str(v[0])
            return str(v)
        except Exception:
            return ""

    def _poll_once(self) -> None:
        poses = _safe_call(
            self._vr_system,
            "GetDeviceToAbsoluteTrackingPose",
            "getDeviceToAbsoluteTrackingPose",
            openvr.TrackingUniverseStanding,
            0.0,
            openvr.k_unMaxTrackedDeviceCount,
        )
        if isinstance(poses, tuple) and poses and isinstance(poses[0], (list, tuple)):
            poses = poses[0]
        cache: Dict[int, DeviceInfo] = {}

        for i in range(int(openvr.k_unMaxTrackedDeviceCount)):
            connected = bool(_safe_call(self._vr_system, "IsTrackedDeviceConnected", "isTrackedDeviceConnected", i))
            if not connected:
                continue

            device_class = self._get_device_class(i)
            model = self._get_string_prop(i, openvr.Prop_ModelNumber_String)
            serial = self._get_string_prop(i, openvr.Prop_SerialNumber_String)

            tracked_pose = poses[i]
            pose = _matrix34_to_pose(tracked_pose) if tracked_pose is not None else None

            cache[i] = DeviceInfo(
                index=i,
                device_class=device_class,
                model=model,
                serial=serial,
                connected=connected,
                pose=pose,
            )

        with self._lock:
            self._device_cache = cache
            self._last_pose_time = time.time()


def device_class_name(device_class: int) -> str:
    m = {
        int(openvr.TrackedDeviceClass_Invalid): "Invalid",
        int(openvr.TrackedDeviceClass_HMD): "HMD",
        int(openvr.TrackedDeviceClass_Controller): "Controller",
        int(openvr.TrackedDeviceClass_GenericTracker): "GenericTracker",
        int(openvr.TrackedDeviceClass_TrackingReference): "TrackingReference",
        int(openvr.TrackedDeviceClass_DisplayRedirect): "DisplayRedirect",
    }
    return m.get(int(device_class), str(device_class))


def tracking_result_name(result: int) -> str:
    m = {
        int(openvr.TrackingResult_Uninitialized): "Uninitialized",
        int(openvr.TrackingResult_Calibrating_InProgress): "Calibrating_InProgress",
        int(openvr.TrackingResult_Calibrating_OutOfRange): "Calibrating_OutOfRange",
        int(openvr.TrackingResult_Running_OK): "Running_OK",
        int(openvr.TrackingResult_Running_OutOfRange): "Running_OutOfRange",
    }
    return m.get(int(result), str(result))
