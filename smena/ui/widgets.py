"""Рисованные виджеты: фейдер, ручка, индикатор уровня, лампа, счётчик кадров, индикатор долей, развёртка.

Вариант оформления — `variant`: "body" (корпус «Смены»: гравировка на чёрном) или "screen" (люминофор Pip-Boy).
Цвета и шрифты — только из темы (THEME).
"""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QInputDialog, QWidget

from smena.ui.theme import THEME


def scheme(variant):
    """Цвета варианта: основной, приглушённый, акцент, фон дорожки."""
    if variant == "screen":
        return {"fg": THEME.c("screen_fg"), "dim": THEME.c("screen_dim"), "acc": THEME.c("screen_warn"),
                "bg": THEME.c("screen_bg"), "font": "screen"}
    return {"fg": THEME.c("engrave"), "dim": THEME.c("metal_shadow"), "acc": THEME.c("engrave_red"),
            "bg": QColor("#0a0a0a"), "font": "engrave"}


def fmt_num(v, step):
    return f"{v:.0f}" if step >= 1 else (f"{v:.2f}" if step < 0.1 else f"{v:.1f}")


# ----------------------------------------------------------------------- значения
class ValueControl(QWidget):
    """Общее для фейдера и ручки: мышь (тянуть; Shift — точно), колесо, двойной клик — по умолчанию,
    правый клик — ввод числа."""
    valueChanged = Signal(float)

    def __init__(self, lo, hi, default, step=1.0, label="", unit="", variant="body", parent=None, hint=""):
        super().__init__(parent)
        self.lo, self.hi, self.default, self.step = lo, hi, default, step
        self.label, self.unit, self.variant = label, unit, variant
        self.hint = hint              # что делает — первая строка всплывающей подсказки
        self.value = default
        self.auto_value = None        # положение, которое выставил триггер (M3); ручное — «база»
        self._drag = None
        self.setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._update_tip()

    def _update_tip(self):
        head = f"{self.label} — {self.hint}\n" if self.hint else ""
        self.setToolTip(f"{head}сейчас: {fmt_num(self.value, self.step)} {self.unit} · по умолчанию "
                        f"{fmt_num(self.default, self.step)}\n"
                        "тянуть — менять (Shift — точно) · колесо — шаг · двойной клик — по умолчанию · "
                        "правый клик — число")

    def norm(self, v=None):
        v = self.value if v is None else v
        return (v - self.lo) / ((self.hi - self.lo) or 1)

    def set_value(self, v, emit=True):
        v = min(max(v, self.lo), self.hi)
        if self.step:
            v = self.lo + round((v - self.lo) / self.step) * self.step
            v = round(v, 6)
        if v != self.value:
            self.value = v
            self._update_tip()
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def travel(self):
        return 150.0

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.position().y(), self.value)
        elif e.button() == Qt.RightButton:
            decimals = 0 if self.step >= 1 else 2
            v, ok = QInputDialog.getDouble(self, self.label or "Значение",
                                           f"{self.label} ({self.lo:g}…{self.hi:g} {self.unit})",
                                           self.value, self.lo, self.hi, decimals)
            if ok:
                self.set_value(v)

    def mouseMoveEvent(self, e):
        if self._drag:
            y0, v0 = self._drag
            k = 0.2 if e.modifiers() & Qt.ShiftModifier else 1.0
            self.set_value(v0 + (y0 - e.position().y()) / self.travel() * (self.hi - self.lo) * k)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_value(self.default)

    def wheelEvent(self, e):
        notch = max(self.step, round((self.hi - self.lo) / 40 / (self.step or 1)) * (self.step or 1))
        if e.modifiers() & Qt.ShiftModifier:
            notch = self.step or notch / 5
        d = e.angleDelta().y() / 120
        self.set_value(self.value + d * notch)


