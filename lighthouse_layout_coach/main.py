from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from .ui_main import MainWindow


def create_main_window() -> MainWindow:
    return MainWindow()


def run_desktop(existing_app: Optional[QApplication] = None) -> int:
    """
    Runs the existing desktop UI. Safe to call from a launcher by passing an existing QApplication.
    """
    app = existing_app or QApplication(sys.argv)
    app.setApplicationName("LighthouseLayoutCoach")
    try:
        from pathlib import Path

        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        icon_path = base / "assets" / "icons" / "app_icon.ico"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass
    window = create_main_window()
    window.show()
    if existing_app is not None:
        return 0
    return app.exec()


def main() -> int:
    return run_desktop()
