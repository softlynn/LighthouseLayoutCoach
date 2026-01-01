from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import openvr
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .chaperone import PlayArea, get_play_area
from .coverage import StationPose, compute_coverage
from .metrics import SessionMetrics, analyze_diagnostic_session
from .storage import load_config, save_config, save_session
from .steamvr_io import DeviceInfo, SteamVRRuntime


def _ok_pose(d: DeviceInfo) -> bool:
    return bool(d.connected and d.pose is not None and d.pose.pose_valid and int(d.pose.tracking_result) == int(openvr.TrackingResult_Running_OK))


class _QuickBaselineRunner(QThread):
    finished_session = Signal(dict, object)  # (session_dict, SessionMetrics)

    def __init__(
        self,
        runtime: SteamVRRuntime,
        tracker_serials: List[str],
        tracker_roles_by_serial: Dict[str, str],
        stations: List[StationPose],
        play_area: PlayArea,
        duration_s: float = 30.0,
        poll_hz: float = 90.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._tracker_serials = list(tracker_serials)
        self._tracker_roles_by_serial = dict(tracker_roles_by_serial)
        self._stations = list(stations)
        self._play_area = play_area
        self._duration_s = float(duration_s)
        self._poll_hz = float(poll_hz)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        start = time.perf_counter()
        dt = 1.0 / max(1.0, self._poll_hz)
        samples: List[dict] = []

        while not self._stop:
            t = time.perf_counter() - start
            if t >= self._duration_s:
                break

            snap = self._runtime.get_snapshot()
            by_serial = {d.serial: d for d in snap if d.serial}

            hmd_yaw = None
            for d in snap:
                if d.device_class == int(openvr.TrackedDeviceClass_HMD) and d.pose is not None and d.pose.pose_valid:
                    hmd_yaw = float(d.pose.yaw_deg)
                    break

            trk: Dict[str, dict] = {}
            for serial in self._tracker_serials:
                d = by_serial.get(serial)
                if d is None or d.pose is None:
                    trk[serial] = {"ok": False}
                else:
                    trk[serial] = {
                        "pos": [float(d.pose.position_m[0]), float(d.pose.position_m[1]), float(d.pose.position_m[2])],
                        "yaw_deg": float(d.pose.yaw_deg),
                        "ok": bool(_ok_pose(d)),
                    }
            samples.append({"t_s": float(t), "hmd_yaw_deg": hmd_yaw, "trackers": trk})
            time.sleep(dt)

        coverage = compute_coverage(self._play_area, self._stations) if len(self._stations) == 2 else None
        session = {
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "duration_s": self._duration_s,
            "tracker_roles_by_serial": self._tracker_roles_by_serial,
            "stations": [
                {"serial": s.serial, "pos": list(s.position_m), "rot": [list(r) for r in s.rotation_3x3]} for s in self._stations
            ],
            "play_area": {"corners_m": [list(p) for p in self._play_area.corners_m], "source": self._play_area.source, "warning": self._play_area.warning},
            "coverage_summary": None
            if coverage is None
            else {"overlap_pct_foot": coverage.overlap_pct_foot, "overlap_pct_waist": coverage.overlap_pct_waist, "overall_score": coverage.overall_score},
            "samples": samples,
        }

        metrics = analyze_diagnostic_session(samples, self._tracker_roles_by_serial, self._stations)
        self.finished_session.emit(session, metrics)


class SetupWizard(QDialog):
    """
    First-run setup wizard (modal).
    If the user cancels, we do not set `first_run_completed` and will prompt again next start.
    """

    def __init__(self, runtime: SteamVRRuntime, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LighthouseLayoutCoach Setup")
        self.setModal(True)
        self.resize(760, 540)

        self._runtime = runtime
        self._cfg = load_config()

        self._stack = QStackedWidget()
        self._btn_back = QPushButton("Back")
        self._btn_next = QPushButton("Next")
        self._btn_cancel = QPushButton("Cancel")

        nav = QHBoxLayout()
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)
        nav.addStretch(1)
        nav.addWidget(self._btn_cancel)

        root = QVBoxLayout(self)
        root.addWidget(self._stack, 1)
        root.addLayout(nav)

        self._pages: List[QWidget] = []
        self._add_pages()
        self._stack.setCurrentIndex(0)
        self._update_buttons()

        self._btn_back.clicked.connect(self._back)
        self._btn_next.clicked.connect(self._next)
        self._btn_cancel.clicked.connect(self.reject)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

        self._baseline_runner: Optional[_QuickBaselineRunner] = None
        self._baseline_path: Optional[str] = None

    def _add_pages(self) -> None:
        self._pages.append(self._page_welcome())
        self._pages.append(self._page_steamvr())
        self._pages.append(self._page_devices())
        self._pages.append(self._page_play_area())
        self._pages.append(self._page_baseline())
        self._pages.append(self._page_finish())
        for p in self._pages:
            self._stack.addWidget(p)

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("Welcome")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                "Prerequisites:\n"
                "1) Start Virtual Desktop → SteamVR\n"
                "2) Ensure base stations are on\n"
                "3) Ensure Vive Trackers are on and visible in SteamVR\n\n"
                "This wizard will select your 2 base stations and label 3 trackers, then optionally create a baseline session."
            )
        )
        layout.addStretch(1)
        return w

    def _page_steamvr(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("SteamVR Detection")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)
        self._steamvr_status = QLabel("Waiting for SteamVR…")
        self._steamvr_status.setStyleSheet("font-weight:600;")
        layout.addWidget(self._steamvr_status)
        self._steamvr_hint = QLabel("Keep SteamVR running; this screen will update automatically.")
        self._steamvr_hint.setWordWrap(True)
        layout.addWidget(self._steamvr_hint)
        layout.addStretch(1)
        return w

    def _page_devices(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("Device Selection")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)

        self._device_status = QLabel("")
        self._device_status.setWordWrap(True)
        layout.addWidget(self._device_status)

        form = QFormLayout()
        self._trk_left = QComboBox()
        self._trk_right = QComboBox()
        self._trk_waist = QComboBox()
        self._st_a = QComboBox()
        self._st_b = QComboBox()

        for cb in [self._trk_left, self._trk_right, self._trk_waist, self._st_a, self._st_b]:
            cb.addItem("(select)", userData=None)

        form.addRow("Left Foot tracker", self._trk_left)
        form.addRow("Right Foot tracker", self._trk_right)
        form.addRow("Waist tracker", self._trk_waist)
        form.addRow("Station A", self._st_a)
        form.addRow("Station B", self._st_b)

        layout.addLayout(form)
        layout.addStretch(1)
        return w

    def _page_play_area(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("Play Area Detection")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)
        self._play_area_status = QLabel("Detecting chaperone bounds…")
        self._play_area_status.setWordWrap(True)
        layout.addWidget(self._play_area_status)
        layout.addStretch(1)
        return w

    def _page_baseline(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("Baseline (Optional)")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Run a short baseline test now to compare improvements later."))
        self._run_baseline = QCheckBox("Run ~30s baseline test now")
        self._run_baseline.setChecked(True)
        layout.addWidget(self._run_baseline)

        self._baseline_status = QLabel("Not started.")
        self._baseline_status.setWordWrap(True)
        layout.addWidget(self._baseline_status)
        self._baseline_progress = QProgressBar()
        self._baseline_progress.setRange(0, 30)
        self._baseline_progress.setValue(0)
        layout.addWidget(self._baseline_progress)
        layout.addStretch(1)
        return w

    def _page_finish(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        title = QLabel("Finish")
        title.setStyleSheet("font-weight:600;font-size:16px;")
        layout.addWidget(title)
        self._finish_status = QLabel("Click Finish to save settings.")
        self._finish_status.setWordWrap(True)
        layout.addWidget(self._finish_status)
        layout.addStretch(1)
        return w

    def _tick(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 1:
            self._steamvr_status.setText("SteamVR connected" if self._runtime.is_connected() else "Waiting for SteamVR…")
        if idx == 2:
            self._refresh_device_lists()
        if idx == 3:
            self._refresh_play_area()
        if idx == 4:
            self._tick_baseline()

        self._update_buttons()

    def _refresh_device_lists(self) -> None:
        if not self._runtime.is_connected():
            self._device_status.setText("SteamVR not connected yet.")
            return
        snap = self._runtime.get_snapshot()
        trackers = [d for d in snap if d.device_class == int(openvr.TrackedDeviceClass_GenericTracker) and d.serial]
        stations = [d for d in snap if d.device_class == int(openvr.TrackedDeviceClass_TrackingReference) and d.serial]

        def set_options(cb: QComboBox, items: List[DeviceInfo]) -> None:
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("(select)", userData=None)
            for d in items:
                cb.addItem(f"{d.model} ({d.serial})", userData=d.serial)
            if cur is not None:
                ix = cb.findData(cur)
                if ix >= 0:
                    cb.setCurrentIndex(ix)
            cb.blockSignals(False)

        set_options(self._trk_left, trackers)
        set_options(self._trk_right, trackers)
        set_options(self._trk_waist, trackers)
        set_options(self._st_a, stations)
        set_options(self._st_b, stations)

        self._device_status.setText(f"Found {len(trackers)} trackers and {len(stations)} base stations.")

        # Auto-fill from config if present.
        tr = self._cfg.get("trackers", {})
        st = self._cfg.get("base_stations", {})
        if tr.get("left_foot"):
            self._set_combo_serial(self._trk_left, tr.get("left_foot"))
        if tr.get("right_foot"):
            self._set_combo_serial(self._trk_right, tr.get("right_foot"))
        if tr.get("waist"):
            self._set_combo_serial(self._trk_waist, tr.get("waist"))
        if st.get("station_a"):
            self._set_combo_serial(self._st_a, st.get("station_a"))
        if st.get("station_b"):
            self._set_combo_serial(self._st_b, st.get("station_b"))

        # If exactly two stations exist and unset, preselect.
        if len(stations) == 2 and not (st.get("station_a") and st.get("station_b")):
            self._set_combo_serial(self._st_a, stations[0].serial)
            self._set_combo_serial(self._st_b, stations[1].serial)

    def _refresh_play_area(self) -> None:
        if not self._runtime.is_connected():
            self._play_area_status.setText("SteamVR not connected yet.")
            return
        _, chap, setup = self._runtime.get_vr_handles()
        pa = get_play_area(chap, setup)
        if pa.warning:
            self._play_area_status.setText(pa.warning)
        else:
            self._play_area_status.setText(f"Chaperone bounds detected ({pa.source}).")

    def _tick_baseline(self) -> None:
        if self._baseline_runner is None:
            return
        # Progress is time-based from our own counter; good enough.
        v = self._baseline_progress.value()
        if v < 30:
            self._baseline_progress.setValue(v + 1)

    def _set_combo_serial(self, cb: QComboBox, serial: Optional[str]) -> None:
        if not serial:
            return
        ix = cb.findData(serial)
        if ix >= 0:
            cb.setCurrentIndex(ix)

    def _back(self) -> None:
        i = self._stack.currentIndex()
        if i > 0:
            self._stack.setCurrentIndex(i - 1)
        self._update_buttons()

    def _next(self) -> None:
        i = self._stack.currentIndex()

        if i == 2:
            ok, msg = self._validate_and_save_device_selection()
            if not ok:
                self._device_status.setText(msg)
                return

        if i == 4:
            # baseline page: if checked and not run yet, start and wait on finish.
            if self._run_baseline.isChecked() and self._baseline_runner is None and self._baseline_path is None:
                ok = self._start_baseline()
                if not ok:
                    return
                # do not advance yet; wait until finished callback sets baseline.
                self._btn_next.setEnabled(False)
                return

        if i < len(self._pages) - 1:
            self._stack.setCurrentIndex(i + 1)

        # Finish button on last page
        if self._stack.currentIndex() == len(self._pages) - 1:
            self._btn_next.setText("Finish")
        self._update_buttons()

        if self._btn_next.text() == "Finish" and self._stack.currentIndex() == len(self._pages) - 1:
            self._finalize()

    def _validate_and_save_device_selection(self) -> Tuple[bool, str]:
        lf = self._trk_left.currentData()
        rf = self._trk_right.currentData()
        wa = self._trk_waist.currentData()
        sa = self._st_a.currentData()
        sb = self._st_b.currentData()

        if not (lf and rf and wa and sa and sb):
            return False, "Select 3 trackers and 2 base stations."
        if len({lf, rf, wa}) != 3:
            return False, "Tracker selections must be 3 different devices."
        if sa == sb:
            return False, "Station A and Station B must be different devices."

        self._cfg["trackers"] = {"left_foot": lf, "right_foot": rf, "waist": wa}
        self._cfg["base_stations"] = {"station_a": sa, "station_b": sb}
        save_config(self._cfg)
        return True, "Saved."

    def _start_baseline(self) -> bool:
        if not self._runtime.is_connected():
            self._baseline_status.setText("SteamVR not connected yet.")
            return False

        snap = self._runtime.get_snapshot()
        by_serial = {d.serial: d for d in snap if d.serial}

        roles = {
            self._cfg.get("trackers", {}).get("left_foot"): "Left Foot",
            self._cfg.get("trackers", {}).get("right_foot"): "Right Foot",
            self._cfg.get("trackers", {}).get("waist"): "Waist",
        }
        roles = {k: v for k, v in roles.items() if k}
        if len(roles) != 3:
            self._baseline_status.setText("Select trackers first.")
            return False

        # Station poses
        sa = self._cfg.get("base_stations", {}).get("station_a")
        sb = self._cfg.get("base_stations", {}).get("station_b")
        stations: List[StationPose] = []
        for serial in [sa, sb]:
            d = by_serial.get(serial)
            if d is None or d.pose is None or not d.pose.pose_valid:
                continue
            stations.append(StationPose(serial=serial, position_m=d.pose.position_m, rotation_3x3=d.pose.rotation_3x3))
        if len(stations) != 2:
            self._baseline_status.setText("Station poses not valid yet; stand where stations can see the room.")
            return False

        _, chap, setup = self._runtime.get_vr_handles()
        pa = get_play_area(chap, setup)

        self._baseline_progress.setValue(0)
        self._baseline_status.setText("Running baseline… (0–10s still, 10–25s slow turn, 25–30s step)")

        self._baseline_runner = _QuickBaselineRunner(
            runtime=self._runtime,
            tracker_serials=list(roles.keys()),
            tracker_roles_by_serial=roles,
            stations=stations,
            play_area=pa,
            duration_s=30.0,
            poll_hz=90.0,
        )
        self._baseline_runner.finished_session.connect(self._baseline_finished)
        self._baseline_runner.start()
        return True

    def _baseline_finished(self, session: dict, metrics_obj: object) -> None:
        metrics: SessionMetrics = metrics_obj
        p = save_session(session)
        self._baseline_path = str(p)
        self._cfg["baseline_session"] = self._baseline_path
        save_config(self._cfg)
        self._baseline_status.setText(
            f"Baseline saved.\nDropouts: {sum(t.dropout_count for t in metrics.per_tracker)} | "
            f"Dropout time: {sum(t.dropout_duration_s for t in metrics.per_tracker):.2f}s"
        )
        self._baseline_runner = None
        self._btn_next.setEnabled(True)
        # Advance to finish
        self._stack.setCurrentIndex(self._stack.currentIndex() + 1)
        self._update_buttons()

    def _finalize(self) -> None:
        self._cfg["first_run_completed"] = True
        save_config(self._cfg)
        self.accept()

    def _update_buttons(self) -> None:
        i = self._stack.currentIndex()
        self._btn_back.setEnabled(i > 0)
        if i == len(self._pages) - 1:
            self._btn_next.setText("Finish")
        else:
            self._btn_next.setText("Next")
        # Gate moving past SteamVR page until connected
        if i == 1:
            self._btn_next.setEnabled(self._runtime.is_connected())
        elif i == 4 and self._baseline_runner is not None:
            self._btn_next.setEnabled(False)
        else:
            self._btn_next.setEnabled(True)