class Fader(ValueControl):
    """Вертикальный фейдер. Экран — люминофор Pip-Boy; корпус — жёлтый, как на старой приборной панели:
    риски по обе стороны, чёрная прорезь, ниже колпачка — жёлтая заливка, колпачок — краска с рифлением и ржавчиной."""

    def __init__(self, *a, marks=(), **kw):
        super().__init__(*a, **kw)
        self.marks = marks
        self.setMinimumSize(40, 90)
        self._rust = [(random.uniform(1, 21), random.choice((1.5, 13.5)), random.uniform(0.8, 1.8),
                       random.uniform(0.6, 1.2)) for _ in range(4)]

    def _track(self):
        top, bot = 10.0, self.height() - 10.0
        return top, bot

    def travel(self):
        top, bot = self._track()
        return max(bot - top, 20.0)

    def paintEvent(self, _):
        if self.variant == "screen":
            return self._paint_screen()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.3)
        top, bot = self._track()
        x = self.width() * 0.5
        yel, yel_d = THEME.c("hazard"), THEME.c("hazard_dark")
        p.setPen(QPen(yel, 1.2))                                     # риски
        for i in range(11):
            y = top + (bot - top) * i / 10
            L = 6 if i % 5 == 0 else 3.5
            p.drawLine(QPointF(x - 9 - L, y), QPointF(x - 9, y))
            p.drawLine(QPointF(x + 9, y), QPointF(x + 9 + L, y))
        p.setPen(QPen(QColor("#3b2c18"), 1.2))                       # прорезь
        p.setBrush(QColor("#030303"))
        p.drawRoundedRect(QRectF(x - 4, top - 3, 8, bot - top + 6), 4, 4)
        cy = bot - self.norm() * (bot - top)
        fill = QRectF(x - 2.5, cy, 5, bot - cy + 1)
        g = QLinearGradient(fill.topLeft(), fill.topRight())
        g.setColorAt(0, yel_d)
        g.setColorAt(0.5, yel)
        g.setColorAt(1, yel_d)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(fill, 2, 2)
        if self.auto_value is not None:                              # «призрак»: триггер / LFO
            ya = bot - self.norm(self.auto_value) * (bot - top)
            p.setBrush(QColor("#ff8a2a"))
            p.drawRect(QRectF(x - 10, ya - 1.2, 20, 2.4))
        cap = QRectF(x - 11, cy - 7.5, 22, 15)                        # колпачок
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawRoundedRect(cap.translated(1, 2), 3, 3)
        g = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        g.setColorAt(0, QColor("#f3d540"))
        g.setColorAt(0.55, QColor("#d9b61c"))
        g.setColorAt(1, QColor("#a07f0e"))
        p.setBrush(g)
        p.setPen(QPen(QColor("#4b2b10"), 1.4))
        p.drawRoundedRect(cap, 3.5, 3.5)
        p.setPen(QPen(QColor(60, 40, 10, 200), 1.2))
        for k in (-3, 0, 3):
            p.drawLine(QPointF(cap.left() + 4, cy + k), QPointF(cap.right() - 4, cy + k))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(110, 60, 25, 200))
        for rx, ry, w, h in self._rust:
            p.drawEllipse(QPointF(cap.left() + rx, cap.top() + ry), w, h)
        p.end()

    def _paint_screen(self):
        s = scheme(self.variant)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.3)
        w = self.width()
        top, bot = self._track()
        x = w * 0.62
        p.setFont(THEME.font(s["font"], 8))
        for m in self.marks:
            y = bot - self.norm(m) * (bot - top)
            p.setPen(QPen(s["dim"], 1))
            p.drawLine(QPointF(x - 9, y), QPointF(x - 5, y))
            p.setPen(s["acc"] if m == self.default else s["fg"])
            p.drawText(QRectF(0, y - 6, x - 10, 12), Qt.AlignRight | Qt.AlignVCenter, f"{m:g}")
        p.setPen(QPen(s["dim"], 1))
        p.setBrush(s["bg"])
        p.drawRoundedRect(QRectF(x - 2.5, top, 5, bot - top), 2, 2)
        p.setPen(Qt.NoPen)
        fill_y = bot - self.norm() * (bot - top)
        p.setBrush(s["dim"])
        p.drawRoundedRect(QRectF(x - 1.5, fill_y, 3, bot - fill_y), 1, 1)
        if self.auto_value is not None:
            ya = bot - self.norm(self.auto_value) * (bot - top)
            p.setBrush(s["acc"])
            p.drawRect(QRectF(x - 9, ya - 1.5, 18, 3))
        rect = QRectF(x - 9, fill_y - 6, 18, 12)
        p.setBrush(s["bg"])
        p.setPen(QPen(s["fg"], 1.5))
        p.drawRect(rect)
        p.drawLine(QPointF(rect.left() + 3, fill_y), QPointF(rect.right() - 3, fill_y))
        p.end()


