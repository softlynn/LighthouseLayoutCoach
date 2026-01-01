from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AppPaths:
    root: Path
    config_json: Path
    sessions_dir: Path
    export_dir: Path


def get_paths() -> AppPaths:
    # Always use a user-writable location (required for Program Files installs).
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata) / "LighthouseLayoutCoach"
    else:
        root = Path.home() / "AppData" / "Roaming" / "LighthouseLayoutCoach"
    return AppPaths(
        root=root,
        config_json=root / "config.json",
        sessions_dir=root / "sessions",
        export_dir=root / "export",
    )


def ensure_dirs() -> AppPaths:
    paths = get_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)
    paths.export_dir.mkdir(parents=True, exist_ok=True)
    return paths


def load_config() -> Dict[str, Any]:
    paths = ensure_dirs()
    if not paths.config_json.exists():
        return {
            "first_run_completed": False,
            "last_seen_version": None,
            "trackers": {"left_foot": None, "right_foot": None, "waist": None},
            "base_stations": {"station_a": None, "station_b": None},
            "baseline_session": None,
            "update": {"repo": None, "last_check_utc": None, "auto_check": True},
        }
    try:
        cfg = json.loads(paths.config_json.read_text(encoding="utf-8"))
        # Backfill keys for older configs.
        cfg.setdefault("first_run_completed", False)
        cfg.setdefault("last_seen_version", None)
        cfg.setdefault("trackers", {"left_foot": None, "right_foot": None, "waist": None})
        cfg.setdefault("base_stations", {"station_a": None, "station_b": None})
        cfg.setdefault("baseline_session", None)
        cfg.setdefault("update", {"repo": None, "last_check_utc": None, "auto_check": True})
        return cfg
    except Exception:
        return {
            "first_run_completed": False,
            "last_seen_version": None,
            "trackers": {"left_foot": None, "right_foot": None, "waist": None},
            "base_stations": {"station_a": None, "station_b": None},
            "baseline_session": None,
            "update": {"repo": None, "last_check_utc": None, "auto_check": True},
        }


def save_config(cfg: Dict[str, Any]) -> None:
    paths = ensure_dirs()
    paths.config_json.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def save_session(session: Dict[str, Any]) -> Path:
    paths = ensure_dirs()
    ts = session.get("timestamp") or "unknown_time"
    out = paths.sessions_dir / f"{ts}.json"
    out.write_text(json.dumps(session, indent=2), encoding="utf-8")
    return out


def list_sessions() -> Dict[str, Path]:
    paths = ensure_dirs()
    sessions: Dict[str, Path] = {}
    for p in sorted(paths.sessions_dir.glob("*.json")):
        sessions[p.stem] = p
    return sessions


def load_session(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def export_report(summary_text: str, session: Dict[str, Any]) -> Dict[str, Path]:
    paths = ensure_dirs()
    ts = session.get("timestamp") or "unknown_time"
    summary_path = paths.export_dir / f"{ts}_summary.txt"
    session_path = paths.export_dir / f"{ts}_session.json"
    summary_path.write_text(summary_text, encoding="utf-8")
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    return {"summary": summary_path, "session": session_path}
