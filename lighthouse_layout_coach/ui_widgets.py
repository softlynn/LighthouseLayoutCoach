from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .chaperone import PlayArea
from .coverage import CoverageResult, StationPose, station_yaw_pitch_deg


def make_banner(text: str, kind: str = "warning") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setFrameShape(QFrame.Shape.StyledPanel)
    if kind == "warning":
        label.setStyleSheet("background:#3b2f00;color:#ffd27a;padding:6px;")
    elif kind == "error":
        label.setStyleSheet("background:#3b0000;color:#ffb0b0;padding:6px;")
    else:
        label.setStyleSheet("background:#002b3b;color:#b0e6ff;padding:6px;")
    return label


class SelectorPanel(QGroupBox):
    """
    Simple selection panel for persistent serial-based mapping.
    """

    def __init__(self, title: str, labels: List[str], parent=None) -> None:
        super().__init__(title, parent)
        self._labels = labels
        self._combos: Dict[str, QComboBox] = {}
        layout = QFormLayout(self)
        for lab in labels:
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItem("(not set)", userData=None)
            self._combos[lab] = combo
            layout.addRow(lab, combo)

    def set_options(self, options: List[Tuple[str, str]]) -> None:
        """
        options: list of (display, serial)
        """
        for combo in self._combos.values():
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(not set)", userData=None)
            for disp, serial in options:
                combo.addItem(disp, userData=serial)
            # restore if still present
            if cur is not None:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def set_value(self, label: str, serial: Optional[str]) -> None:
        combo = self._combos[label]
        idx = combo.findData(serial)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def get_values(self) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        for lab, combo in self._combos.items():
            out[lab] = combo.currentData()
        return out

    def combos(self) -> Dict[str, QComboBox]:
        return self._combos


@dataclass(frozen=True)
class SceneStyle:
    ppm: float = 220.0  # pixels per meter