class Knob(ValueControl):
    """Ручка, дуга 270°. Экран — люминофор; корпус — шлифованный металл с прорезью-указателем.
    ring=True — крупная ручка корпуса со шкалой рисок (пройденная часть — жёлтая); compact=True — подпись и
    значение справа от ручки (узкая верхняя полоса)."""

    def __init__(self, *a, size=28, ring=False, compact=False, text_w=62, lamp=False, **kw):
        super().__init__(*a, **kw)
        self.ring, self.compact, self.lamp = ring, compact, lamp
        self.d = size
        if ring and compact == "under":
            self.setFixedSize(max(size + 22, text_w), size + 24)
        elif ring and compact:
            self.setFixedSize(size + 20 + text_w, size + 20)
        elif ring:
            self.setFixedSize(max(size + 24, 64), size + 40)
        else:
            self.setFixedSize(size + 4, size + 2)

    def travel(self):
        return 120.0

    def paintEvent(self, _):
        if self.variant == "screen":
            return self._paint_screen()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        d = self.d
        if self.ring and self.compact == "under":
            c = QPointF(self.width() / 2, d / 2 + 7)
        elif self.ring and self.compact:
            c = QPointF(d / 2 + 10, self.height() / 2)
        else:
            c = QPointF(self.width() / 2, 1 + d / 2 + (6 if self.ring else 0))
        rk = d / 2 - (1 if self.ring else 0)
        a0, span = 225.0, -270.0
        if self.ring:                                                   # шкала
            n = 27
            for i in range(n):
                u = i / (n - 1)
                a = math.radians(a0 + span * u)
                long = i % 5 == 0
                r1, r2 = rk + 3, rk + (9 if long else 6)
                p.setPen(QPen(THEME.c("hazard") if u <= self.norm() + 1e-6 else QColor(235, 235, 228),
                              1.6 if long else 1.0))
                p.drawLine(QPointF(c.x() + math.cos(a) * r1, c.y() - math.sin(a) * r1),
                           QPointF(c.x() + math.cos(a) * r2, c.y() - math.sin(a) * r2))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawEllipse(c + QPointF(1.2, 1.8), rk + 1.5, rk + 1.5)
        p.setBrush(QColor("#0a0a0a"))
        p.drawEllipse(c, rk + 1.2, rk + 1.2)
        g = QConicalGradient(c, 45)                                      # шлифованный металл
        for t, v in ((0.0, 245), (0.12, 150), (0.25, 235), (0.37, 120), (0.5, 245), (0.62, 150), (0.75, 235),
                     (0.87, 120), (1.0, 245)):
            g.setColorAt(t, QColor(v, v, v - 4))
        p.setBrush(g)
        p.setPen(QPen(QColor(60, 60, 58), 1))
        p.drawEllipse(c, rk, rk)
        rg = QRadialGradient(c - QPointF(rk * 0.3, rk * 0.35), rk * 1.3)
        rg.setColorAt(0, QColor(255, 255, 255, 60))
        rg.setColorAt(1, QColor(0, 0, 0, 40))
        p.setBrush(rg)
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, rk, rk)
        a = math.radians(a0 + span * self.norm())                         # прорезь-указатель
        p.setPen(QPen(QColor(25, 25, 25), 2.0 if self.ring else 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(a) * rk * 0.35, c.y() - math.sin(a) * rk * 0.35),
                   QPointF(c.x() + math.cos(a) * rk * 0.9, c.y() - math.sin(a) * rk * 0.9))
        if self.lamp:                       # лампочка в центре: 0 — ярко-красная, больше 0 — зелёная, ярче громче
            v = self.norm()
            col = QColor(255, 40, 30) if v <= 0 else QColor(60, 255, 90, int(60 + 195 * v))
            rl = rk * 0.26
            glow = QRadialGradient(c, rl * 3.2)
            gc = QColor(col)
            gc.setAlpha(int(150 * (1.0 if v <= 0 else v)))
            glow.setColorAt(0, gc)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, rl * 3.2, rl * 3.2)
            p.setBrush(QColor("#111"))
            p.drawEllipse(c, rl + 1, rl + 1)
            p.setBrush(col)
            p.drawEllipse(c, rl, rl)
        if self.ring:
            val = f"{fmt_num(self.value, self.step)} {self.unit}".strip()
            p.setFont(THEME.font("engrave", 10, bold=True))
            if self.compact == "under":                                  # подпись и значение под ручкой
                p.setFont(THEME.font("engrave", 9, bold=True))
                p.setPen(QColor(220, 218, 205))
                p.drawText(QRectF(0, d + 12, self.width(), 10), Qt.AlignCenter, f"{self.label} {val}")
            elif self.compact:
                x0 = d + 22
                p.setPen(QColor(220, 218, 205))
                p.drawText(QRectF(x0, 0, self.width() - x0, self.height() / 2), Qt.AlignLeft | Qt.AlignBottom,
                           self.label)
                p.setPen(THEME.c("hazard"))
                p.drawText(QRectF(x0, self.height() / 2 + 1, self.width() - x0, self.height() / 2),
                           Qt.AlignLeft | Qt.AlignTop, val)
            else:
                p.setPen(QColor(220, 218, 205))
                p.drawText(QRectF(0, d + 14, self.width(), 12), Qt.AlignCenter, self.label)
                p.setPen(THEME.c("hazard"))
                p.drawText(QRectF(0, d + 25, self.width(), 12), Qt.AlignCenter, val)
        p.end()

    def _paint_screen(self):
        s = scheme(self.variant)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        d = self.d
        r = QRectF((self.width() - d) / 2, 1, d, d)
        a0, span = 225.0, -270.0
        p.setPen(QPen(s["dim"], 2))
        p.setBrush(s["bg"])
        p.drawEllipse(r.adjusted(3, 3, -3, -3))
        p.setPen(QPen(s["fg"], 2.5))
        p.drawArc(r.adjusted(1, 1, -1, -1), int(a0 * 16), int(span * self.norm() * 16))
        c = r.center()
        a = math.radians(a0 + span * self.norm())
        p.setPen(QPen(s["fg"], 2.2))
        p.drawLine(QPointF(c.x() + math.cos(a) * d * 0.12, c.y() - math.sin(a) * d * 0.12),
                   QPointF(c.x() + math.cos(a) * d * 0.36, c.y() - math.sin(a) * d * 0.36))
        p.end()


