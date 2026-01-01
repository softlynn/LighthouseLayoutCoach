from __future__ import annotations

import argparse
import ctypes
import json
import logging
import math
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import openvr
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen


log = logging.getLogger("llc.overlay")


def _safe_call(obj, pascal: str, camel: str, *args, **kwargs):
    fn = camel if hasattr(obj, camel) else pascal
    try:
        return getattr(obj, fn)(*args, **kwargs)
    except Exception as e:
        # openvr raises specific exception types like openvr.error_code.OverlayError_RequestFailed
        # via its error_code check wrapper; the exception class name is the enum name.
        log.error("OpenVR call failed: %s -> %s: %s", fn, type(e).__name__, e)
        raise


@dataclass(frozen=True)
class Button:
    id: str
    rect: Tuple[int, int, int, int]  # x,y,w,h in pixels
    label: str

    def hit(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self.rect
        return (rx <= x <= rx + rw) and (ry <= y <= ry + rh)


class DashboardOverlayClient:
    def __init__(self, state_url: str) -> None:
        self.state_url = state_url.rstrip("/")
        self.w, self.h = 1024, 768
        self.buttons = [
            Button("recompute", (28, 680, 300, 60), "Recompute"),
            Button("diagnostic", (350, 680, 300, 60), "Run 60s Diagnostic"),
        ]

        self.overlay = None
        self.handle = None
        self.thumb = None
        self._openvr_inited = False

    def start(self) -> None:
        openvr.init(openvr.VRApplication_Overlay)
        self._openvr_inited = True
        self.overlay = openvr.VROverlay()
        self._create_or_recreate_overlay()

        self._configure_overlay()

        if self.thumb is not None:
            thumb_img = QImage(256, 256, QImage.Format.Format_RGBA8888)
            thumb_img.fill(QColor(30, 30, 30))
            p = QPainter(thumb_img)
            p.setPen(QColor(235, 235, 235))
            f = QFont("Segoe UI", 24)
            f.setBold(True)
            p.setFont(f)
            p.drawText(20, 130, "LLC")
            p.end()
            self._set_raw(self.thumb, thumb_img)

    def shutdown(self) -> None:
        try:
            if self.overlay and self.handle is not None:
                _safe_call(self.overlay, "DestroyOverlay", "destroyOverlay", self.handle)
        except Exception:
            pass
        try:
            openvr.shutdown()
            self._openvr_inited = False
        except Exception:
            pass

    def run(self, fps: float = 20.0) -> None:
        dt = 1.0 / max(1.0, fps)
        while True:
            start = time.perf_counter()
            state = self._get_json("/state")
            img = self._render(state)
            self._set_raw(self.handle, img)
            self._pump_events()
            time.sleep(max(0.0, dt - (time.perf_counter() - start)))

    def _create_or_recreate_overlay(self) -> None:
        if self.overlay is None:
            raise RuntimeError("Overlay interface not created")

        if self.handle is not None:
            try:
                _safe_call(self.overlay, "DestroyOverlay", "destroyOverlay", self.handle)
            except Exception:
                pass

        res = _safe_call(
            self.overlay,
            "CreateDashboardOverlay",
            "createDashboardOverlay",
            "lighthouse.layout.coach",
            "Lighthouse Layout Coach",
        )
        if isinstance(res, tuple) and len(res) == 3:
            _, self.handle, self.thumb = res
        elif isinstance(res, tuple) and len(res) == 2:
            self.handle, self.thumb = res
        else:
            self.handle = res
            self.thumb = None

    def _configure_overlay(self) -> None:
        if self.overlay is None or self.handle is None:
            return
        _safe_call(self.overlay, "SetOverlayWidthInMeters", "setOverlayWidthInMeters", self.handle, 1.7)
        _safe_call(
            self.overlay,
            "SetOverlayInputMethod",
            "setOverlayInputMethod",
            self.handle,
            openvr.VROverlayInputMethod_Mouse,
        )
        _safe_call(self.overlay, "ShowDashboard", "showDashboard", "lighthouse.layout.coach")

    def _is_valid_handle(self, handle) -> bool:
        if handle is None:
            return False
        try:
            h = int(handle)
        except Exception:
            return False
        if h == 0:
            return False
        invalid = getattr(openvr, "k_ulOverlayHandleInvalid", None)
        if invalid is not None:
            try:
                if h == int(invalid):
                    return False
            except Exception:
                pass
        return True

    def _get_json(self, path: str) -> Dict:
        try:
            with urllib.request.urlopen(self.state_url + path, timeout=0.35) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return {"connected": False, "last_error": "State server unreachable", "stations": [], "trackers": [], "coverage": None, "recommendations": [], "diagnostic": {"running": False, "stage": "Idle"}}

    def _post(self, path: str) -> None:
        try:
            req = urllib.request.Request(self.state_url + path, method="POST", data=b"{}")
            with urllib.request.urlopen(req, timeout=0.35) as r:
                r.read()
        except Exception:
            pass

    def _pump_events(self) -> None:
        # Best-effort click support.
        try:
            e = openvr.VREvent_t()
            while _safe_call(self.overlay, "PollNextOverlayEvent", "pollNextOverlayEvent", self.handle, e, ctypes.sizeof(e)):
                if int(e.eventType) == int(getattr(openvr, "VREvent_MouseButtonDown", 200)):
                    x = float(e.data.mouse.x) * self.w
                    y = float(e.data.mouse.y) * self.h
                    for b in self.buttons:
                        if b.hit(x, y):
                            if b.id == "diagnostic":
                                self._post("/run_diagnostic")
                            elif b.id == "recompute":
                                self._post("/recompute")
        except Exception:
            return

    def _render(self, state: Dict) -> QImage:
        img = QImage(self.w, self.h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(18, 18, 18))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        title = QFont("Segoe UI", 18)
        title.setBold(True)
        p.setFont(title)
        p.setPen(QColor(235, 235, 235))
        p.drawText(24, 40, "LighthouseLayoutCoach (VR Overlay)")

        ok = bool(state.get("connected"))
        p.setFont(QFont("Segoe UI", 12))
        p.setPen(QColor(120, 220, 160) if ok else QColor(255, 170, 120))
        p.drawText(24, 68, "SteamVR connected" if ok else f"Waiting for SteamVR… {state.get('last_error','')}")

        y = 110
        p.setFont(QFont("Segoe UI", 13, weight=QFont.Weight.DemiBold))
        p.setPen(QColor(220, 220, 220))
        p.drawText(24, y, "Stations")
        y += 22
        p.setFont(QFont("Consolas", 11))
        for st in state.get("stations", [])[:2]:
            p.setPen(QColor(200, 200, 200))
            p.drawText(
                24,
                y,
                f"{st.get('label')}: z {st.get('height_m',0):.2f}m | yaw {st.get('yaw_deg',0):.0f}° | pitch {st.get('pitch_deg',0):.0f}° | aim err {st.get('aim_error_deg',0):+.0f}°",
            )
            y += 18

        # Mini-map: play area + stations + trackers + heatmap thumbnails
        self._draw_minimap(p, state, 620, 90, 380, 310)

        y += 10
        p.setFont(QFont("Segoe UI", 13, weight=QFont.Weight.DemiBold))
        p.setPen(QColor(220, 220, 220))
        p.drawText(24, y, "Coverage (heuristic)")
        y += 22
        p.setFont(QFont("Consolas", 11))
        cov = state.get("coverage")
        if cov:
            p.setPen(QColor(200, 200, 200))
            p.drawText(24, y, f"Foot overlap {cov.get('overlap_pct_foot',0):.1f}% | Waist overlap {cov.get('overlap_pct_waist',0):.1f}% | Score {cov.get('overall_score',0):.1f}/100")
            y += 18
            if cov.get("sync_warning"):
                p.setPen(QColor(255, 210, 122))
                p.drawText(24, y, "Sync warning: " + str(cov.get("sync_warning"))[:110])
                y += 18
        else:
            p.setPen(QColor(200, 200, 200))
            p.drawText(24, y, "(coverage unavailable)")
            y += 18

        heat = state.get("heatmap")
        if heat:
            p.setPen(QColor(220, 220, 220))
            p.setFont(QFont("Segoe UI", 11, weight=QFont.Weight.DemiBold))
            p.drawText(24, y + 18, "Heatmap: Foot / Waist")
            self._draw_heatmap(p, heat, "foot", 24, y + 28, 280, 120)
            self._draw_heatmap(p, heat, "waist", 320, y + 28, 280, 120)
            y += 160

        y += 10
        p.setFont(QFont("Segoe UI", 13, weight=QFont.Weight.DemiBold))
        p.setPen(QColor(220, 220, 220))
        p.drawText(24, y, "Trackers (live)")
        y += 22
        p.setFont(QFont("Consolas", 11))
        for tr in state.get("trackers", []):
            tracking_ok = bool(tr.get("tracking_ok"))
            p.setPen(QColor(120, 220, 160) if tracking_ok else QColor(255, 170, 120))
            p.drawText(
                24,
                y,
                f"{tr.get('role')}: {'OK' if tracking_ok else 'NOT OK'} | dropouts {tr.get('dropouts',0)} | jitter {tr.get('jitter_pos_mm',0):.1f}mm / {tr.get('jitter_yaw_deg',0):.1f}°",
            )
            y += 18

        y += 10
        p.setFont(QFont("Segoe UI", 13, weight=QFont.Weight.DemiBold))
        p.setPen(QColor(220, 220, 220))
        p.drawText(24, y, "Recommendations")
        y += 22
        p.setFont(QFont("Segoe UI", 11))
        for line in state.get("recommendations", [])[:10]:
            p.setPen(QColor(200, 200, 200))
            p.drawText(24, y, str(line)[:120])
            y += 16

        diag = state.get("diagnostic") or {}
        p.setFont(QFont("Segoe UI", 11))
        if diag.get("running"):
            p.setPen(QColor(255, 210, 122))
            p.drawText(24, 660, f"Diagnostic: {diag.get('stage','Running')} ({diag.get('t_s',0):.0f}s)")
        else:
            p.setPen(QColor(200, 200, 200))
            p.drawText(24, 660, f"Diagnostic: {diag.get('stage','Idle')}")

        p.setFont(QFont("Segoe UI", 10, weight=QFont.Weight.DemiBold))
        for b in self.buttons:
            x, by, bw, bh = b.rect
            p.setPen(QPen(QColor(90, 90, 90), 2))
            p.setBrush(QColor(30, 30, 30))
            p.drawRoundedRect(x, by, bw, bh, 8, 8)
            p.setPen(QColor(230, 230, 230))
            p.drawText(x + 14, by + 36, b.label)

        p.end()
        return img

    def _draw_heatmap(self, p: QPainter, heat: Dict, key: str, x0: int, y0: int, w: int, h: int) -> None:
        try:
            gw = int(heat["w"])
            gh = int(heat["h"])
            vals = heat[key]
            cell_w = w / max(1, gw)
            cell_h = h / max(1, gh)
            for yi in range(gh):
                for xi in range(gw):
                    v = int(vals[yi * gw + xi])
                    if v < 0:
                        continue
                    if v == 0:
                        c = QColor(200, 60, 60, 110)
                    elif v == 1:
                        c = QColor(210, 170, 60, 110)
                    else:
                        c = QColor(60, 200, 110, 120)
                    p.fillRect(int(x0 + xi * cell_w), int(y0 + yi * cell_h), int(cell_w + 1), int(cell_h + 1), c)
            p.setPen(QPen(QColor(90, 90, 90), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x0, y0, w, h)
        except Exception:
            return

    def _draw_minimap(self, p: QPainter, state: Dict, x0: int, y0: int, w: int, h: int) -> None:
        # Draw play area polygon, station arrows, and tracker points (top-down).
        pa = (state.get("play_area") or {})
        corners = pa.get("corners_m") or None
        if not corners:
            p.setPen(QColor(120, 120, 120))
            p.drawText(x0, y0 + 18, "Play area unavailable")
            p.setPen(QPen(QColor(90, 90, 90), 2))
            p.drawRect(x0, y0, w, h)
            return

        pts = [(float(c[0]), float(c[1])) for c in corners]
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        pad = 0.15
        min_x -= pad
        max_x += pad
        min_y -= pad
        max_y += pad
        sx = w / max(1e-6, (max_x - min_x))
        sy = h / max(1e-6, (max_y - min_y))
        s = min(sx, sy)

        def to_px(xm: float, ym: float) -> Tuple[float, float]:
            px = x0 + (xm - min_x) * s
            py = y0 + h - (ym - min_y) * s
            return px, py

        # Background + border
        p.fillRect(x0, y0, w, h, QColor(22, 22, 22))
        p.setPen(QPen(QColor(90, 90, 90), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(x0, y0, w, h)

        # Play area outline
        p.setPen(QPen(QColor(200, 200, 200), 2))
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            ax, ay = to_px(a[0], a[1])
            bx, by = to_px(b[0], b[1])
            p.drawLine(int(ax), int(ay), int(bx), int(by))

        # Stations
        for st in state.get("stations", [])[:2]:
            pos = st.get("pos_m") or [0, 0, 0]
            yaw = float(st.get("yaw_deg", 0.0))
            px, py = to_px(float(pos[0]), float(pos[1]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(120, 180, 255))
            p.drawEllipse(int(px - 5), int(py - 5), 10, 10)
            # arrow
            dx = math.cos(math.radians(yaw))
            dy = math.sin(math.radians(yaw))
            ex, ey = to_px(float(pos[0]) + dx * 0.5, float(pos[1]) + dy * 0.5)
            p.setPen(QPen(QColor(120, 180, 255), 2))
            p.drawLine(int(px), int(py), int(ex), int(ey))

        # Trackers
        for tr in state.get("trackers", []):
            pos = tr.get("pos_m")
            if not pos:
                continue
            px, py = to_px(float(pos[0]), float(pos[1]))
            ok = bool(tr.get("tracking_ok"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(120, 255, 170) if ok else QColor(255, 170, 120))
            p.drawEllipse(int(px - 4), int(py - 4), 8, 8)

    def _set_raw(self, handle, img: QImage) -> None:
        if img.format() != QImage.Format.Format_RGBA8888:
            img = img.convertToFormat(QImage.Format.Format_RGBA8888)

        w = int(img.width())
        h = int(img.height())
        depth = 4
        expected_len = w * h * depth

        data = img.bits().tobytes()
        if not isinstance(data, (bytes, bytearray)):
            log.error("SetOverlayRaw skipped: buffer type is %s (expected bytes/bytearray)", type(data).__name__)
            return

        if len(data) != expected_len:
            # QImage can include scanline padding; strip to w*depth per row when needed.
            bpl = int(img.bytesPerLine())
            row_len = w * depth
            if bpl >= row_len and h > 0:
                data = b"".join(data[y * bpl : y * bpl + row_len] for y in range(h))

        if len(data) != expected_len:
            log.error(
                "SetOverlayRaw skipped: buffer length mismatch (got=%d expected=%d w=%d h=%d depth=%d)",
                len(data),
                expected_len,
                w,
                h,
                depth,
            )
            return

        if not self._openvr_inited:
            log.error("SetOverlayRaw skipped: OpenVR not initialized")
            return
        if self.overlay is None:
            log.error("SetOverlayRaw skipped: overlay interface is None")
            return
        if not self._is_valid_handle(handle):
            log.warning("SetOverlayRaw: invalid overlay handle (%r); recreating overlay…", handle)
            try:
                self._create_or_recreate_overlay()
                self._configure_overlay()
                handle = self.handle
            except Exception as e:
                log.error("SetOverlayRaw skipped: failed to recreate overlay: %s: %s", type(e).__name__, e)
                return
            if not self._is_valid_handle(handle):
                log.error("SetOverlayRaw skipped: invalid overlay handle after recreate (%r)", handle)
                return

        log.debug("SetOverlayRaw: handle=%s w=%d h=%d depth=%d len=%d", handle, w, h, depth, len(data))
        buf = ctypes.create_string_buffer(data, len(data))

        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                _safe_call(self.overlay, "SetOverlayRaw", "setOverlayRaw", handle, buf, w, h, depth)
                return
            except openvr.error_code.OverlayError_RequestFailed as e:
                last_exc = e
                log.warning("SetOverlayRaw RequestFailed (attempt %d/3); retrying…", attempt)
                time.sleep(0.05 * attempt)
            except Exception as e:
                last_exc = e
                log.error("SetOverlayRaw failed: %s: %s", type(e).__name__, e)
                return

        log.warning(
            "SetOverlayRaw still failing after retries (w=%d h=%d depth=%d len=%d); recreating overlay handle and retrying once…",
            w,
            h,
            depth,
            len(data),
        )
        try:
            self._create_or_recreate_overlay()
            if self._is_valid_handle(self.handle):
                self._configure_overlay()
                _safe_call(self.overlay, "SetOverlayRaw", "setOverlayRaw", self.handle, buf, w, h, depth)
                return
        except Exception as e:
            last_exc = e

        log.error(
            "SetOverlayRaw disabled (continuing without crashing) (w=%d h=%d depth=%d len=%d): %s: %s",
            w,
            h,
            depth,
            len(data),
            type(last_exc).__name__,
            last_exc,
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:17835", help="State server base URL")
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--overlay-test", action="store_true", help="Initialize OpenVR and submit one 256x256 test image")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

    app = QGuiApplication([])
    client = DashboardOverlayClient(args.url)
    try:
        client.start()
    except openvr.error_code.InitError_Init_HmdNotFound:
        if args.overlay_test:
            log.info(
                "OpenVR init failed: InitError_Init_HmdNotFound. This is expected when no HMD/SteamVR runtime is active; "
                "overlay handle validation and SetOverlayRaw submission cannot be performed in this environment."
            )
        raise
    try:
        if args.overlay_test:
            test = QImage(256, 256, QImage.Format.Format_RGBA8888)
            test.fill(QColor(30, 30, 30, 255))
            p = QPainter(test)
            p.setPen(QColor(235, 235, 235, 255))
            f = QFont("Segoe UI", 26)
            f.setBold(True)
            p.setFont(f)
            p.drawText(24, 140, "Overlay Test")
            p.end()
            client._set_raw(client.handle, test)
            return 0

        client.run(args.fps)
    finally:
        client.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