class LayoutViewer(QGraphicsView):
    """
    Top-down 2D viewer for play area, stations, and tracked points.
    Coordinates:
      world meters: +X right, +Y forward; displayed with +Y up (so Y is inverted).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(18, 18, 18))
        self.setScene(QGraphicsScene(self))

        self._style = SceneStyle()

        self._play_poly_item: Optional[QGraphicsPolygonItem] = None
        self._heat_item: Optional[QGraphicsPixmapItem] = None
        self._sync_text_item: Optional[QGraphicsTextItem] = None

        self._station_items: Dict[str, Tuple[QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsTextItem]] = {}
        self._point_items: Dict[str, QGraphicsEllipseItem] = {}

        self._play_area: Optional[PlayArea] = None
        self._coverage: Optional[CoverageResult] = None
        self._heat_mode: str = "foot"
        self._heat_enabled: bool = True

    def set_heatmap_enabled(self, enabled: bool) -> None:
        self._heat_enabled = bool(enabled)
        self._refresh_heatmap()

    def set_heat_mode(self, mode: str) -> None:
        self._heat_mode = mode
        self._refresh_heatmap()

    def set_play_area(self, play_area: PlayArea) -> None:
        self._play_area = play_area
        poly = QPolygonF([self._w2s_xy(x, y) for x, y in play_area.corners_m])
        if self._play_poly_item is None:
            pen = QPen(QColor(200, 200, 200))
            pen.setWidth(2)
            self._play_poly_item = self.scene().addPolygon(poly, pen, QBrush(Qt.BrushStyle.NoBrush))
        else:
            self._play_poly_item.setPolygon(poly)

        self._fit()

    def set_coverage(self, coverage: Optional[CoverageResult]) -> None:
        self._coverage = coverage
        self._refresh_heatmap()

    def set_sync_warning(self, text: Optional[str]) -> None:
        if not text:
            if self._sync_text_item is not None:
                self.scene().removeItem(self._sync_text_item)
                self._sync_text_item = None
            return
        if self._sync_text_item is None:
            self._sync_text_item = self.scene().addText(text)
            self._sync_text_item.setDefaultTextColor(QColor(255, 210, 122))
            self._sync_text_item.setZValue(10)
        else:
            self._sync_text_item.setPlainText(text)
        self._sync_text_item.setPos(QPointF(10, 10))

    def set_stations(self, stations: List[StationPose], labels_by_serial: Optional[Dict[str, str]] = None) -> None:
        labels_by_serial = labels_by_serial or {}
        keep = {s.serial for s in stations}
        for serial in list(self._station_items.keys()):
            if serial not in keep:
                dot, line, text = self._station_items.pop(serial)
                self.scene().removeItem(dot)
                self.scene().removeItem(line)
                self.scene().removeItem(text)

        for s in stations:
            if s.serial not in self._station_items:
                dot = QGraphicsEllipseItem(-6, -6, 12, 12)
                dot.setBrush(QBrush(QColor(120, 180, 255)))
                dot.setPen(QPen(Qt.PenStyle.NoPen))
                dot.setZValue(5)
                self.scene().addItem(dot)

                line = QGraphicsLineItem()
                pen = QPen(QColor(120, 180, 255))
                pen.setWidth(2)
                line.setPen(pen)
                line.setZValue(5)
                self.scene().addItem(line)

                text = self.scene().addText(labels_by_serial.get(s.serial, s.serial))
                text.setDefaultTextColor(QColor(200, 200, 200))
                text.setZValue(6)
                self._station_items[s.serial] = (dot, line, text)

            dot, line, text = self._station_items[s.serial]
            p = self._w2s_xy(s.position_m[0], s.position_m[1])
            sx, sy = p.x(), p.y()
            dot.setPos(p)

            yaw, _ = station_yaw_pitch_deg(s)
            dx = math.cos(math.radians(yaw))
            dy = math.sin(math.radians(yaw))
            a = QPointF(sx, sy)
            b = QPointF(sx + dx * self._style.ppm * 0.35, sy - dy * self._style.ppm * 0.35)
            line.setLine(a.x(), a.y(), b.x(), b.y())
            text.setPlainText(labels_by_serial.get(s.serial, s.serial))
            text.setPos(QPointF(sx + 8, sy + 8))

    def set_points(self, points: Dict[str, Tuple[float, float, QColor]]) -> None:
        """
        points: id -> (x_m, y_m, color)
        """
        keep = set(points.keys())
        for k in list(self._point_items.keys()):
            if k not in keep:
                self.scene().removeItem(self._point_items.pop(k))
        for k, (x, y, color) in points.items():
            if k not in self._point_items:
                dot = QGraphicsEllipseItem(-4, -4, 8, 8)
                dot.setBrush(QBrush(color))
                dot.setPen(QPen(Qt.PenStyle.NoPen))
                dot.setZValue(7)
                self.scene().addItem(dot)
                self._point_items[k] = dot
            self._point_items[k].setPos(self._w2s_xy(x, y))

    def _w2s_xy(self, x_m: float, y_m: float) -> QPointF:
        return QPointF(x_m * self._style.ppm, -y_m * self._style.ppm)

    def _refresh_heatmap(self) -> None:
        if self._heat_item is not None:
            self.scene().removeItem(self._heat_item)
            self._heat_item = None

        if not self._heat_enabled or self._coverage is None:
            return

        cov = self._coverage
        scores = cov.score_foot if self._heat_mode == "foot" else cov.score_waist

        img = QImage(cov.grid_w, cov.grid_h, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        for yi in range(cov.grid_h):
            for xi in range(cov.grid_w):
                idx = yi * cov.grid_w + xi
                if not cov.inside_mask[idx]:
                    continue
                sc = scores[idx]
                if sc <= 0:
                    c = QColor(200, 60, 60, 120)
                elif sc == 1:
                    c = QColor(210, 170, 60, 120)
                else:
                    c = QColor(60, 200, 110, 140)
                img.setPixelColor(xi, yi, c)

        pix = QPixmap.fromImage(img).scaled(
            int(cov.grid_w * cov.grid_step_m * self._style.ppm),
            int(cov.grid_h * cov.grid_step_m * self._style.ppm),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._heat_item = self.scene().addPixmap(pix)
        self._heat_item.setOpacity(0.75)
        ox, oy = cov.grid_origin_m
        self._heat_item.setPos(self._w2s_xy(ox, oy + cov.grid_h * cov.grid_step_m))
        self._heat_item.setZValue(1)

        self._fit()

    def _fit(self) -> None:
        if self._play_poly_item is None:
            return
        rect = self._play_poly_item.boundingRect().adjusted(-80, -80, 80, 80)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)


class RecommendationsWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._label = QLabel("Run a diagnostic test to generate recommendations.")
        self._label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