# ----------------------------------------------------------------------- индикаторы
class Meter(QWidget):
    """Вертикальный сегментный индикатор 0..1 с удержанием пика."""

    def __init__(self, variant="screen", segments=16, parent=None):
        super().__init__(parent)
        self.variant, self.segments = variant, segments
        self.value = 0.0
        self.peak = 0.0
        self._peak_t = 0.0
        self.setMinimumSize(8, 40)

    def set_value(self, v):
        v = min(max(float(v), 0.0), 1.0)
        now = time.perf_counter()
        if v >= self.peak or now - self._peak_t > 1.2:
            self.peak, self._peak_t = v, now
        if abs(v - self.value) > 1e-3:
            self.value = v
            self.update()

    def paintEvent(self, _):
        s = scheme(self.variant)
        p = QPainter(self)
        n = self.segments
        h = self.height() / n
        lit = round(self.value * n)
        pk = min(n - 1, int(self.peak * n))
        for i in range(n):
            y = self.height() - (i + 1) * h
            if i < lit:
                col = s["acc"] if i >= n * 0.85 else s["fg"]
            elif i == pk and self.peak > 0.02:
                col = s["fg"]
            else:
                col = QColor(s["dim"])
                col.setAlphaF(0.25)
            p.fillRect(QRectF(0, y + 1, self.width(), h - 1.5), col)
        p.end()


