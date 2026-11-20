"""Холст редактора: фото (вписано), слой контуров кандидатов и заливок элементов, номера, композиционная линия.
Клик — в координатах кандидатов (длинная сторона фото ≤ 1280); линию можно перетаскивать.

Инструменты (0.1.2): sam — клик как раньше; hand — обвести от руки; points — многоугольник по точкам (двойной клик —
замкнуть); erase — ластик по элементу; фигуры rect / ellipse / tri / hband / vband / sector — тянуть мышью;
horizon — провести линию по горизонту. Готовая маска → сигнал shape_done, ластик → erase_done, горизонт → horizon_done.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SHAPES = ("rect", "ellipse", "tri", "hband", "vband", "sector")


def shape_path(kind, a, b, W, H):
    """Контур фигуры по двум точкам перетаскивания (координаты фото)."""
    path = QPainterPath()
    r = QRectF(a, b).normalized()
    if kind == "rect":
        path.addRect(r)
    elif kind == "ellipse":
        path.addEllipse(r)
    elif kind == "tri":
        path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), r.bottomRight(), r.bottomLeft()]))
        path.closeSubpath()
    elif kind == "hband":
        path.addRect(QRectF(0, r.top(), W, r.height()))
    elif kind == "vband":
        path.addRect(QRectF(r.left(), 0, r.width(), H))
    elif kind == "sector":                         # сектор: центр — начало, радиус и направление — конец
        rad = math.hypot(b.x() - a.x(), b.y() - a.y())
        ang = math.degrees(math.atan2(-(b.y() - a.y()), b.x() - a.x()))
        path.moveTo(a)
        path.arcTo(QRectF(a.x() - rad, a.y() - rad, 2 * rad, 2 * rad), ang - 45, 90)
        path.closeSubpath()
    return path


def path_mask(path, W, H, stroke=0.0):
    """Маска (H×W bool) из контура; stroke > 0 — обводка толщиной stroke (для ластика)."""
    img = QImage(W, H, QImage.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if stroke > 0:
        p.setPen(QPen(QColor(255, 255, 255), stroke, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    else:
        p.setPen(Qt.NoPen)
        p.fillPath(path, QBrush(QColor(255, 255, 255)))
    p.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(H, img.bytesPerLine())[:, :W]
    return a > 127


def smooth_points(pts, k):
    """Сглаживание линии от руки скользящим средним (k точек)."""
    if k <= 1 or len(pts) < 3:
        return pts
    a = np.array(pts, np.float32)
    pad = np.concatenate([a[-k:], a, a[:k]])
    ker = np.ones(2 * k + 1) / (2 * k + 1)
    out = np.stack([np.convolve(pad[:, i], ker, mode="same")[k:-k] for i in range(2)], axis=1)
    return [tuple(x) for x in out]

PALETTE = [(255, 140, 40), (60, 200, 255), (120, 255, 120), (255, 90, 200), (255, 230, 60), (160, 120, 255),
           (255, 255, 255), (255, 80, 80), (80, 255, 220), (200, 255, 80)]


def boundary(m, thick=1):
    """Контур маски (толщина 1–2 пикселя) — numpy, без OpenCV."""
    e = m.copy()
    e[1:-1, 1:-1] = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    b = m & ~e
    if thick > 1:
        b2 = b.copy()
        b2[1:] |= b[:-1]
        b2[:, 1:] |= b[:, :-1]
        b = b2
    return b


class Canvas(QWidget):
    clicked = Signal(int, int, object)       # x, y (пиксели кандидатов), модификаторы
    line_moved = Signal(float)               # новая композиционная линия, доля высоты
    shape_done = Signal(object, str)         # маска H×W bool, откуда (рука / точки / фигура)
    erase_done = Signal(object)              # маска стёртого H×W bool
    horizon_done = Signal(float)             # угол горизонта, градусы (по часовой — положительный)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(640, 420)
        self.photo = None
        self.overlay = None
        self.labels = []                     # [(x, y, текст, (r, g, b))]
        self.line_y = None
        self.show_line = True
        self.hint = ""
        self._drag = False
        self._overlay_buf = None
        self.tool = "sam"
        self.brush = 24.0                    # толщина ластика, пиксели фото
        self.smooth = 4                      # сглаживание руки, точек
        self._pts = []                       # рука / точки / ластик — в координатах фото
        self._a = self._b = None             # фигура / горизонт — две точки
        self._hover = None

    # ------------------------------------------------------------- данные
    def set_photo(self, img):
        self.photo = img
        self.update()

    def set_overlay(self, rgba):
        """rgba: H×W×4 uint8 (прозрачный фон)."""
        self._overlay_buf = np.ascontiguousarray(rgba)
        h, w = rgba.shape[:2]
        self.overlay = QImage(self._overlay_buf.data, w, h, 4 * w, QImage.Format_RGBA8888)
        self.update()

    # ------------------------------------------------------------- геометрия
    def _frame(self):
        if not self.photo:
            return QRectF(), 1.0
        W, H = self.photo.width(), self.photo.height()
        s = min(self.width() / W, self.height() / H)
        return QRectF((self.width() - W * s) / 2, (self.height() - H * s) / 2, W * s, H * s), s

    def to_img(self, pos):
        r, s = self._frame()
        return (pos.x() - r.x()) / s, (pos.y() - r.y()) / s

    def _line_px(self):
        r, _ = self._frame()
        return r.y() + self.line_y * r.height() if self.line_y is not None else None

    # ------------------------------------------------------------- рисование
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0a0a"))
        if not self.photo:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, self.hint or "нет фото")
            p.end()
            return
        r, s = self._frame()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(r, self.photo)
        if self.overlay is not None:
            p.drawImage(r, self.overlay)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Arial", 11, QFont.Bold)
        p.setFont(f)
        for x, y, text, col in self.labels:
            pt = QPointF(r.x() + x * s, r.y() + y * s)
            p.setPen(QPen(QColor(0, 0, 0), 4))
            p.drawText(pt, text)
            p.setPen(QColor(*col))
            p.drawText(pt, text)
        self._paint_tool(p, r, s)
        ly = self._line_px()
        if self.show_line and ly is not None:
            p.setPen(QPen(QColor(255, 60, 60, 200), 2, Qt.DashLine))
            p.drawLine(QPointF(r.left(), ly), QPointF(r.right(), ly))
            p.setPen(QColor(255, 90, 90))
            p.drawText(QPointF(r.left() + 6, ly - 4), f"линия {self.line_y:.2f} (тянуть мышью)")
        p.end()

    def _paint_tool(self, p, r, s):
        """Предпросмотр рисования: жёлтым — контур, красным — ластик."""
        to = lambda q: QPointF(r.x() + q[0] * s, r.y() + q[1] * s)
        yel = QColor(255, 207, 61)
        if self.tool in ("hand", "points") and self._pts:
            pts = [to(q) for q in self._pts] + ([self._hover] if self.tool == "points" and self._hover else [])
            p.setPen(QPen(yel, 2, Qt.DashLine))
            p.setBrush(QColor(255, 207, 61, 40))
            p.drawPolygon(QPolygonF(pts))
        if self.tool == "erase":
            p.setPen(QPen(QColor(255, 90, 80), 1))
            p.setBrush(Qt.NoBrush)
            if self._hover:
                p.drawEllipse(self._hover, self.brush / 2 * s, self.brush / 2 * s)
            if len(self._pts) > 1:
                p.setPen(QPen(QColor(255, 90, 80, 160), self.brush * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(QPolygonF([to(q) for q in self._pts]))
        if self._a and self._b and self.photo:
            a, b = QPointF(*self._a), QPointF(*self._b)
            if self.tool == "horizon":
                p.setPen(QPen(QColor(80, 220, 255), 2))
                p.drawLine(to(self._a), to(self._b))
            elif self.tool in SHAPES:
                path = shape_path(self.tool, a, b, self.photo.width(), self.photo.height())
                p.save()
                p.translate(r.x(), r.y())
                p.scale(s, s)
                p.setPen(QPen(yel, 2 / s, Qt.DashLine))
                p.setBrush(QColor(255, 207, 61, 50))
                p.drawPath(path)
                p.restore()

    # ------------------------------------------------------------- инструменты
    def set_tool(self, tool):
        self.tool = tool
        self._pts, self._a, self._b = [], None, None
        self.setCursor(Qt.CrossCursor)
        self.update()

    def _inside(self, pos):
        x, y = self.to_img(pos)
        W, H = self.photo.width(), self.photo.height()
        return min(max(x, 0.0), W - 1.0), min(max(y, 0.0), H - 1.0)

    def _finish_poly(self, pts, origin):
        if len(pts) >= 3:
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(*q) for q in pts]))
            path.closeSubpath()
            m = path_mask(path, self.photo.width(), self.photo.height())
            if m.sum() >= 30:
                self.shape_done.emit(m, origin)
        self._pts = []
        self.update()

    # ------------------------------------------------------------- мышь
    def _near_line(self, pos):
        ly = self._line_px()
        return self.show_line and ly is not None and abs(pos.y() - ly) < 6

    def mousePressEvent(self, e):
        if not self.photo:
            return
        if e.button() == Qt.RightButton and self.tool != "sam":      # правый клик — отменить рисование
            self._pts, self._a, self._b = [], None, None
            self.update()
            return
        if e.button() != Qt.LeftButton:
            return
        if self._near_line(e.position()):
            self._drag = True
            return
        if self.tool != "sam":
            q = self._inside(e.position())
            if self.tool in ("hand", "erase"):
                self._pts = [q]
            elif self.tool == "points":
                self._pts.append(q)
            else:
                self._a = self._b = q
            self.update()
            return
        x, y = self.to_img(e.position())
        if 0 <= x < self.photo.width() and 0 <= y < self.photo.height():
            self.clicked.emit(int(x), int(y), e.modifiers())

    def mouseMoveEvent(self, e):
        self._hover = e.position()
        if self.tool != "sam" and not self._drag and self.photo:
            if e.buttons() & Qt.LeftButton:
                q = self._inside(e.position())
                if self.tool in ("hand", "erase"):
                    if not self._pts or math.dist(self._pts[-1], q) > 2:
                        self._pts.append(q)
                elif self._a:
                    self._b = q
            self.update()
            return
        if self._drag:
            r, _ = self._frame()
            self.line_y = float(np.clip((e.position().y() - r.y()) / max(r.height(), 1), 0.02, 0.98))
            self.update()
            return
        self.setCursor(Qt.SizeVerCursor if self._near_line(e.position()) else Qt.CrossCursor)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.line_moved.emit(self.line_y)
            return
        if e.button() != Qt.LeftButton or not self.photo or self.tool == "sam":
            return
        W, H = self.photo.width(), self.photo.height()
        if self.tool == "hand":
            self._finish_poly(smooth_points(self._pts, int(self.smooth)), "рука")
        elif self.tool == "erase" and self._pts:
            path = QPainterPath(QPointF(*self._pts[0]))
            for q in self._pts[1:] or [(self._pts[0][0] + 0.1, self._pts[0][1])]:
                path.lineTo(QPointF(*q))
            self.erase_done.emit(path_mask(path, W, H, stroke=self.brush))
            self._pts = []
        elif self.tool in SHAPES and self._a and self._b:
            a, b = QPointF(*self._a), QPointF(*self._b)
            if (b - a).manhattanLength() > 4:
                m = path_mask(shape_path(self.tool, a, b, W, H), W, H)
                if m.sum() >= 30:
                    self.shape_done.emit(m, {"rect": "▭", "ellipse": "◯", "tri": "△", "hband": "▬",
                                             "vband": "▮", "sector": "◔"}[self.tool])
            self._a = self._b = None
        elif self.tool == "horizon" and self._a and self._b:
            dx, dy = self._b[0] - self._a[0], self._b[1] - self._a[1]
            if abs(dx) > 20:
                ang = math.degrees(math.atan2(dy, dx))
                if ang > 90:
                    ang -= 180
                elif ang < -90:
                    ang += 180
                self.horizon_done.emit(-ang)          # повернуть обратно — горизонт станет ровным
            self._a = self._b = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.tool == "points" and e.button() == Qt.LeftButton:
            self._finish_poly(self._pts[:-1] if len(self._pts) > 3 else self._pts, "точки")

    def leaveEvent(self, _):
        self._hover = None
        self.update()
