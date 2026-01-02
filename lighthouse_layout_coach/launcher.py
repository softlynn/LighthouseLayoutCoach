from __future__ import annotations

import argparse
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("lighthouse_layout_coach.launcher")

from .logging_setup import setup_logging


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@dataclass
class VRProcesses:
    engine: object
    http_server: object
    overlay_proc: subprocess.Popen
    url: str
    overlay_log_stop: threading.Event
    overlay_log_queue: "queue.Queue[str]"
    overlay_log_thread: threading.Thread


def create_launcher_window(auto_start_vr: bool = False):
    """
    Creates the PySide6 launcher window (imported lazily so `--smoke` can run without Qt installed).
    """

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

    from .main import create_main_window

    class LauncherWindow(QMainWindow):
        def __init__(self, auto_start_vr: bool = False) -> None:
            super().__init__()
            self.setWindowTitle("LighthouseLayoutCoach")
            self.resize(760, 520)

            self._vr: Optional[VRProcesses] = None

            self.status = QLabel("Choose a mode:")
            self.status.setWordWrap(True)

            self.log_view = QTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setPlaceholderText("Logs…")

            self.btn_desktop = QPushButton("Desktop App")
            self.btn_vr = QPushButton("VR Overlay Mode")
            self.btn_vr_coach = QPushButton("Launch VR Coach (Unity)")
            self.btn_stop = QPushButton("Stop")
            self.btn_stop.setEnabled(False)
            self.btn_updates = QPushButton("Check for Updates…")

            top = QHBoxLayout()
            top.addWidget(self.btn_desktop)
            top.addWidget(self.btn_vr)
            top.addWidget(self.btn_vr_coach)
            top.addWidget(self.btn_stop)
            top.addWidget(self.btn_updates)
            top.addStretch(1)

            root = QWidget()
            layout = QVBoxLayout(root)
            layout.addLayout(top)
            layout.addWidget(self.status)
            layout.addWidget(self.log_view, 1)
            self.setCentralWidget(root)

            self.btn_desktop.clicked.connect(self._start_desktop)
            self.btn_vr.clicked.connect(self._start_vr)
            self.btn_stop.clicked.connect(self._stop_vr)
            self.btn_updates.clicked.connect(self._check_updates)
            self.btn_vr_coach.clicked.connect(self._launch_vr_coach_unity)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(250)

            if auto_start_vr:
                QTimer.singleShot(0, self._start_vr)

        def closeEvent(self, event) -> None:
            self._stop_vr()
            return super().closeEvent(event)

        def _append_log(self, line: str) -> None:
            ts = time.strftime("%H:%M:%S")
            self.log_view.append(f"[{ts}] {line}")

        def _start_desktop(self) -> None:
            self._append_log("Launching desktop UI…")
            self.status.setText("Desktop mode: running (close desktop window to return).")
            self.hide()
            self._desktop_window = create_main_window()
            self._desktop_window.destroyed.connect(self._desktop_closed)
            self._desktop_window.show()

        def _check_updates(self) -> None:
            try:
                from .update_checker import UpdateDialog

                dlg = UpdateDialog(parent=self)
                dlg.exec()
            except Exception as e:
                self._append_log(f"Update check failed: {type(e).__name__}: {e}")

        def _desktop_closed(self) -> None:
            self._append_log("Desktop window closed.")
            self.show()
            self.status.setText("Choose a mode:")

        def _start_vr(self) -> None:
            if self._vr is not None:
                return
            self._append_log("Starting VR mode: state server + overlay client…")
            log.info("VR mode start requested")
            self.status.setText("VR mode: starting…")
            self.btn_stop.setEnabled(True)
            self.btn_vr.setEnabled(False)
            self.btn_desktop.setEnabled(False)
            self.btn_vr_coach.setEnabled(False)

            url = "http://127.0.0.1:17835"
            from .state_server import StateEngine, serve_state

            engine = StateEngine(poll_hz=30.0)
            engine.start()
            http_server = serve_state(engine, host="127.0.0.1", port=17835)

            overlay_cmd = self._overlay_command(url)
            env = os.environ.copy()
            env.setdefault(
                "PYINSTALLER_RUNTIME_TMPDIR",
                os.path.join(os.environ.get("LOCALAPPDATA", os.environ.get("TEMP", ".")), "LighthouseLayoutCoach", "tmp"),
            )
            overlay_proc = subprocess.Popen(
                overlay_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

            overlay_log_stop = threading.Event()
            overlay_log_queue: queue.Queue[str] = queue.Queue()

            def _log_reader() -> None:
                try:
                    if overlay_proc.stdout is None:
                        return
                    for line in iter(overlay_proc.stdout.readline, ""):
                        if overlay_log_stop.is_set():
                            break
                        if line:
                            overlay_log_queue.put(line.rstrip("\n"))
                        if overlay_proc.poll() is not None:
                            break
                except Exception:
                    return

            t = threading.Thread(target=_log_reader, name="OverlayLogReader", daemon=True)
            t.start()

            self._vr = VRProcesses(
                engine=engine,
                http_server=http_server,
                overlay_proc=overlay_proc,
                url=url,
                overlay_log_stop=overlay_log_stop,
                overlay_log_queue=overlay_log_queue,
                overlay_log_thread=t,
            )
            self._append_log("Overlay process started.")
            log.info("VR mode started: overlay_pid=%s", overlay_proc.pid)

        def _overlay_command(self, url: str):
            if _is_frozen():
                # Prefer a bundled onedir overlay helper to avoid onefile _MEI extraction/cleanup warnings.
                try:
                    from pathlib import Path

                    overlay_exe = (Path(sys.executable).resolve().parent / "overlay" / "LighthouseLayoutCoachOverlay.exe")
                    if overlay_exe.exists():
                        return [str(overlay_exe), "--url", url]
                except Exception:
                    pass
                return [sys.executable, "--overlay-client", "--url", url]
            return [sys.executable, "-m", "lighthouse_layout_coach", "--overlay-client", "--url", url]

        def _stop_vr(self) -> None:
            if self._vr is None:
                return
            self._append_log("Stopping VR mode…")
            log.info("VR mode stop requested")

            try:
                req = urllib.request.Request(self._vr.url + "/shutdown", method="POST", data=b"{}")
                urllib.request.urlopen(req, timeout=0.2).read()
            except Exception:
                pass

            try:
                self._vr.http_server.shutdown()
            except Exception:
                pass

            try:
                self._vr.engine.stop()
            except Exception:
                pass

            try:
                self._vr.overlay_log_stop.set()
                self._vr.overlay_proc.terminate()
                self._vr.overlay_proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._vr.overlay_proc.kill()
                except Exception:
                    pass

            try:
                self._vr.overlay_log_thread.join(timeout=1.0)
            except Exception:
                pass

            self._vr = None
            self.btn_stop.setEnabled(False)
            self.btn_vr.setEnabled(True)
            self.btn_desktop.setEnabled(True)
            self.btn_vr_coach.setEnabled(True)
            self.status.setText("VR mode: stopped.")
            self._append_log("VR mode stopped.")
            log.info("VR mode stopped")

        def _launch_vr_coach_unity(self) -> None:
            """
            Launches the standalone Unity VR Coach app (no SteamVR overlays).
            For installed builds, expects the Unity build under `<install>/VRCoach/`.
            For source checkouts, looks under `releases/VRCoach_Windows/`.
            """
            try:
                from pathlib import Path

                exe = None
                if _is_frozen():
                    base = Path(sys.executable).resolve().parent
                    cand = base / "VRCoach" / "LighthouseLayoutCoachVRCoach.exe"
                    if cand.exists():
                        exe = cand
                else:
                    base = Path(__file__).resolve().parents[1]
                    cand = base / "releases" / "VRCoach_Windows" / "LighthouseLayoutCoachVRCoach.exe"
                    if cand.exists():
                        exe = cand

                if exe is None:
                    QMessageBox.information(
                        self,
                        "VR Coach not installed",
                        "Unity VR Coach build not found.\n\n"
                        "Build it from `unity_vr_coach/` and place the Windows build at:\n"
                        "- Installed app: `VRCoach/LighthouseLayoutCoachVRCoach.exe`\n"
                        "- Source checkout: `releases/VRCoach_Windows/LighthouseLayoutCoachVRCoach.exe`",
                    )
                    return

                self._append_log(f"Launching VR Coach: {exe}")
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
            except Exception as e:
                self._append_log(f"Failed to launch VR Coach: {type(e).__name__}: {e}")

        def _tick(self) -> None:
            if self._vr is None:
                return
            proc = self._vr.overlay_proc
            try:
                # Drain a bounded number of log lines per tick to keep UI responsive.
                for _ in range(200):
                    line = self._vr.overlay_log_queue.get_nowait()
                    self._append_log("overlay: " + line.rstrip())
            except queue.Empty:
                pass
            except Exception:
                pass

            if proc.poll() is not None:
                code = proc.returncode
                self._append_log(f"Overlay process exited with code {code}.")
                log.warning("Overlay process exited: code=%s", code)
                self._stop_vr()

    return LauncherWindow(auto_start_vr=auto_start_vr)


def cli_main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--desktop", action="store_true", help="Run desktop UI directly")
    ap.add_argument("--vr", action="store_true", help="Run VR overlay mode (server + overlay client)")
    ap.add_argument("--overlay", action="store_true", help="Alias for --vr")
    ap.add_argument("--smoke", action="store_true", help="Non-UI smoke test (verifies OpenVR DLL loads)")
    ap.add_argument("--overlay-test", action="store_true", help="Submit one overlay frame (OpenVR init + 256x256 image)")
    ap.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    ap.add_argument("--overlay-client", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--url", default="http://127.0.0.1:17835", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.debug:
        os.environ["LLC_DEBUG"] = "1"

    log_level = logging.DEBUG if (args.debug or os.environ.get("LLC_DEBUG") == "1") else logging.INFO
    log_path = setup_logging(level=log_level)
    log.info("Logging to %s", log_path)

    if args.smoke:
        try:
            import openvr  # noqa: F401

            return 0
        except Exception as e:
            print(f"SMOKE FAILED: {type(e).__name__}: {e}")
            return 2

    if args.overlay_client:
        from vr_overlay.overlay_client import main as overlay_main

        ov_args = ["--url", args.url]
        if args.debug or os.environ.get("LLC_DEBUG") == "1":
            ov_args.append("--debug")
        return overlay_main(ov_args)

    if args.overlay_test:
        from vr_overlay.overlay_client import main as overlay_main

        ov_args = ["--overlay-test", "--url", args.url]
        if args.debug or os.environ.get("LLC_DEBUG") == "1":
            ov_args.append("--debug")
        return overlay_main(ov_args)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon

    app = QApplication(sys.argv)
    app.setApplicationName("LighthouseLayoutCoach")

    try:
        from pathlib import Path

        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        icon_path = base / "assets" / "icons" / "app_icon.ico"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass

    if args.desktop:
        from .main import create_main_window

        w = create_main_window()
        w.show()
        return app.exec()

    if args.vr or args.overlay:
        w = create_launcher_window(auto_start_vr=True)
        w.show()
        return app.exec()

    w = create_launcher_window(auto_start_vr=False)
    w.show()
    return app.exec()