class Lamp(QWidget):
    """Лампа срабатывания: яркость = уровень; flash() — вспышка на событии."""

    def __init__(self, variant="screen", size=10, parent=None):
        super().__init__(parent)
        self.variant = variant
        self.level = 0.0
        self._flash_t = -1e9
        self.setFixedSize(size + 2, size + 2)

    def flash(self):
        self._flash_t = time.perf_counter()
        self.update()

    def set_level(self, v):
        self.level = min(max(float(v), 0.0), 1.0)
        self.update()

    def brightness(self):
        f = max(0.0, 1.0 - (time.perf_counter() - self._flash_t) / 0.3)
        return max(self.level, f)

    def paintEvent(self, _):
        s = scheme(self.variant)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.brightness()
        col = QColor(s["acc"] if self.variant == "body" else s["fg"])
        off = QColor(s["dim"])
        off.setAlphaF(0.35)
        p.setPen(QPen(s["dim"], 1))
        p.setBrush(off)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.drawEllipse(r)
        if b > 0.02:
            col.setAlphaF(0.25 + 0.75 * b)
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(r)
        p.end()


class FrameCounter(QWidget):
    """Счётчик кадров: номер master-фото / всего — зелёный индикатор."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current, self.total = None, 0
        self.setFixedSize(132, 40)
        self.setToolTip("СЧЁТЧИК КАДРОВ — номер текущего фото / всего в папке")

    def set(self, current, total):
        self.current, self.total = current, total
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        win = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(THEME.c("screen_bg"))
        p.setPen(QPen(QColor("#0d3a1c"), 1))
        p.drawRoundedRect(win, 3, 3)
        cur = "—" if self.current is None else f"{self.current:03d}"
        p.setFont(THEME.font("digits", 30))
        p.setPen(THEME.c("screen_fg"))
        p.drawText(win.adjusted(0, 0, -win.width() / 2 - 6, 0), Qt.AlignRight | Qt.AlignVCenter, cur)
        p.setPen(THEME.c("screen_dim"))
        p.drawText(win, Qt.AlignCenter, "/")
        p.setPen(THEME.c("screen_fg"))
        p.drawText(win.adjusted(win.width() / 2 + 6, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, f"{self.total:03d}")
        p.end()


class BeatIndicator(QWidget):
    """Доли такта ▮▮▯▯: текущая доля горит, первая — акцентом; вспышка в начале доли."""

    def __init__(self, variant="screen", parent=None):
        super().__init__(parent)
        self.variant = variant
        self.in_bar, self.phase, self.conditional = 0, 0.0, False
        self.setFixedSize(92, 18)

    def set(self, in_bar, phase, conditional):
        self.in_bar, self.phase, self.conditional = in_bar, phase, conditional
        self.update()

    def paintEvent(self, _):
        s = scheme(self.variant)
        p = QPainter(self)
        w = (self.width() - 3 * 4) / 4
        for i in range(4):
            r = QRectF(i * (w + 4), 2, w, self.height() - 4)
            if i <= self.in_bar:
                col = QColor(s["acc"] if i == 0 else s["fg"])
                if i == self.in_bar:
                    col.setAlphaF(1.0 - 0.6 * self.phase)
                if self.conditional:
                    col = QColor(s["dim"])
            else:
                col = QColor(s["dim"])
                col.setAlphaF(0.25)
            p.fillRect(r, col)
        p.end()


class Scanlines(QWidget):
    """Строки развёртки и свечение экрана Pip-Boy поверх содержимого (мышь проходит насквозь)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        parent.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Resize:
            self.setGeometry(obj.rect())
            self.raise_()
        return False

    def paintEvent(self, _):
        a = float(THEME.effects.get("scanlines", 0.2))
        glow = float(THEME.effects.get("glow", 0.5))
        p = QPainter(self)
        line = QColor(0, 0, 0)
        line.setAlphaF(a)
        for y in range(0, self.height(), 3):
            p.fillRect(0, y, self.width(), 1, line)
        if glow > 0:
            # мягкое свечение у краёв стекла
            g = QLinearGradient(0, 0, 0, self.height())
            edge = THEME.c("screen_fg", 0.06 * glow)
            g.setColorAt(0, edge)
            g.setColorAt(0.12, QColor(0, 0, 0, 0))
            g.setColorAt(0.88, QColor(0, 0, 0, 0))
            g.setColorAt(1, edge)
            p.fillRect(self.rect(), g)
        p.end()


