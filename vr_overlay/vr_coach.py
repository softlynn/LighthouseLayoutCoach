from __future__ import annotations

import ctypes
import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import openvr
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

log = logging.getLogger("llc.vr_coach")

Point2 = Tuple[float, float]


def _safe_call(obj, pascal: str, camel: str, *args, **kwargs):
    fn = camel if hasattr(obj, camel) else pascal
    return getattr(obj, fn)(*args, **kwargs)


def _mat34_translate(x: float, y: float, z: float):
    # Identity rotation + translation in OpenVR HmdMatrix34_t form.
    m = openvr.HmdMatrix34_t()
    m.m[0][0] = 1.0
    m.m[0][1] = 0.0
    m.m[0][2] = 0.0
    m.m[0][3] = float(x)
    m.m[1][0] = 0.0
    m.m[1][1] = 1.0
    m.m[1][2] = 0.0
    m.m[1][3] = float(y)
    m.m[2][0] = 0.0
    m.m[2][1] = 0.0
    m.m[2][2] = 1.0
    m.m[2][3] = float(z)
    return m


@dataclass
class VRCoachToggles:
    heatmap: bool = True
    body_suggestions: bool = True
    use_history: bool = False


class VRCoachOverlay:
    """
    A lightweight world overlay ("scene experience") separate from the SteamVR dashboard panel.

    Implementation note: OpenVR overlays are textured quads; we render a simple 2D/3D-ish visualization into a texture
    and place it in the standing universe. This keeps the implementation incremental and avoids engine rewrites.
    """

    def __init__(self, overlay, state_url: str, toggles: VRCoachToggles) -> None:
        self.overlay = overlay
        self.state_url = state_url.rstrip("/")
        self.toggles = toggles

        self.handle = None
        self._visible = False

        self.w, self.h = 1024, 768
        self._last_submit = 0.0

    def start(self) -> None:
        if self.overlay is None:
            raise RuntimeError("OpenVR overlay interface is None")
        if self.handle is not None:
            return
        res = _safe_call(
            self.overlay,
            "CreateOverlay",
            "createOverlay",
            "lighthouse.layout.coach.vrcoach",
            "Lighthouse Layout Coach (VR Coach)",
        )
        # wrappers vary in return shape
        self.handle = res[0] if isinstance(res, tuple) and res else res

        _safe_call(self.overlay, "SetOverlayWidthInMeters", "setOverlayWidthInMeters", self.handle, 1.8)
        _safe_call(
            self.overlay,
            "SetOverlayInputMethod",
            "setOverlayInputMethod",
            self.handle,
            openvr.VROverlayInputMethod_Mouse,
        )

        # Place a world-locked panel in front of the origin; user can reposition via SteamVR overlay tools if needed.
        # Note: forward is -Z in OpenVR standing universe.
        _safe_call(
            self.overlay,
            "SetOverlayTransformAbsolute",
            "setOverlayTransformAbsolute",
            self.handle,
            openvr.TrackingUniverseStanding,
            _mat34_translate(0.0, 1.2, -1.6),
        )
        _safe_call(self.overlay, "ShowOverlay", "showOverlay", self.handle)
        self._visible = True
        log.info("VR Coach overlay started")

    def stop(self) -> None:
        if self.overlay is None:
            return
        if self.handle is None:
            return
        try:
            _safe_call(self.overlay, "HideOverlay", "hideOverlay", self.handle)
        except Exception:
            pass
        try:
            _safe_call(self.overlay, "DestroyOverlay", "destroyOverlay", self.handle)
        except Exception:
            pass
        self.handle = None
        self._visible = False
        log.info("VR Coach overlay stopped")

    def is_running(self) -> bool:
        return self.handle is not None and self._visible

    def submit_frame(self, state: Dict, history_heatmap: Optional[Dict] = None, fps: float = 12.0) -> None:
        if self.overlay is None or self.handle is None:
            return
        now = time.perf_counter()
        if fps > 0 and (now - self._last_submit) < (1.0 / fps):
            return
        self._last_submit = now

        img = self._render(state, history_heatmap=history_heatmap)
        if img.format() != QImage.Format.Format_RGBA8888:
            img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        data = img.bits().tobytes()
        buf = ctypes.create_string_buffer(data, len(data))
        _safe_call(self.overlay, "SetOverlayRaw", "setOverlayRaw", self.handle, buf, img.width(), img.height(), 4)

    def _render(self, state: Dict, history_heatmap: Optional[Dict]) -> QImage:
        img = QImage(self.w, self.h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(10, 10, 10))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        title = QFont("Segoe UI", 16)
        title.setBold(True)
        p.setFont(title)
        p.setPen(QColor(235, 235, 235))
        p.drawText(24, 40, "VR Coach")

        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QColor(170, 170, 170))
        p.drawText(24, 66, "World overlay • Esc/Close via dashboard")

        # Viewport for playspace visualization.
        x0, y0, w, h = 24, 90, 976, 640
        p.fillRect(x0, y0, w, h, QColor(18, 18, 18))
        p.setPen(QPen(QColor(90, 90, 90), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(x0, y0, w, h)

        pa = (state.get("play_area") or {})
        corners = pa.get("corners_m") or None
        if not corners:
            p.setPen(QColor(200, 200, 200))
            p.drawText(x0 + 18, y0 + 28, "Play area unavailable")
            p.end()
            return img

        pts = [(float(c[0]), float(c[1])) for c in corners]
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        centroid = (sum(xs) / max(1, len(xs)), sum(ys) / max(1, len(ys)))
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        pad = 0.25
        min_x -= pad
        max_x += pad
        min_y -= pad
        max_y += pad
        sx = w / max(1e-6, (max_x - min_x))
        sy = h / max(1e-6, (max_y - min_y))
        s = min(sx, sy)

        def to_px(xm: float, ym: float) -> Point2:
            px = x0 + (xm - min_x) * s
            py = y0 + h - (ym - min_y) * s
            return px, py

        # Heatmap overlay (historical preferred; fallback to live heuristic).
        if self.toggles.heatmap:
            hm = history_heatmap if (self.toggles.use_history and history_heatmap) else (state.get("heatmap") or None)
            if hm is not None:
                try:
                    gw = int(hm["w"])
                    gh = int(hm["h"])
                    step = float(hm["step_m"])
                    origin = hm["origin_m"]
                    vals = hm["score"] if "score" in hm else hm.get("waist")  # prefer waist slice for coach view
                    if vals is None:
                        vals = hm.get("foot")
                    if vals is not None:
                        for yi in range(gh):
                            for xi in range(gw):
                                v = int(vals[yi * gw + xi])
                                if v < 0:
                                    continue
                                # Normalize to 0..100 for color mapping.
                                vv = v if "score" in hm else (0 if v <= 0 else (50 if v == 1 else 100))
                                r = int(max(0, min(255, 255 - (vv * 2))))
                                g = int(max(0, min(255, vv * 2)))
                                c = QColor(r, g, 80, 90)
                                cx = float(origin[0]) + (xi + 0.5) * step
                                cy = float(origin[1]) + (yi + 0.5) * step
                                px, py = to_px(cx, cy)
                                cell_w = step * s
                                cell_h = step * s
                                p.fillRect(int(px - cell_w / 2), int(py - cell_h / 2), int(cell_w + 1), int(cell_h + 1), c)
                except Exception:
                    pass

        # Play area outline
        p.setPen(QPen(QColor(210, 210, 210), 2))
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            ax, ay = to_px(a[0], a[1])
            bx, by = to_px(b[0], b[1])
            p.drawLine(int(ax), int(ay), int(bx), int(by))

        # Base stations: frustum-like wedge
        for st in (state.get("stations") or [])[:2]:
            pos = st.get("pos_m") or [0, 0, 0]
            yaw = float(st.get("yaw_deg", 0.0))
            px, py = to_px(float(pos[0]), float(pos[1]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(120, 180, 255))
            p.drawEllipse(int(px - 6), int(py - 6), 12, 12)
            p.setPen(QPen(QColor(120, 180, 255), 2))
            dx = math.cos(math.radians(yaw))
            dy = math.sin(math.radians(yaw))
            ex, ey = to_px(float(pos[0]) + dx * 0.7, float(pos[1]) + dy * 0.7)
            p.drawLine(int(px), int(py), int(ex), int(ey))

        # Trackers: points
        tracker_by_role: Dict[str, Dict] = {}
        for tr in (state.get("trackers") or []):
            pos = tr.get("pos_m")
            if not pos:
                continue
            px, py = to_px(float(pos[0]), float(pos[1]))
            ok = bool(tr.get("tracking_ok"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(90, 230, 140) if ok else QColor(255, 140, 90))
            p.drawEllipse(int(px - 5), int(py - 5), 10, 10)
            role = str(tr.get("role") or "")
            if role:
                tracker_by_role[role] = tr

        # Body placement suggestions (very simple anchors in playspace coordinates).
        if self.toggles.body_suggestions:
            anchors: Dict[str, Point2] = {
                "Waist": (centroid[0], centroid[1]),
                "Left Foot": (centroid[0] - 0.18, centroid[1] - 0.10),
                "Right Foot": (centroid[0] + 0.18, centroid[1] - 0.10),
                "Chest": (centroid[0], centroid[1] + 0.12),
            }
            p.setFont(QFont("Segoe UI", 10))
            for name, (ax, ay) in anchors.items():
                px, py = to_px(ax, ay)
                p.setPen(QPen(QColor(200, 200, 255, 180), 2))
                p.setBrush(QColor(60, 60, 90, 120))
                p.drawEllipse(int(px - 6), int(py - 6), 12, 12)
                p.setPen(QColor(200, 200, 255, 200))
                p.drawText(int(px + 8), int(py + 4), name)

                tr = tracker_by_role.get(name)
                if tr and tr.get("pos_m"):
                    tx, ty = float(tr["pos_m"][0]), float(tr["pos_m"][1])
                    tpx, tpy = to_px(tx, ty)
                    p.setPen(QPen(QColor(255, 220, 120, 200), 2))
                    p.drawLine(int(tpx), int(tpy), int(px), int(py))

        p.end()
        return img
