from __future__ import annotations

import datetime as _dt
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openvr
from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .chaperone import PlayArea, get_play_area
from .coverage import CoverageResult, StationPose, compute_coverage
from .metrics import SessionMetrics, analyze_diagnostic_session
from .recommendations import generate_recommendations
from .steamvr_io import DeviceInfo, SteamVRRuntime, device_class_name, tracking_result_name
from .storage import export_report, list_sessions, load_config, load_session, save_config, save_session
from .update_checker import UpdateDialog, maybe_background_update_check
from .version import read_version
from .ui_widgets import LayoutViewer, RecommendationsWidget, SelectorPanel, make_banner
from .setup_wizard import SetupWizard


def _now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _ok_pose(d: DeviceInfo) -> bool:
    return bool(d.connected and d.pose is not None and d.pose.pose_valid and int(d.pose.tracking_result) == int(openvr.TrackingResult_Running_OK))


def _pos_str(d: DeviceInfo) -> Tuple[str, str, str]:
    if d.pose is None:
        return ("", "", "")
    x, y, z = d.pose.position_m
    return (f"{x:+.3f}", f"{y:+.3f}", f"{z:+.3f}")


class DiagnosticRunner(QThread):
    finished_session = Signal(dict, object)  # (session_dict, SessionMetrics)

    def __init__(
        self,
        runtime: SteamVRRuntime,
        tracker_serials: List[str],
        tracker_roles_by_serial: Dict[str, str],
        stations: List[StationPose],
        play_area: PlayArea,
        coverage: Optional[CoverageResult],
        duration_s: float = 60.0,
        poll_hz: float = 90.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._tracker_serials = list(tracker_serials)
        self._tracker_roles_by_serial = dict(tracker_roles_by_serial)
        self._stations = list(stations)
        self._play_area = play_area
        self._coverage = coverage
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

            # HMD yaw
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

        session = {
            "timestamp": _now_stamp(),
            "duration_s": self._duration_s,
            "tracker_roles_by_serial": self._tracker_roles_by_serial,
            "stations": [
                {"serial": s.serial, "pos": list(s.position_m), "rot": [list(r) for r in s.rotation_3x3]} for s in self._stations
            ],
            "play_area": {"corners_m": [list(p) for p in self._play_area.corners_m], "source": self._play_area.source, "warning": self._play_area.warning},
            "coverage_summary": None
            if self._coverage is None
            else {
                "overlap_pct_foot": self._coverage.overlap_pct_foot,
                "overlap_pct_waist": self._coverage.overlap_pct_waist,
                "overall_score": self._coverage.overall_score,
            },
            "samples": samples,
        }

        metrics = analyze_diagnostic_session(samples, self._tracker_roles_by_serial, self._stations)
        self.finished_session.emit(session, metrics)


class DevicesTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.status_label = QLabel("Waiting for SteamVR…")
        self.status_label.setStyleSheet("font-weight:600;")
        self.error_banner = make_banner("", kind="error")
        self.error_banner.hide()

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Index", "Class", "Model", "Serial", "Connected", "PoseValid", "TrackingResult", "X", "Y", "Z"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_banner)
        layout.addWidget(self.table, 1)

    def set_status(self, connected: bool, last_error: Optional[str]) -> None:
        if connected:
            self.status_label.setText("SteamVR connected")
            self.error_banner.hide()
        else:
            self.status_label.setText("Waiting for SteamVR…")
            if last_error:
                self.error_banner.setText(f"Last error: {last_error}")
                self.error_banner.show()
            else:
                self.error_banner.hide()

    def update_devices(self, devices: List[DeviceInfo]) -> None:
        self.table.setRowCount(len(devices))
        for r, d in enumerate(sorted(devices, key=lambda x: x.index)):
            pose_valid = d.pose.pose_valid if d.pose is not None else False
            tracking = tracking_result_name(d.pose.tracking_result) if d.pose is not None else ""
            x, y, z = _pos_str(d)
            vals = [
                str(d.index),
                device_class_name(d.device_class),
                d.model or "",
                d.serial or "",
                "Yes" if d.connected else "No",
                "Yes" if pose_valid else "No",
                tracking,
                x,
                y,
                z,
            ]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c in (0,):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()


class LayoutTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.viewer = LayoutViewer()
        self.warning_banner = make_banner("", kind="warning")
        self.warning_banner.hide()
        self.metrics_label = QLabel("")
        self.metrics_label.setWordWrap(True)

        self.heat_enabled = QCheckBox("Show heatmap")
        self.heat_enabled.setChecked(True)
        self.heat_foot = QRadioButton("Foot (0.15m)")
        self.heat_waist = QRadioButton("Waist (1.0m)")
        self.heat_foot.setChecked(True)

        ctrls = QHBoxLayout()
        ctrls.addWidget(self.heat_enabled)
        ctrls.addWidget(self.heat_foot)
        ctrls.addWidget(self.heat_waist)
        ctrls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.warning_banner)
        layout.addLayout(ctrls)
        layout.addWidget(self.viewer, 1)
        layout.addWidget(self.metrics_label)

        self.heat_enabled.toggled.connect(self.viewer.set_heatmap_enabled)
        self.heat_foot.toggled.connect(lambda v: v and self.viewer.set_heat_mode("foot"))
        self.heat_waist.toggled.connect(lambda v: v and self.viewer.set_heat_mode("waist"))

    def set_play_area(self, play_area: PlayArea) -> None:
        if play_area.warning:
            self.warning_banner.setText(play_area.warning)
            self.warning_banner.show()
        else:
            self.warning_banner.hide()
        self.viewer.set_play_area(play_area)

    def set_coverage(self, coverage: Optional[CoverageResult]) -> None:
        self.viewer.set_coverage(coverage)
        if coverage is None:
            self.metrics_label.setText("Coverage: (insufficient data)")
            self.viewer.set_sync_warning(None)
            return
        self.metrics_label.setText(
            f"Coverage: overlap foot {coverage.overlap_pct_foot:.1f}% | waist {coverage.overlap_pct_waist:.1f}% | score {coverage.overall_score:.1f}/100"
        )
        self.viewer.set_sync_warning(coverage.station_sync_warning)


class DiagnosticsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.banner = make_banner(
            "Run the test while already in SteamVR with Quest Pro connected and trackers visible.",
            kind="info",
        )
        self.script_label = QLabel("Idle")
        self.script_label.setStyleSheet("font-weight:600;")
        self.script_label.setWordWrap(True)
        self.timer_label = QLabel("")

        self.run_btn = QPushButton("Run 60s Diagnostic Test")
        self.run_btn.setEnabled(False)

        self.baseline_combo = QComboBox()
        self.baseline_combo.addItem("(no baseline selected)", userData=None)
        self.set_baseline_btn = QPushButton("Set Baseline to Last Session")
        self.export_btn = QPushButton("Export Report (Last Session)")
        self.export_btn.setEnabled(False)

        self.metrics_view = QTextEdit()
        self.metrics_view.setReadOnly(True)
        self.recs = RecommendationsWidget()

        self.health_table = QTableWidget(0, 5)
        self.health_table.setHorizontalHeaderLabels(["Role", "Serial", "Connected", "Tracking OK", "Dropouts"])
        self.health_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.health_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        top = QHBoxLayout()
        top.addWidget(self.run_btn)
        top.addStretch(1)
        top.addWidget(QLabel("Baseline:"))
        top.addWidget(self.baseline_combo)

        bot = QHBoxLayout()
        bot.addWidget(self.set_baseline_btn)
        bot.addWidget(self.export_btn)
        bot.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.banner)
        layout.addLayout(top)
        layout.addWidget(self.script_label)
        layout.addWidget(self.timer_label)
        layout.addWidget(QLabel("Tracking Health (live)"))
        layout.addWidget(self.health_table)
        layout.addWidget(self.metrics_view, 1)
        layout.addWidget(self.recs)
        layout.addLayout(bot)

        self._last_session: Optional[dict] = None
        self._last_metrics: Optional[SessionMetrics] = None

    def set_can_run(self, can: bool) -> None:
        self.run_btn.setEnabled(bool(can))

    def set_running_ui(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.export_btn.setEnabled(not running and self._last_session is not None)

    def set_script(self, text: str, remaining_s: float) -> None:
        self.script_label.setText(text)
        self.timer_label.setText(f"Time remaining: {remaining_s:0.1f}s")

    def set_results(self, session: dict, metrics: SessionMetrics, rec_text: str, compare_text: str) -> None:
        self._last_session = session
        self._last_metrics = metrics
        self.export_btn.setEnabled(True)
        self.metrics_view.setPlainText(compare_text + "\n\n" + rec_text)

    def set_health_rows(self, rows: List[Tuple[str, str, bool, bool, int]]) -> None:
        self.health_table.setRowCount(len(rows))
        for r, (role, serial, connected, ok, dropouts) in enumerate(rows):
            vals = [role, serial, "Yes" if connected else "No", "Yes" if ok else "No", str(dropouts)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                self.health_table.setItem(r, c, it)
        self.health_table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._version = read_version()
        self.setWindowTitle(f"LighthouseLayoutCoach v{self._version}")
        self.resize(1200, 800)

        self._cfg = load_config()
        self._runtime = SteamVRRuntime(poll_hz=90.0)
        self._runtime.start()

        self._play_area: Optional[PlayArea] = None
        self._coverage: Optional[CoverageResult] = None
        self._coverage_key: Optional[tuple] = None
        self._stations: List[StationPose] = []

        self.tabs = QTabWidget()
        self.devices_tab = DevicesTab()
        self.layout_tab = LayoutTab()
        self.diag_tab = DiagnosticsTab()

        self.tabs.addTab(self.devices_tab, "Devices")
        self.tabs.addTab(self.layout_tab, "Layout")
        self.tabs.addTab(self.diag_tab, "Diagnostics")

        # Selection panels
        self.trackers_sel = SelectorPanel("Select Trackers (persisted by serial)", ["Left Foot", "Right Foot", "Waist"])
        self.stations_sel = SelectorPanel("Select Base Stations (persisted by serial)", ["Station A", "Station B"])

        save_btn = QPushButton("Save Selections")
        save_btn.clicked.connect(self._save_selections)

        sel_box = QWidget()
        sel_layout = QHBoxLayout(sel_box)
        sel_layout.addWidget(self.trackers_sel, 1)
        sel_layout.addWidget(self.stations_sel, 1)
        sel_layout.addWidget(save_btn, 0)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addWidget(sel_box)
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        self._init_menu()
        self._refresh_sessions_list()
        self.diag_tab.baseline_combo.currentIndexChanged.connect(self._baseline_changed)
        self.diag_tab.run_btn.clicked.connect(self._start_diagnostic)
        self.diag_tab.set_baseline_btn.clicked.connect(self._set_baseline_to_last)
        self.diag_tab.export_btn.clicked.connect(self._export_last)

        self._runner: Optional[DiagnosticRunner] = None
        self._live_tracker_state: Dict[str, Dict[str, object]] = {}
        self._script_timer = QTimer(self)
        self._script_timer.timeout.connect(self._tick_script)
        self._script_start = 0.0

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._tick_ui)
        self._ui_timer.start(100)  # ~10 Hz UI updates

        self._chaperone_timer = QTimer(self)
        self._chaperone_timer.timeout.connect(self._tick_chaperone)
        self._chaperone_timer.start(2000)

        self._apply_config_to_selectors()
        QTimer.singleShot(0, self._maybe_run_setup_wizard)
        QTimer.singleShot(1500, self._maybe_auto_update_check)

    def _init_menu(self) -> None:
        help_menu = self.menuBar().addMenu("&Help")
        act_setup = help_menu.addAction("Re-run Setup Wizard…")
        act_updates = help_menu.addAction("Check for Updates…")
        act_about = help_menu.addAction("About…")
        act_setup.triggered.connect(self._run_setup_wizard)
        act_updates.triggered.connect(self._show_update_dialog)
        act_about.triggered.connect(self._about)

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            f"LighthouseLayoutCoach v{self._version}\n\n"
            "SteamVR/OpenVR layout + diagnostics tool.\n"
            "MIT licensed. Unsigned builds may trigger Windows SmartScreen.",
        )

    def _maybe_run_setup_wizard(self) -> None:
        if not self._cfg.get("first_run_completed", False):
            self._run_setup_wizard()

    def _run_setup_wizard(self) -> None:
        wiz = SetupWizard(self._runtime, parent=self)
        res = wiz.exec()
        self._cfg = load_config()
        self._apply_config_to_selectors()
        if res == 0:
            QMessageBox.information(self, "Setup not completed", "Setup wizard was canceled. You can re-run it from Help → Re-run Setup Wizard…")

    def _show_update_dialog(self) -> None:
        dlg = UpdateDialog(parent=self)
        dlg.exec()

    def _maybe_auto_update_check(self) -> None:
        self._cfg = load_config()
        maybe_background_update_check(self, self._cfg)

    def closeEvent(self, event) -> None:
        try:
            if self._runner is not None:
                self._runner.stop()
                self._runner.wait(500)
        except Exception:
            pass
        self._runtime.stop()
        self._runtime.wait(1000)
        return super().closeEvent(event)

    def _apply_config_to_selectors(self) -> None:
        self.trackers_sel.set_value("Left Foot", self._cfg.get("trackers", {}).get("left_foot"))
        self.trackers_sel.set_value("Right Foot", self._cfg.get("trackers", {}).get("right_foot"))
        self.trackers_sel.set_value("Waist", self._cfg.get("trackers", {}).get("waist"))
        self.stations_sel.set_value("Station A", self._cfg.get("base_stations", {}).get("station_a"))
        self.stations_sel.set_value("Station B", self._cfg.get("base_stations", {}).get("station_b"))

    def _save_selections(self) -> None:
        tr = self.trackers_sel.get_values()
        st = self.stations_sel.get_values()
        self._cfg["trackers"] = {"left_foot": tr["Left Foot"], "right_foot": tr["Right Foot"], "waist": tr["Waist"]}
        self._cfg["base_stations"] = {"station_a": st["Station A"], "station_b": st["Station B"]}
        save_config(self._cfg)
        QMessageBox.information(self, "Saved", "Selections saved.")

    def _tick_ui(self) -> None:
        connected = self._runtime.is_connected()
        last_error = self._runtime.last_error()
        snap = self._runtime.get_snapshot()

        self.devices_tab.set_status(connected, last_error)
        self.devices_tab.update_devices(snap)

        trackers = [d for d in snap if d.device_class == int(openvr.TrackedDeviceClass_GenericTracker)]
        stations = [d for d in snap if d.device_class == int(openvr.TrackedDeviceClass_TrackingReference)]

        # Update selector options.
        self.trackers_sel.set_options([(f"{d.model} ({d.serial})", d.serial) for d in trackers if d.serial])
        self.stations_sel.set_options([(f"{d.model} ({d.serial})", d.serial) for d in stations if d.serial])

        # Auto-select if not set and exactly two stations are present.
        if len(stations) == 2 and not (self._cfg.get("base_stations", {}).get("station_a") and self._cfg.get("base_stations", {}).get("station_b")):
            self._cfg["base_stations"] = {"station_a": stations[0].serial, "station_b": stations[1].serial}
            save_config(self._cfg)
            self._apply_config_to_selectors()

        self.diag_tab.set_can_run(connected and self._have_required_selections())

        # Diagnostics live health monitor for selected trackers
        roles = self._tracker_roles_by_serial()
        by_serial = {d.serial: d for d in snap if d.serial}
        health_rows: List[Tuple[str, str, bool, bool, int]] = []
        for serial, role in roles.items():
            d = by_serial.get(serial)
            is_ok = bool(d is not None and _ok_pose(d))
            is_conn = bool(d is not None and d.connected)
            st = self._live_tracker_state.setdefault(serial, {"prev_ok": is_ok, "dropouts": 0})
            if bool(st.get("prev_ok")) and not is_ok:
                st["dropouts"] = int(st.get("dropouts", 0)) + 1
            st["prev_ok"] = is_ok
            health_rows.append((role, serial, is_conn, is_ok, int(st.get("dropouts", 0))))
        self.diag_tab.set_health_rows(health_rows)

        # Layout points + coverage
        self._stations = self._selected_station_poses(snap)
        points = self._selected_points(snap)
        self.layout_tab.viewer.set_stations(self._stations, self._station_labels_by_serial())
        self.layout_tab.viewer.set_points(points)

        self._coverage = self._maybe_recompute_coverage()
        self.layout_tab.set_coverage(self._coverage)

        # Live recommendations panel uses latest metrics if present
        recs = generate_recommendations(
            self._play_area or PlayArea([(-1, -1), (1, -1), (1, 1), (-1, 1)], source="default"),
            self._stations,
            self._coverage,
            getattr(self.diag_tab, "_last_metrics", None),
            station_labels_by_serial=self._station_labels_by_serial(),
        )
        text = "\n".join([f"{r.target} [{r.confidence}]: {r.text}" for r in recs])
        self.diag_tab.recs.set_text(text)

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

    def _tick_chaperone(self) -> None:
        if not self._runtime.is_connected():
            return
        vr_system, vr_chap, vr_setup = self._runtime.get_vr_handles()
        if vr_chap is None and vr_setup is None:
            return
        self._play_area = get_play_area(vr_chap, vr_setup)
        if self._play_area is not None:
            self.layout_tab.set_play_area(self._play_area)

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

    def _have_required_selections(self) -> bool:
        tr = self._cfg.get("trackers", {})
        st = self._cfg.get("base_stations", {})
        return bool(tr.get("left_foot") and tr.get("right_foot") and tr.get("waist") and st.get("station_a") and st.get("station_b"))

    def _selected_station_poses(self, snap: List[DeviceInfo]) -> List[StationPose]:
        st = self._cfg.get("base_stations", {})
        want = [st.get("station_a"), st.get("station_b")]
        out: List[StationPose] = []
        for serial in want:
            if not serial:
                continue
            for d in snap:
                if d.serial == serial and d.pose is not None and d.pose.pose_valid:
                    out.append(StationPose(serial=serial, position_m=d.pose.position_m, rotation_3x3=d.pose.rotation_3x3))
        return out

    def _selected_points(self, snap: List[DeviceInfo]) -> Dict[str, Tuple[float, float, QColor]]:
        pts: Dict[str, Tuple[float, float, QColor]] = {}
        roles = self._tracker_roles_by_serial()

        # HMD
        for d in snap:
            if d.device_class == int(openvr.TrackedDeviceClass_HMD) and d.pose is not None and d.pose.pose_valid:
                pts["HMD"] = (d.pose.position_m[0], d.pose.position_m[1], QColor(230, 230, 230))
                break

        for serial, role in roles.items():
            for d in snap:
                if d.serial == serial and d.pose is not None and d.pose.pose_valid:
                    color = QColor(120, 255, 170) if role == "Waist" else QColor(255, 170, 120)
                    pts[role] = (d.pose.position_m[0], d.pose.position_m[1], color)
        return pts

    def _start_diagnostic(self) -> None:
        if not (self._runtime.is_connected() and self._play_area and len(self._stations) == 2 and self._have_required_selections()):
            QMessageBox.warning(self, "Not ready", "SteamVR must be connected, play area available, and selections set.")
            return

        tracker_roles = self._tracker_roles_by_serial()
        tracker_serials = list(tracker_roles.keys())
        if len(tracker_serials) != 3:
            QMessageBox.warning(self, "Not ready", "Select exactly 3 trackers (Left Foot, Right Foot, Waist).")
            return

        self._runner = DiagnosticRunner(
            runtime=self._runtime,
            tracker_serials=tracker_serials,
            tracker_roles_by_serial=tracker_roles,
            stations=self._stations,
            play_area=self._play_area,
            coverage=self._coverage,
        )
        self._runner.finished_session.connect(self._diagnostic_finished)
        self._runner.start()

        self._script_start = time.perf_counter()
        self._script_timer.start(100)
        self.diag_tab.set_running_ui(True)

    def _tick_script(self) -> None:
        if self._runner is None:
            self._script_timer.stop()
            self.diag_tab.set_script("Idle", 0.0)
            return

        t = time.perf_counter() - self._script_start
        remaining = max(0.0, 60.0 - t)

        if t < 10.0:
            msg = "0–10s: Stand still at center."
        elif t < 25.0:
            msg = "10–25s: Slow 360° turn."
        elif t < 35.0:
            msg = "25–35s: Squat + stand."
        elif t < 50.0:
            msg = "35–50s: Step side-to-side."
        elif t < 55.0:
            msg = "50–55s: Face Station A."
        elif t < 60.0:
            msg = "55–60s: Face Station B."
        else:
            msg = "Finishing…"

        self.diag_tab.set_script(msg, remaining)

    def _diagnostic_finished(self, session: dict, metrics_obj: object) -> None:
        metrics: SessionMetrics = metrics_obj  # PySide signal typing
        self._script_timer.stop()
        self._runner = None
        self.diag_tab.set_running_ui(False)

        # Save session to disk
        saved = save_session(session)
        self._refresh_sessions_list()

        # Build summary and baseline compare
        compare_text = self._build_compare_text(metrics, session)

        # Recommendations
        pa = self._play_area_from_session(session)
        recs = generate_recommendations(
            pa,
            self._stations,
            self._coverage,
            metrics,
            station_labels_by_serial=self._station_labels_by_serial(),
        )
        rec_text = "Recommendations:\n" + "\n".join([f"- {r.target} [{r.confidence}]: {r.text}" for r in recs])

        self.diag_tab.set_results(session, metrics, rec_text=rec_text, compare_text=compare_text)

    def _refresh_sessions_list(self) -> None:
        sessions = list_sessions()
        cur = self.diag_tab.baseline_combo.currentData()
        self.diag_tab.baseline_combo.blockSignals(True)
        self.diag_tab.baseline_combo.clear()
        self.diag_tab.baseline_combo.addItem("(no baseline selected)", userData=None)
        for name, p in sessions.items():
            self.diag_tab.baseline_combo.addItem(name, userData=str(p))
        # restore selection
        if cur is not None:
            idx = self.diag_tab.baseline_combo.findData(cur)
            if idx >= 0:
                self.diag_tab.baseline_combo.setCurrentIndex(idx)
        # config baseline
        base = self._cfg.get("baseline_session")
        if base:
            idx = self.diag_tab.baseline_combo.findData(base)
            if idx >= 0:
                self.diag_tab.baseline_combo.setCurrentIndex(idx)
        self.diag_tab.baseline_combo.blockSignals(False)

    def _baseline_changed(self) -> None:
        base = self.diag_tab.baseline_combo.currentData()
        self._cfg["baseline_session"] = base
        save_config(self._cfg)

        if self.diag_tab._last_session is not None and self.diag_tab._last_metrics is not None:
            compare_text = self._build_compare_text(self.diag_tab._last_metrics, self.diag_tab._last_session)
            self.diag_tab.metrics_view.setPlainText(compare_text + "\n\n" + self.diag_tab.recs._label.text())

    def _set_baseline_to_last(self) -> None:
        if self.diag_tab._last_session is None:
            QMessageBox.information(self, "No session", "Run a diagnostic test first.")
            return
        # last session is already saved; pick it by timestamp.
        sessions = list_sessions()
        ts = self.diag_tab._last_session.get("timestamp")
        if not ts or ts not in sessions:
            QMessageBox.warning(self, "Not found", "Last session file not found.")
            return
        path = str(sessions[ts])
        idx = self.diag_tab.baseline_combo.findData(path)
        if idx >= 0:
            self.diag_tab.baseline_combo.setCurrentIndex(idx)
            QMessageBox.information(self, "Baseline set", f"Baseline set to {ts}.")

    def _export_last(self) -> None:
        if self.diag_tab._last_session is None or self.diag_tab._last_metrics is None:
            return
        summary = self._build_compare_text(self.diag_tab._last_metrics, self.diag_tab._last_session)
        paths = export_report(summary, self.diag_tab._last_session)
        QMessageBox.information(self, "Exported", f"Wrote:\n{paths['summary']}\n{paths['session']}")

    def _build_compare_text(self, current: SessionMetrics, current_session: dict) -> str:
        total_dropouts = sum(t.dropout_count for t in current.per_tracker)
        total_dropout_s = sum(t.dropout_duration_s for t in current.per_tracker)
        p95_pos = sum(t.jitter_pos_rms_m_p95 for t in current.per_tracker) / max(1, len(current.per_tracker))
        p95_yaw = sum(t.jitter_yaw_deg_p95 for t in current.per_tracker) / max(1, len(current.per_tracker))

        cov = current_session.get("coverage_summary") or {}
        cur_line = (
            f"Current: dropouts {total_dropouts} | dropout time {total_dropout_s:.2f}s | jitter pos p95 {p95_pos*1000:.1f}mm | yaw p95 {p95_yaw:.1f}°"
        )
        if cov:
            cur_line += f" | overlap foot {cov.get('overlap_pct_foot', 0):.1f}% | waist {cov.get('overlap_pct_waist', 0):.1f}% | score {cov.get('overall_score', 0):.1f}/100"

        per_tracker_lines: List[str] = ["Per-tracker:"]
        for tm in current.per_tracker:
            top_bins = sorted(tm.dropout_yaw_bins.items(), key=lambda kv: kv[1], reverse=True)[:3]
            bins_s = ", ".join([f"{k}:{v}" for k, v in top_bins]) if top_bins else "(none)"
            per_tracker_lines.append(
                f"- {tm.role} ({tm.serial}): dropouts {tm.dropout_count} ({tm.dropout_duration_s:.2f}s) | jitter p95 {tm.jitter_pos_rms_m_p95*1000:.1f}mm / {tm.jitter_yaw_deg_p95:.1f}° | yaw bins {bins_s}"
            )

        base_path = self._cfg.get("baseline_session")
        if not base_path:
            return cur_line + "\n" + "\n".join(per_tracker_lines)

        base = load_session(Path(base_path))
        if not base:
            return cur_line + "\n" + "\n".join(per_tracker_lines) + "\nBaseline: (failed to load)"

        # Recompute baseline metrics from stored samples to keep consistent logic.
        base_samples = base.get("samples", [])
        roles = base.get("tracker_roles_by_serial", {})
        stations = []
        for s in base.get("stations", []):
            try:
                stations.append(StationPose(serial=s["serial"], position_m=tuple(s["pos"]), rotation_3x3=tuple(tuple(r) for r in s["rot"])))
            except Exception:
                pass
        base_metrics = analyze_diagnostic_session(base_samples, roles, stations)

        b_total_dropouts = sum(t.dropout_count for t in base_metrics.per_tracker)
        b_total_dropout_s = sum(t.dropout_duration_s for t in base_metrics.per_tracker)
        b_p95_pos = sum(t.jitter_pos_rms_m_p95 for t in base_metrics.per_tracker) / max(1, len(base_metrics.per_tracker))
        b_p95_yaw = sum(t.jitter_yaw_deg_p95 for t in base_metrics.per_tracker) / max(1, len(base_metrics.per_tracker))

        delta_line = (
            f"Baseline: dropouts {b_total_dropouts} | dropout time {b_total_dropout_s:.2f}s | jitter pos p95 {b_p95_pos*1000:.1f}mm | yaw p95 {b_p95_yaw:.1f}°\n"
            f"Delta: dropouts {total_dropouts - b_total_dropouts:+d} | dropout time {total_dropout_s - b_total_dropout_s:+.2f}s | jitter pos p95 {(p95_pos - b_p95_pos)*1000:+.1f}mm | yaw p95 {p95_yaw - b_p95_yaw:+.1f}°"
        )
        return cur_line + "\n" + "\n".join(per_tracker_lines) + "\n" + delta_line

    def _play_area_from_session(self, session: dict) -> PlayArea:
        pa = session.get("play_area") or {}
        corners = pa.get("corners_m") or [[-1, -1], [1, -1], [1, 1], [-1, 1]]
        corners_t = [(float(p[0]), float(p[1])) for p in corners]
        return PlayArea(corners_m=corners_t, source=str(pa.get("source") or "default"), warning=pa.get("warning"))