class Jack(QWidget):
    """Гнездо для провода LFO: выход LFO (out=True) или вход фейдера. Провода рисует PatchLayer вкладки ФЕЙДЕРЫ,
    перетаскивание — через patch (begin / drag / end); правый клик — снять провода с гнезда."""

    def __init__(self, patch, key, out=False, parent=None):
        super().__init__(parent)
        self.patch, self.key, self.out = patch, key, out
        self.setFixedSize(16, 16)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("выход LFO — тяните провод к гнезду под фейдером" if out else
                        "гнездо модуляции — сюда тянут провод от выхода LFO; правый клик — снять провода")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        busy = self.patch.busy(self)
        col = THEME.c("accent") if (self.out or busy) else THEME.c("screen_dim")
        p.setPen(QPen(col, 2))
        p.setBrush(QColor("#000"))
        p.drawEllipse(QRectF(2, 2, 12, 12))
        if busy or self.out:
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(6, 6, 4, 4))
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.patch.begin(self, e.globalPosition())
        elif e.button() == Qt.RightButton:
            self.patch.unplug(self)

    def mouseMoveEvent(self, e):
        self.patch.drag(e.globalPosition())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.patch.end(e.globalPosition())


class PlateButton(QWidget):
    """Кнопка-плашка по эскизу автора (пиксель-арт): тёмная панель, металлическая рамка со срезанными углами
    и ржавчиной, тонкая жёлтая линия внутри. Внутри — значок (▶ ■ ▶▶|) или текст; lamp=True — лампочка слева
    (горит, когда кнопка включена). checkable — как тогл."""
    clicked = Signal()
    toggled = Signal(bool)

    def __init__(self, icon="play", text="", w=64, h=34, checkable=False, lamp=False, lamp_color="#ff3b2a",
                 parent=None):
        super().__init__(parent)
        self.icon, self.text, self.checkable, self.lamp = icon, text, checkable, lamp
        self.lamp_color = QColor(lamp_color)
        self.checked = False
        self._down = False
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        rng = random.Random(hash((icon, text, w)) & 0xFFFF)
        self._rust = [(rng.random(), rng.random() < 0.5, rng.uniform(3, 9)) for _ in range(7)]

    def isChecked(self):
        return self.checked

    def setChecked(self, on):
        if on != self.checked:
            self.checked = on
            self.update()
            self.toggled.emit(on)

    def toggle(self):
        self.setChecked(not self.checked)

    def setText(self, t):
        self.text = t
        self.update()

    def setIcon(self, icon):
        self.icon = icon
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            if self.rect().contains(e.position().toPoint()):
                if self.checkable:
                    self.toggle()
                self.clicked.emit()
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        W, H = self.width(), self.height()
        c = 4                                            # срез угла
        dy = 1 if self._down else 0

        def chamfer(r, k):
            from PySide6.QtGui import QPolygonF
            return QPolygonF([QPointF(r.left() + k, r.top()), QPointF(r.right() - k, r.top()),
                              QPointF(r.right(), r.top() + k), QPointF(r.right(), r.bottom() - k),
                              QPointF(r.right() - k, r.bottom()), QPointF(r.left() + k, r.bottom()),
                              QPointF(r.left(), r.bottom() - k), QPointF(r.left(), r.top() + k)])
        outer = QRectF(0.5, 0.5, W - 1, H - 1)
        p.setPen(QPen(QColor("#0b0b09"), 1))
        g = QLinearGradient(outer.topLeft(), outer.bottomLeft())
        g.setColorAt(0, QColor("#9aa39c"))
        g.setColorAt(0.5, QColor("#6f7872"))
        g.setColorAt(1, QColor("#545c57"))
        p.setBrush(g)
        p.drawPolygon(chamfer(outer, c))
        p.setPen(Qt.NoPen)                               # ржавчина и бирюза на металле рамки
        for t, top, L in self._rust:
            x = 4 + t * (W - 8 - L)
            y = 1.5 if top else H - 3.5
            p.setBrush(QColor(150, 75, 30, 200) if L > 5 else QColor(90, 150, 140, 170))
            p.drawRect(QRectF(x, y, L, 2))
        inner = QRectF(3.5, 3.5, W - 7, H - 7)
        p.setPen(QPen(QColor("#050504"), 1))
        g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
        g.setColorAt(0, QColor("#22211a") if not self._down else QColor("#141310"))
        g.setColorAt(1, QColor("#121109"))
        p.setBrush(g)
        p.drawPolygon(chamfer(inner, c - 1))
        line = THEME.c("hazard")
        line.setAlpha(230 if self.checked else 130)
        p.setPen(QPen(line, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(chamfer(inner.adjusted(3, 3, -3, -3), 2))
        yel = QColor("#fff200") if (self.checked or not self.checkable) else QColor("#a39a20")
        cx, cy = W / 2, H / 2 + dy
        p.setPen(Qt.NoPen)
        p.setBrush(yel)
        s = min(H * 0.34, 9)
        from PySide6.QtGui import QPolygonF
        if self.icon == "play":
            p.drawPolygon(QPolygonF([QPointF(cx - s * 0.75, cy - s), QPointF(cx + s * 0.95, cy),
                                     QPointF(cx - s * 0.75, cy + s)]))
        elif self.icon == "stop":
            p.drawRect(QRectF(cx - s * 0.8, cy - s * 0.8, s * 1.6, s * 1.6))
        elif self.icon == "next":                        # ▶▶|
            for k in (-1, 0):
                x0 = cx + k * s * 1.05 - s * 0.35
                p.drawPolygon(QPolygonF([QPointF(x0 - s * 0.5, cy - s * 0.8), QPointF(x0 + s * 0.55, cy),
                                         QPointF(x0 - s * 0.5, cy + s * 0.8)]))
            p.drawRect(QRectF(cx + s * 0.45, cy - s * 0.8, s * 0.3, s * 1.6))
        elif self.icon in ("down", "up"):                # стрелка шторки
            k = 1 if self.icon == "down" else -1
            p.drawPolygon(QPolygonF([QPointF(cx - s * 1.0, cy - k * s * 0.45), QPointF(cx + s * 1.0, cy - k * s * 0.45),
                                     QPointF(cx, cy + k * s * 0.6)]))
        elif self.icon == "first":                       # |◀◀
            p.drawRect(QRectF(cx - s * 1.25, cy - s * 0.8, s * 0.3, s * 1.6))
            for k in (0, 1):
                x0 = cx - s * 0.35 + k * s * 1.05
                p.drawPolygon(QPolygonF([QPointF(x0 + s * 0.5, cy - s * 0.8), QPointF(x0 - s * 0.55, cy),
                                         QPointF(x0 + s * 0.5, cy + s * 0.8)]))
        tx = 0.0
        if self.lamp:                                    # лампочка
            lx, r = 13.0, 4.0
            on = self.checked
            col = QColor(self.lamp_color) if on else QColor("#3a1410")
            if on:
                glow = QRadialGradient(QPointF(lx, cy), r * 3)
                gc = QColor(self.lamp_color)
                gc.setAlpha(120)
                glow.setColorAt(0, gc)
                glow.setColorAt(1, QColor(0, 0, 0, 0))
                p.setBrush(glow)
                p.drawEllipse(QPointF(lx, cy), r * 3, r * 3)
            p.setBrush(col)
            p.setPen(QPen(QColor("#000"), 1))
            p.drawEllipse(QPointF(lx, cy), r, r)
            if on:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 150))
                p.drawEllipse(QPointF(lx - 1.2, cy - 1.2), 1.2, 1.2)
            tx = 10.0
        if self.text:
            f = THEME.font("engrave", 14, bold=True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
            p.setFont(f)
            p.setPen(yel)
            p.drawText(QRectF(tx, dy, W - tx, H), Qt.AlignCenter, self.text)
        p.end()
