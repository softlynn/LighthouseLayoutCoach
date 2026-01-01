from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QProgressBar, QVBoxLayout

from .storage import load_config, save_config
from .version import is_newer, read_version


DEFAULT_REPO = "Softlynn/LighthouseLayoutCoach"
INSTALLER_ASSET_NAME = "LighthouseLayoutCoach_Setup.exe"


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    html_url: str
    installer_url: str
    installer_size: Optional[int]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _https_only(url: str) -> bool:
    return url.strip().lower().startswith("https://")


def fetch_latest_release(repo: str) -> Optional[ReleaseInfo]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LighthouseLayoutCoach",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=6.0) as r:
        data = json.loads(r.read().decode("utf-8"))

    tag = str(data.get("tag_name") or "")
    html = str(data.get("html_url") or "")
    assets = data.get("assets") or []
    installer_url = ""
    installer_size: Optional[int] = None
    for a in assets:
        if str(a.get("name")) == INSTALLER_ASSET_NAME:
            installer_url = str(a.get("browser_download_url") or "")
            try:
                installer_size = int(a.get("size")) if a.get("size") is not None else None
            except Exception:
                installer_size = None
            break

    if not tag or not html or not installer_url:
        return None
    if not _https_only(installer_url):
        return None
    return ReleaseInfo(tag_name=tag, html_url=html, installer_url=installer_url, installer_size=installer_size)


def _sanity_size_ok(size: Optional[int]) -> bool:
    # Basic sanity check: installer should not be tiny or enormous.
    if size is None:
        return True
    return (size >= 1_000_000) and (size <= 500_000_000)


