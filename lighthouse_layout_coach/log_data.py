from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from .chaperone import PlayArea
from .storage import get_paths

log = logging.getLogger("lighthouse_layout_coach.log_data")

Point2 = Tuple[float, float]


@dataclass(frozen=True)
class Heatmap:
    origin_m: Point2
    step_m: float
    w: int
    h: int
    # -1 for cells outside play area; otherwise 0..100 (higher is better tracking)
    score: list[int]
    source: str


@dataclass(frozen=True)
class LogSummary:
    sessions: int
    samples: int
    points: int
    ok_points: int
    bad_points: int


def _bbox(corners: Iterable[Point2]) -> Tuple[float, float, float, float]:
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_poly(pt: Point2, poly: list[Point2]) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if ((y0 > y) != (y1 > y)) and (x < (x1 - x0) * (y - y0) / max(1e-9, (y1 - y0)) + x0):
            inside = not inside
    return inside


class LogDataProvider:
    """
    Read-only ingestion of prior-run session logs from %APPDATA%\\LighthouseLayoutCoach\\sessions\\*.json.
    Designed to load once and then provide derived summaries/heatmaps.
    """

    def __init__(self) -> None:
        self._loaded = False
        self._paths: list[Path] = []
        self._summary = LogSummary(sessions=0, samples=0, points=0, ok_points=0, bad_points=0)

    def load_once(self) -> None:
        if self._loaded:
            return
        paths = get_paths().sessions_dir
        self._paths = sorted(paths.glob("*.json"))
        self._summary = LogSummary(sessions=len(self._paths), samples=0, points=0, ok_points=0, bad_points=0)
        self._loaded = True
        log.info("Historical logs: %d session files in %s", len(self._paths), paths)

    def summary(self) -> LogSummary:
        self.load_once()
        return self._summary

    def compute_heatmap(self, play_area: PlayArea, step_m: float = 0.25) -> Optional[Heatmap]:
        self.load_once()
        if not self._paths:
            return None

        min_x, min_y, max_x, max_y = _bbox(play_area.corners_m)
        w = max(1, int((max_x - min_x) / step_m) + 1)
        h = max(1, int((max_y - min_y) / step_m) + 1)

        ok = [0] * (w * h)
        bad = [0] * (w * h)
        inside = [False] * (w * h)
        poly = list(play_area.corners_m)
        for yi in range(h):
            for xi in range(w):
                cx = min_x + (xi + 0.5) * step_m
                cy = min_y + (yi + 0.5) * step_m
                inside[yi * w + xi] = _point_in_poly((cx, cy), poly)

        sessions = 0
        samples = 0
        points = 0
        ok_points = 0
        bad_points = 0

        for p in self._paths:
            try:
                obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            sess_samples = obj.get("samples")
            if not isinstance(sess_samples, list):
                continue
            sessions += 1
            samples += len(sess_samples)

            for s in sess_samples:
                if not isinstance(s, dict):
                    continue
                trackers = s.get("trackers")
                if not isinstance(trackers, dict):
                    continue
                for _serial, tr in trackers.items():
                    if not isinstance(tr, dict):
                        continue
                    pos = tr.get("pos")
                    if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
                        continue
                    x = float(pos[0])
                    y = float(pos[1])
                    xi = int((x - min_x) / step_m)
                    yi = int((y - min_y) / step_m)
                    if not (0 <= xi < w and 0 <= yi < h):
                        continue
                    idx = yi * w + xi
                    if not inside[idx]:
                        continue
                    is_ok = bool(tr.get("ok"))
                    points += 1
                    if is_ok:
                        ok[idx] += 1
                        ok_points += 1
                    else:
                        bad[idx] += 1
                        bad_points += 1

        self._summary = LogSummary(
            sessions=sessions,
            samples=samples,
            points=points,
            ok_points=ok_points,
            bad_points=bad_points,
        )

        score: list[int] = []
        for i in range(w * h):
            if not inside[i]:
                score.append(-1)
                continue
            tot = ok[i] + bad[i]
            if tot <= 0:
                score.append(50)
            else:
                score.append(int(round(100.0 * ok[i] / tot)))

        return Heatmap(origin_m=(min_x, min_y), step_m=step_m, w=w, h=h, score=score, source="historical_logs")

