from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtWidgets import QApplication

from .ui_main import MainWindow


def create_main_window() -> MainWindow:
    return MainWindow()


def run_desktop(existing_app: Optional[QApplication] = None) -> int:
    """
    Runs the existing desktop UI. Safe to call from a launcher by passing an existing QApplication.
    """
    app = existing_app or QApplication(sys.argv)
    app.setApplicationName("LighthouseLayoutCoach")
    window = create_main_window()
    window.show()
    if existing_app is not None:
        return 0
    return app.exec()


def main() -> int:
    return run_desktop()