class _UpdateCheckThread(QThread):
    finished_check = Signal(object)  # Optional[ReleaseInfo]
    failed = Signal(str)

    def __init__(self, repo: str) -> None:
        super().__init__()
        self._repo = repo

    def run(self) -> None:
        try:
            info = fetch_latest_release(self._repo)
            self.finished_check.emit(info)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class _DownloadThread(QThread):
    progress = Signal(int)
    finished_path = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest_path: str, expected_size: Optional[int]) -> None:
        super().__init__()
        self._url = url
        self._dest_path = dest_path
        self._expected_size = expected_size

    def run(self) -> None:
        try:
            req = urllib.request.Request(self._url, headers={"User-Agent": "LighthouseLayoutCoach"})
            with urllib.request.urlopen(req, timeout=30.0) as r:
                total = r.headers.get("Content-Length")
                total_i = int(total) if total and total.isdigit() else self._expected_size
                if not _sanity_size_ok(total_i):
                    raise RuntimeError("Download size is suspicious; aborting.")
                os.makedirs(os.path.dirname(self._dest_path), exist_ok=True)
                read = 0
                with open(self._dest_path, "wb") as f:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        read += len(chunk)
                        if total_i:
                            pct = int(100 * min(1.0, read / max(1, total_i)))
                            self.progress.emit(pct)
            # final size check
            if self._expected_size is not None:
                got = os.path.getsize(self._dest_path)
                if got < int(self._expected_size * 0.7):
                    raise RuntimeError("Downloaded file size mismatch; aborting.")
            self.progress.emit(100)
            self.finished_path.emit(self._dest_path)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class UpdateDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.setModal(True)
        self.resize(520, 220)

        self._cfg = load_config()
        self._repo = str((self._cfg.get("update") or {}).get("repo") or DEFAULT_REPO)
        self._local_version = read_version()

        self._status = QLabel("Checking GitHub Releases…")
        self._status.setWordWrap(True)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.hide()

        self._btn_check = QPushButton("Check Now")
        self._btn_install = QPushButton("Download & Install")
        self._btn_notes = QPushButton("View Release Notes")
        self._btn_close = QPushButton("Close")
        self._btn_install.setEnabled(False)
        self._btn_notes.setEnabled(False)

        btns = QHBoxLayout()
        btns.addWidget(self._btn_check)
        btns.addStretch(1)
        btns.addWidget(self._btn_notes)
        btns.addWidget(self._btn_install)
        btns.addWidget(self._btn_close)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addLayout(btns)

        self._btn_close.clicked.connect(self.accept)
        self._btn_check.clicked.connect(self._start_check)
        self._btn_install.clicked.connect(self._download_and_install)
        self._btn_notes.clicked.connect(self._open_notes)

        self._latest: Optional[ReleaseInfo] = None
        self._check_thread: Optional[_UpdateCheckThread] = None
        self._dl_thread: Optional[_DownloadThread] = None

        self._start_check()

    def _start_check(self) -> None:
        self._btn_check.setEnabled(False)
        self._btn_install.setEnabled(False)
        self._btn_notes.setEnabled(False)
        self._progress.hide()
        self._status.setText(f"Checking GitHub Releases for {self._repo}…")

        self._check_thread = _UpdateCheckThread(self._repo)
        self._check_thread.finished_check.connect(self._check_finished)
        self._check_thread.failed.connect(self._check_failed)
        self._check_thread.start()

        cfg = load_config()
        cfg.setdefault("update", {})
        cfg["update"]["repo"] = self._repo
        cfg["update"]["last_check_utc"] = _utc_now_iso()
        save_config(cfg)

    def _check_failed(self, msg: str) -> None:
        self._btn_check.setEnabled(True)
        self._status.setText(f"Update check failed: {msg}")

    def _check_finished(self, info_obj: object) -> None:
        self._btn_check.setEnabled(True)
        info: Optional[ReleaseInfo] = info_obj if isinstance(info_obj, ReleaseInfo) else None
        self._latest = info
        if not info:
            self._status.setText("No compatible release found (missing installer asset).")
            return
        self._btn_notes.setEnabled(True)
        if is_newer(info.tag_name, self._local_version):
            self._btn_install.setEnabled(True)
            self._status.setText(f"Update available: {self._local_version} → {info.tag_name}")
        else:
            self._status.setText(f"You're on the latest version ({self._local_version}).")

    def _open_notes(self) -> None:
        if not self._latest:
            return
        QDesktopServices.openUrl(QUrl(self._latest.html_url))

    def _download_and_install(self) -> None:
        if not self._latest:
            return
        if not _https_only(self._latest.installer_url):
            QMessageBox.warning(self, "Blocked", "Installer URL is not HTTPS; refusing to download.")
            return

        tmpdir = os.path.join(tempfile.gettempdir(), "LighthouseLayoutCoach")
        dest = os.path.join(tmpdir, INSTALLER_ASSET_NAME)

        self._btn_install.setEnabled(False)
        self._btn_check.setEnabled(False)
        self._progress.show()
        self._progress.setValue(0)
        self._status.setText("Downloading installer…")

        self._dl_thread = _DownloadThread(self._latest.installer_url, dest, self._latest.installer_size)
        self._dl_thread.progress.connect(self._progress.setValue)
        self._dl_thread.finished_path.connect(self._download_finished)
        self._dl_thread.failed.connect(self._download_failed)
        self._dl_thread.start()

    def _download_failed(self, msg: str) -> None:
        self._btn_check.setEnabled(True)
        self._status.setText(f"Download failed: {msg}")

    def _download_finished(self, path: str) -> None:
        self._status.setText("Download complete.")
        res = QMessageBox.question(
            self,
            "Install update",
            "Installer downloaded.\n\nClose the app and run the installer now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception as e:
                QMessageBox.warning(self, "Failed to launch installer", f"{type(e).__name__}: {e}")
                return
            # Exit the entire app so the installer can update cleanly.
            from PySide6.QtWidgets import QApplication

            QApplication.quit()


def maybe_background_update_check(main_window, cfg: Dict[str, Any]) -> None:
    """
    Non-blocking update check at startup. If an update is available, shows a prompt.
    """
    upd = cfg.get("update") or {}
    if not bool(upd.get("auto_check", True)):
        return
    repo = str(upd.get("repo") or DEFAULT_REPO)

    last = _parse_iso(upd.get("last_check_utc"))
    if last is not None:
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        if age_h < 24.0:
            return

    local_ver = read_version()

    def _done(info_obj: object) -> None:
        info: Optional[ReleaseInfo] = info_obj if isinstance(info_obj, ReleaseInfo) else None
        if not info:
            return
        if is_newer(info.tag_name, local_ver):
            res = QMessageBox.information(
                main_window,
                "Update available",
                f"A new version is available: {local_ver} → {info.tag_name}\n\nUse Help → Check for Updates… to install.",
                QMessageBox.StandardButton.Ok,
            )

    t = _UpdateCheckThread(repo)
    t.finished_check.connect(_done)
    # Keep a reference on the window to avoid GC stopping the thread.
    setattr(main_window, "_llc_update_thread", t)
    t.start()

    cfg2 = load_config()
    cfg2.setdefault("update", {})
    cfg2["update"]["repo"] = repo
    cfg2["update"]["last_check_utc"] = _utc_now_iso()
    save_config(cfg2)
