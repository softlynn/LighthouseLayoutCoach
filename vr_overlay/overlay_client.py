from __future__ import annotations

import argparse
import ctypes
import json
import logging
import math
import os
import random
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import openvr
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen

from lighthouse_layout_coach.chaperone import PlayArea
from lighthouse_layout_coach.log_data import LogDataProvider
from lighthouse_layout_coach.logging_setup import setup_logging
from vr_overlay.vr_coach import VRCoachOverlay, VRCoachToggles


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
        self.toggles = VRCoachToggles()
        self._coach: Optional[VRCoachOverlay] = None
        self._logs = LogDataProvider()
        self._history_heatmap: Optional[Dict] = None
        self._history_heatmap_key: Optional[tuple] = None

        self.buttons = [
            Button("coach", (28, 680, 240, 60), "Launch VR Coach"),
            Button("history", (284, 680, 240, 60), "History: OFF"),
            Button("heatmap", (540, 680, 220, 60), "Heatmap: ON"),
            Button("body", (776, 680, 220, 60), "Body: ON"),
            Button("diagnostic", (28, 608, 300, 56), "Run 60s Diagnostic"),
            Button("recompute", (350, 608, 300, 56), "Recompute"),
        ]

        self.overlay = None
        self.handle = None
        self.thumb = None
        self._openvr_inited = False

        # Stability + diagnostics (rate-limited logging; no per-frame spam)
        self.overlay_created_count = 0
        self.show_dashboard_count = 0
        self.submission_attempts = 0
        self.submission_failures = 0
        self.recreate_count = 0
        self.last_error: Optional[str] = None

        self._next_submit_time = 0.0
        self._last_diag_time = 0.0
        self._last_error_log_time = 0.0
        self._last_recreate_time = 0.0
        self._recreate_cooldown_s = 5.0
        self._last_submit_ok_time: Optional[float] = None

        self._cached_state: Dict = {}
        self._next_state_fetch_time = 0.0

        self._dashboard_key = "lighthouse.layout.coach"
        self._dashboard_name = "Lighthouse Layout Coach"

        self._poll_event_needs_size: Optional[bool] = None
        self._event_poll_broken = False
        self._events_polled_since = 0
        self._events_last_rate_time = time.monotonic()
        self._logged_first_event = False
        self._logged_first_mouse_move = False
        self._mouse_px: Optional[Tuple[float, float]] = None
        self._hover_button_id: Optional[str] = None
        self._click_toggle = False
        self._click_count = 0
        self._logged_first_event_by_handle: dict[int, bool] = {}

    def start(self) -> None:
        # SteamVR can take a moment to be ready; retry init briefly instead of crashing.
        init_last: Optional[Exception] = None
        for attempt in range(1, 11):
            try:
                openvr.init(openvr.VRApplication_Overlay)
                init_last = None
                break
            except Exception as e:
                init_last = e
                # Backoff and retry for common SteamVR-not-ready states.
                time.sleep(0.35)
        if init_last is not None:
            raise init_last

        self._openvr_inited = True
        self.overlay = openvr.VROverlay()
        try:
            self._create_or_recreate_overlay()
        except openvr.error_code.OverlayError_KeyInUse as e:
            # Do not crash: leave dashboard handle unset and let the run loop retry on cooldown.
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("Dashboard overlay key is in use; will retry creation on cooldown. (%s)", self.last_error)

        self._configure_overlay()
        self._show_dashboard()

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
            if self._coach is not None:
                self._coach.stop()
        except Exception:
            pass
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

            # Avoid heavy per-frame logic: fetch state at a lower cadence and reuse between frames.
            now_m = time.monotonic()
            if now_m >= self._next_state_fetch_time:
                self._cached_state = self._get_json("/state")
                self._next_state_fetch_time = now_m + 0.2  # 5 Hz
            state = self._cached_state

            history_heatmap = self._maybe_update_history_heatmap(state)
            if self._coach is not None and self._coach.is_running():
                try:
                    self._coach.submit_frame(state, history_heatmap=history_heatmap, fps=12.0)
                except Exception as e:
                    log.warning("VR Coach submit failed: %s: %s", type(e).__name__, e)

            img = self._render(state)
            self._set_raw(self.handle, img)
            self._pump_events()
            self._log_diagnostics_rate_limited()
            time.sleep(max(0.0, dt - (time.perf_counter() - start)))

    def _maybe_update_history_heatmap(self, state: Dict) -> Optional[Dict]:
        if not self.toggles.use_history:
            self._history_heatmap = None
            self._history_heatmap_key = None
            return None

        pa = state.get("play_area") or {}
        corners = pa.get("corners_m")
        if not (isinstance(corners, list) and len(corners) >= 4):
            return None

        key = ("history", tuple((float(c[0]), float(c[1])) for c in corners), 0.25)
        if key == self._history_heatmap_key and self._history_heatmap is not None:
            return self._history_heatmap

        play_area = PlayArea(
            corners_m=[(float(c[0]), float(c[1])) for c in corners],
            source=str(pa.get("source") or "unknown"),
            warning=str(pa.get("warning") or "") or None,
        )
        hm = self._logs.compute_heatmap(play_area, step_m=0.25)
        if hm is None:
            self._history_heatmap = None
            self._history_heatmap_key = key
            return None

        self._history_heatmap = {"origin_m": list(hm.origin_m), "step_m": hm.step_m, "w": hm.w, "h": hm.h, "score": hm.score}
        self._history_heatmap_key = key
        return self._history_heatmap

    def _create_or_recreate_overlay(self) -> None:
        if self.overlay is None:
            raise RuntimeError("Overlay interface not created")

        if self.handle is not None:
            try:
                _safe_call(self.overlay, "DestroyOverlay", "destroyOverlay", self.handle)
            except Exception:
                pass

        try:
            res = _safe_call(
                self.overlay,
                "CreateDashboardOverlay",
                "createDashboardOverlay",
                self._dashboard_key,
                self._dashboard_name,
            )
        except openvr.error_code.OverlayError_KeyInUse as e:
            # Most often indicates a stale overlay from a previous crash/run.
            self.last_error = f"{type(e).__name__}: {e}"
            log.warning("CreateDashboardOverlay failed: key in use; attempting cleanup/reuse. (%s)", self.last_error)

            # 1) Try to locate and destroy existing overlays with the same key.
            existing = self._find_overlay_handle(self._dashboard_key)
            if existing is not None:
                self._destroy_overlay_best_effort(existing)

            # 2) Dashboard thumbnail key is runtime-specific; try common variants.
            thumb_candidates = [
                self._dashboard_key + ".thumb",
                self._dashboard_key + "_thumb",
                self._dashboard_key + ".thumbnail",
                self._dashboard_key + "_thumbnail",
            ]
            for k in thumb_candidates:
                h = self._find_overlay_handle(k)
                if h is not None:
                    self._destroy_overlay_best_effort(h)

            time.sleep(0.2)
            # 3) Retry creation once after cleanup.
            try:
                res = _safe_call(
                    self.overlay,
                    "CreateDashboardOverlay",
                    "createDashboardOverlay",
                    self._dashboard_key,
                    self._dashboard_name,
                )
            except openvr.error_code.OverlayError_KeyInUse:
                # 4) Last resort: reuse the existing overlay handle (if present).
                self.handle = existing
                self.thumb = None
                if self._is_valid_handle(self.handle):
                    log.info("Reusing existing dashboard overlay handle due to key-in-use.")
                    return
                raise

        self.overlay_created_count += 1
        if isinstance(res, tuple) and len(res) == 3:
            _, self.handle, self.thumb = res
        elif isinstance(res, tuple) and len(res) == 2:
            self.handle, self.thumb = res
        else:
            self.handle = res
            self.thumb = None

    def _find_overlay_handle(self, key: str):
        if self.overlay is None:
            return None
        fn = "findOverlay" if hasattr(self.overlay, "findOverlay") else "FindOverlay"
        try:
            res = getattr(self.overlay, fn)(key)
        except getattr(openvr.error_code, "OverlayError_UnknownOverlay", Exception):
            return None
        except Exception as e:
            log.debug("OpenVR call failed: %s -> %s: %s", fn, type(e).__name__, e)
            return None

        handle = None
        if isinstance(res, tuple) and res:
            handle = res[0]
        else:
            handle = res
        return handle if self._is_valid_handle(handle) else None

    def _destroy_overlay_best_effort(self, handle) -> None:
        if self.overlay is None:
            return
        try:
            _safe_call(self.overlay, "DestroyOverlay", "destroyOverlay", handle)
        except Exception:
            return

    def _configure_overlay(self) -> None:
        if self.overlay is None:
            return

        def _configure_handle(h) -> None:
            if not self._is_valid_handle(h):
                return
            _safe_call(self.overlay, "SetOverlayWidthInMeters", "setOverlayWidthInMeters", h, 1.7)
            _safe_call(
                self.overlay,
                "SetOverlayInputMethod",
                "setOverlayInputMethod",
                h,
                openvr.VROverlayInputMethod_Mouse,
            )
            # Best-effort: ensure mouse coordinates map 1:1 to pixels for click support.
            try:
                scale = openvr.HmdVector2_t()
                scale.v[0] = float(self.w)
                scale.v[1] = float(self.h)
                _safe_call(self.overlay, "SetOverlayMouseScale", "setOverlayMouseScale", h, scale)
            except Exception:
                pass
            # Ensure the overlay is marked interactive for pointer/controller ray input.
            try:
                flags_to_enable = [
                    "VROverlayFlags_MakeOverlaysInteractiveIfVisible",
                    "VROverlayFlags_VisibleInDashboard",
                    "VROverlayFlags_SendVRTouchpadEvents",
                    "VROverlayFlags_SendVRSmoothScrollEvents",
                    "VROverlayFlags_EnableClickStabilization",
                ]
                for name in flags_to_enable:
                    flag = getattr(openvr, name, None)
                    if flag is None:
                        continue
                    _safe_call(self.overlay, "SetOverlayFlag", "setOverlayFlag", h, flag, True)
            except Exception:
                pass

        # Dashboard overlays have both a main handle and a thumbnail handle; configure both.
        _configure_handle(self.handle)
        _configure_handle(self.thumb)

    def _show_dashboard(self) -> None:
        if self.overlay is None:
            return
        # Never call ShowDashboard from a frame loop. Treat start() as the user's request.
        _safe_call(self.overlay, "ShowDashboard", "showDashboard", "lighthouse.layout.coach")
        self.show_dashboard_count += 1

    def _log_diagnostics_rate_limited(self) -> None:
        now = time.monotonic()
        if now - self._last_diag_time < 1.0:
            return
        self._last_diag_time = now
        log.info(
            "overlay_diag created=%d show=%d submit_attempts=%d failures=%d recreates=%d last_error=%s",
            self.overlay_created_count,
            self.show_dashboard_count,
            self.submission_attempts,
            self.submission_failures,
            self.recreate_count,
            self.last_error,
        )

    def _recreate_if_allowed(self, reason: str) -> bool:
        now = time.monotonic()
        if now - self._last_recreate_time < self._recreate_cooldown_s:
            return False
        self._last_recreate_time = now
        self.recreate_count += 1
        log.warning("Recreating dashboard overlay (cooldown %.1fs) due to: %s", self._recreate_cooldown_s, reason)
        try:
            self._create_or_recreate_overlay()
            self._configure_overlay()
            return True
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False

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
        if self._event_poll_broken:
            return
        if self.overlay is None:
            return

        fn = "pollNextOverlayEvent" if hasattr(self.overlay, "pollNextOverlayEvent") else "PollNextOverlayEvent"
        if not hasattr(self.overlay, fn):
            return
        poll = getattr(self.overlay, fn)

        e = openvr.VREvent_t()

        def _maybe_name_event(event_type: int) -> str:
            # Best-effort mapping without importing extra tables.
            for k, v in openvr.__dict__.items():
                if k.startswith("VREvent_") and isinstance(v, int) and int(v) == int(event_type):
                    return k
            return str(int(event_type))

        def _pump_for_handle(h) -> None:
            if not self._is_valid_handle(h):
                return
            try:
                handle_int = int(h)
            except Exception:
                return
            while True:
                try:
                    ok = poll(h, e)
                except TypeError as ex:
                    log.error(
                        "Overlay event polling disabled: %s signature mismatch (%s: %s)",
                        fn,
                        type(ex).__name__,
                        ex,
                    )
                    self._event_poll_broken = True
                    return
                except Exception as ex:
                    log.error("OpenVR call failed: %s -> %s: %s", fn, type(ex).__name__, ex)
                    return

                if not ok:
                    break

                self._events_polled_since += 1
                now = time.monotonic()
                if now - self._events_last_rate_time >= 1.0:
                    log.info("overlay_events_polled_per_sec=%d", self._events_polled_since)
                    self._events_polled_since = 0
                    self._events_last_rate_time = now

                if not self._logged_first_event_by_handle.get(handle_int):
                    et = int(e.eventType)
                    name = _maybe_name_event(et)
                    try:
                        nx = float(e.data.mouse.x)
                        ny = float(e.data.mouse.y)
                        px = nx * float(self.w)
                        py = ny * float(self.h)
                        log.info(
                            "overlay_first_event handle=%s type=%s mouse_norm=(%.3f,%.3f) mouse_px=(%.1f,%.1f)",
                            handle_int,
                            name,
                            nx,
                            ny,
                            px,
                            py,
                        )
                    except Exception:
                        log.info("overlay_first_event handle=%s type=%s", handle_int, name)
                    self._logged_first_event_by_handle[handle_int] = True
                    self._logged_first_event = True

                if int(e.eventType) == int(getattr(openvr, "VREvent_MouseMove", 300)):
                    try:
                        nx = float(e.data.mouse.x)
                        ny = float(e.data.mouse.y)
                        px = nx * float(self.w)
                        py = ny * float(self.h)
                        self._mouse_px = (px, py)
                        if not self._logged_first_mouse_move:
                            log.info("overlay_first_mouse_move mouse_px=(%.1f,%.1f)", px, py)
                            self._logged_first_mouse_move = True
                        hover = None
                        for b in self.buttons:
                            if b.hit(px, py):
                                hover = b.id
                                break
                        self._hover_button_id = hover
                    except Exception:
                        pass

                if int(e.eventType) == int(getattr(openvr, "VREvent_MouseButtonDown", 200)):
                    self._click_toggle = not self._click_toggle
                    self._click_count += 1
                    x = float(e.data.mouse.x) * self.w
                    y = float(e.data.mouse.y) * self.h
                    for b in self.buttons:
                        if b.hit(x, y):
                            if b.id == "coach":
                                if self._coach is None or not self._coach.is_running():
                                    try:
                                        self._coach = VRCoachOverlay(self.overlay, self.state_url, self.toggles)
                                        self._coach.start()
                                    except Exception as ex:
                                        log.error("Failed to start VR Coach: %s: %s", type(ex).__name__, ex)
                                else:
                                    try:
                                        self._coach.stop()
                                    finally:
                                        self._coach = None
                            elif b.id == "history":
                                self.toggles.use_history = not self.toggles.use_history
                            elif b.id == "heatmap":
                                self.toggles.heatmap = not self.toggles.heatmap
                            elif b.id == "body":
                                self.toggles.body_suggestions = not self.toggles.body_suggestions
                            elif b.id == "diagnostic":
                                self._post("/run_diagnostic")
                            elif b.id == "recompute":
                                self._post("/recompute")

        try:
            # Some SteamVR configurations may deliver dashboard events to the thumbnail handle;
            # poll both to avoid "non-interactable" issues.
            _pump_for_handle(self.handle)
            _pump_for_handle(self.thumb)
        except Exception:
            return

    def _render(self, state: Dict) -> QImage:
        img = QImage(self.w, self.h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(26, 40, 60) if self._click_toggle else QColor(18, 18, 18))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        title = QFont("Segoe UI", 18)
        title.setBold(True)
        p.setFont(title)
        p.setPen(QColor(235, 235, 235))
        p.drawText(24, 40, "LighthouseLayoutCoach (Dashboard Panel)")
        p.setFont(QFont("Segoe UI", 12))
        p.setPen(QColor(190, 190, 190))
        p.drawText(24, 62, f"Input proof: clicks={self._click_count}")

        connected = bool(state.get("connected"))
        p.setFont(QFont("Segoe UI", 12))
        p.setPen(QColor(120, 220, 160) if connected else QColor(255, 170, 120))
        p.drawText(24, 68, "SteamVR connected" if connected else f"Waiting for SteamVR… {state.get('last_error','')}")

        stations = state.get("stations") or []
        trackers = state.get("trackers") or []
        station_n = len(stations)
        tracker_n = len(trackers)
        ok_n = sum(1 for t in trackers if t.get("tracking_ok"))

        y = 115
        p.setFont(QFont("Segoe UI", 13, weight=QFont.Weight.DemiBold))
        p.setPen(QColor(220, 220, 220))
        p.drawText(24, y, "Summary")
        y += 24
        p.setFont(QFont("Consolas", 11))
        p.setPen(QColor(200, 200, 200))
        p.drawText(24, y, f"Base stations: {station_n} | Trackers: {tracker_n} (OK: {ok_n})")
        y += 18
        diag = state.get("diagnostic") or {}
        p.drawText(24, y, f"Diagnostic: {diag.get('stage','Idle')} {'(running)' if diag.get('running') else ''}")
        y += 18
        p.drawText(24, y, f"VR Coach: {'Running' if (self._coach is not None and self._coach.is_running()) else 'Stopped'}")
        y += 18
        hist = self._logs.summary()
        p.drawText(
            24,
            y,
            f"Historical logs: {'ON' if self.toggles.use_history else 'OFF'} | sessions {hist.sessions} | points {hist.points}",
        )

        # Update button labels based on current toggles/state.
        for i, b in enumerate(self.buttons):
            if b.id == "coach":
                label = "Exit VR Coach" if (self._coach is not None and self._coach.is_running()) else "Launch VR Coach"
                self.buttons[i] = Button(b.id, b.rect, label)
            elif b.id == "history":
                self.buttons[i] = Button(b.id, b.rect, f"History: {'ON' if self.toggles.use_history else 'OFF'}")
            elif b.id == "heatmap":
                self.buttons[i] = Button(b.id, b.rect, f"Heatmap: {'ON' if self.toggles.heatmap else 'OFF'}")
            elif b.id == "body":
                self.buttons[i] = Button(b.id, b.rect, f"Body: {'ON' if self.toggles.body_suggestions else 'OFF'}")

        p.setFont(QFont("Segoe UI", 10, weight=QFont.Weight.DemiBold))
        for b in self.buttons:
            x, by, bw, bh = b.rect
            p.setPen(QPen(QColor(90, 90, 90), 2))
            is_hover = (self._hover_button_id == b.id)
            p.setBrush(QColor(48, 48, 48) if is_hover else QColor(30, 30, 30))
            p.drawRoundedRect(x, by, bw, bh, 8, 8)
            p.setPen(QColor(230, 230, 230))
            p.drawText(x + 14, by + 36, b.label)

        # Cursor hint for interaction debugging.
        if self._mouse_px is not None:
            try:
                mx, my = self._mouse_px
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 140))
                p.drawEllipse(int(mx) - 4, int(my) - 4, 8, 8)
            except Exception:
                pass

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
            # Do not spam recreates; rate-limit with cooldown.
            if self._recreate_if_allowed(f"invalid overlay handle {handle!r}"):
                handle = self.handle
            if not self._is_valid_handle(handle):
                return

        now = time.monotonic()
        if now < self._next_submit_time:
            return

        log.debug("SetOverlayRaw: handle=%s w=%d h=%d depth=%d len=%d", handle, w, h, depth, len(data))
        buf = ctypes.create_string_buffer(data, len(data))

        last_exc: Optional[Exception] = None
        self.submission_attempts += 1
        for attempt in range(1, 4):
            try:
                _safe_call(self.overlay, "SetOverlayRaw", "setOverlayRaw", handle, buf, w, h, depth)
                self.last_error = None
                self._last_submit_ok_time = time.monotonic()
                return
            except openvr.error_code.OverlayError_RequestFailed as e:
                last_exc = e
                self.submission_failures += 1
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("SetOverlayRaw RequestFailed (attempt %d/3); retrying…", attempt)
                time.sleep(0.05 * attempt)
            except openvr.error_code.OverlayError_InvalidHandle as e:
                last_exc = e
                self.submission_failures += 1
                self.last_error = f"{type(e).__name__}: {e}"
                # Treat as a hard lifecycle failure (SteamVR restarted / overlay torn down).
                self._next_submit_time = time.monotonic() + 2.0
                if self._recreate_if_allowed("OverlayError_InvalidHandle during SetOverlayRaw"):
                    handle = self.handle
                return
            except Exception as e:
                last_exc = e
                self.submission_failures += 1
                self.last_error = f"{type(e).__name__}: {e}"
                log.error("SetOverlayRaw failed: %s: %s", type(e).__name__, e)
                return

        # Back off 2-5 seconds on RequestFailed; do not recreate spam or cause flicker.
        backoff_s = float(random.choice([2.0, 3.0, 5.0]))
        self._next_submit_time = time.monotonic() + backoff_s
        now = time.monotonic()
        if now - self._last_error_log_time >= 2.0:
            self._last_error_log_time = now
            log.warning(
                "SetOverlayRaw paused for %.1fs after RequestFailed (w=%d h=%d depth=%d len=%d).",
                backoff_s,
                w,
                h,
                depth,
                len(data),
            )

        # If failures persist, allow a recreate only on cooldown and only after a sustained outage
        # (avoid flicker from recreate spam).
        last_ok = self._last_submit_ok_time
        sustained_outage = (last_ok is None) or ((time.monotonic() - last_ok) > 10.0)
        if sustained_outage and self._recreate_if_allowed(
            f"OverlayError_RequestFailed after retries ({w=} {h=} {depth=} len={len(data)})"
        ):
            try:
                if self.overlay is not None and self._is_valid_handle(self.handle):
                    _safe_call(self.overlay, "SetOverlayRaw", "setOverlayRaw", self.handle, buf, w, h, depth)
                    self.last_error = None
                    self._last_submit_ok_time = time.monotonic()
                    return
            except Exception as e:
                last_exc = e

        log.error(
            "SetOverlayRaw failed after retries; continuing without crashing (w=%d h=%d depth=%d len=%d): %s: %s",
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
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--overlay-test", action="store_true", help="Initialize OpenVR and submit one 256x256 test image")
    ap.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    args = ap.parse_args(argv)

    log_level = logging.DEBUG if (args.debug or os.environ.get("LLC_DEBUG") == "1") else logging.INFO
    log_path = setup_logging(level=log_level, filename="LighthouseLayoutCoach_overlay.log")
    log.info("Overlay logging to %s", log_path)

    app = QGuiApplication([])
    client = DashboardOverlayClient(args.url)
    try:
        client.start()
    except openvr.error_code.InitError_Init_HmdNotFound:
        log.info(
            "OpenVR init failed: InitError_Init_HmdNotFound. This is expected when no HMD/SteamVR runtime is active; "
            "overlay handle validation and SetOverlayRaw submission cannot be performed in this environment."
        )
        return 0 if args.overlay_test else 2
    except Exception as e:
        log.error("Overlay init failed: %s: %s", type(e).__name__, e)
        return 2
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
        try:
            client.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
