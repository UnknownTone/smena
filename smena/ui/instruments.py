"""Экраны-приборы на консоли (в духе осциллографа С1-83):
  Scope   — LFO: серая рамка, экран с сеткой, вверху живые кривые четырёх LFO (каждая над своей панелью);
  EqScope — эквалайзер: экран со шкалой (сетка, риски на осях, дБ и Гц), кривая АЧХ, тонкая едва заметная кайма.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame

from smena.ui.theme import THEME

WIRE_COLORS = ["#d5e22b", "#f1d81f", "#efeedd", "#3dff7a"]


def paint_bezel(p, rect, t=9.0):
    """Серая рамка прибора и тёмный экран внутри; → прямоугольник экрана."""
    r = QRectF(rect).adjusted(1, 1, -1, -1)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#cfcdc3"))
    g.setColorAt(1, QColor("#8f8d84"))
    p.setPen(QPen(QColor("#3d3c37"), 1))
    p.setBrush(g)
    p.drawRoundedRect(r, 9, 9)
    inner = r.adjusted(t, t + 6, -t, -t)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2a2925"))
    p.drawRoundedRect(inner.adjusted(-2, -2, 2, 2), 8, 8)
    p.setBrush(QColor("#08170e"))
    p.drawRoundedRect(inner, 7, 7)
    sh = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    sh.setColorAt(0, QColor(0, 0, 0, 120))
    sh.setColorAt(0.12, QColor(0, 0, 0, 0))
    p.setBrush(sh)
    p.drawRoundedRect(inner, 7, 7)
    return inner


def graticule(p, inner, nx=10, ny=8, alpha=40):
    """Сетка экрана и риски на центральных осях."""
    grid = QColor(61, 255, 122, alpha)
    p.setPen(QPen(grid, 1))
    for i in range(1, nx):
        x = inner.left() + inner.width() * i / nx
        p.drawLine(QPointF(x, inner.top() + 2), QPointF(x, inner.bottom() - 2))
    for j in range(1, ny):
        y = inner.top() + inner.height() * j / ny
        p.drawLine(QPointF(inner.left() + 2, y), QPointF(inner.right() - 2, y))
    tick = QColor(61, 255, 122, alpha + 40)
    p.setPen(QPen(tick, 1))
    cx, cy = inner.center().x(), inner.center().y()
    for i in range(nx * 5 + 1):
        x = inner.left() + inner.width() * i / (nx * 5)
        p.drawLine(QPointF(x, cy - 2.5), QPointF(x, cy + 2.5))
    for j in range(ny * 5 + 1):
        y = inner.top() + inner.height() * j / (ny * 5)
        p.drawLine(QPointF(cx - 2.5, y), QPointF(cx + 2.5, y))


def lfo_value(wave, ph, sh):
    return (math.sin(2 * math.pi * ph) if wave == 0 else 1 - 4 * abs(ph - 0.5) if wave == 1 else
            2 * ph - 1 if wave == 2 else (1.0 if ph < 0.5 else -1.0) if wave == 3 else sh)


class Scope(QFrame):
    """Осциллограф LFO: панели LFO кладутся внутрь (layout с отступом сверху под полосу кривых)."""

    STRIP = 30

    def __init__(self, mod=None):
        super().__init__()
        self.mod = mod
        self.setObjectName("Instrument")
        self.setStyleSheet("#Instrument { background: transparent; border: none; }")
        self.setToolTip("LFO · ОСЦИЛЛОГРАФ — четыре генератора; кривая над панелью — форма и фаза. "
                        "Провод от «ВЫХ» к гнезду под любым фейдером; правый клик по гнезду — снять")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        inner = paint_bezel(p, self.rect())
        graticule(p, inner, 12, 6, 34)
        p.setFont(THEME.font("engrave", 11, bold=True))
        p.setPen(QColor("#2b2a26"))
        p.drawText(QRectF(16, 1, 300, 13), Qt.AlignLeft | Qt.AlignVCenter, "LFO · ОСЦИЛЛОГРАФ")
        strip = QRectF(inner.left() + 6, inner.top() + 4, inner.width() - 12, self.STRIP - 6)
        lfos = self.mod.lfos if self.mod else []
        cw = strip.width() / 4
        for k in range(4):
            x0 = strip.left() + k * cw + 6
            n = int(cw - 12)
            wave = int(lfos[k].k("wave")) if lfos else k
            ph0 = lfos[k].phase if lfos else 0.0
            sh = lfos[k]._sh if lfos else 0.5
            path = QPainterPath()
            for i in range(n):
                ph = (ph0 + i / n * 2.0) % 1.0                    # два цикла, бегут с фазой
                v = lfo_value(wave, ph, sh if wave == 4 else 0.0)
                if wave == 4:
                    v = math.sin(1.7 * k + math.floor(ph0 + i / n * 2.0) * 2.3)   # ступеньки S&H
                pt = QPointF(x0 + i, strip.center().y() - v * strip.height() * 0.42)
                path.lineTo(pt) if i else path.moveTo(pt)
            c = QColor(WIRE_COLORS[k])
            glow = QColor(c)
            glow.setAlpha(60)
            p.setPen(QPen(glow, 4))
            p.drawPath(path)
            p.setPen(QPen(c, 1.4))
            p.drawPath(path)
        p.end()


class EqScope(QFrame):
    """Экран эквалайзера: шкала (дБ, Гц), АЧХ по текущим полосам; фейдеры и кнопки — дочерние, поверх экрана."""

    def __init__(self, eq):
        super().__init__()
        self.eq = eq
        self.setObjectName("EqScope")
        self.setStyleSheet("#EqScope { background: transparent; border: none; }")
        self.setToolTip("ЭКВАЛАЙЗЕР — звук, который играет SMENA (режим «файл»), и звук записи REC; "
                        "на триггеры не влияет. Кривая — итоговая АЧХ")

    def response(self, n):
        lo, mid, hi = self.eq.gains
        f = np.logspace(math.log10(20), math.log10(20000), n)
        lf = np.log2(f)
        shelf = lambda f0, up: 1.0 / (1.0 + np.exp(-(lf - math.log2(f0)) * 3.0 * (1 if up else -1)))
        return lo * shelf(100.0, False) + mid * np.exp(-0.5 * ((lf - math.log2(1000.0)) / 0.8) ** 2) + \
            hi * shelf(8000.0, True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(61, 255, 122, 45), 1))               # тонкая, едва заметная кайма
        p.setBrush(QColor("#051109"))
        p.drawRoundedRect(r, 6, 6)
        g = QRectF(r.left() + 30, r.top() + 22, r.width() - 40, r.height() * 0.42)   # поле графика
        graticule(p, g, 9, 4, 36)
        p.setFont(THEME.font("screen", 9))
        dim = QColor(61, 255, 122, 120)
        p.setPen(dim)
        for db, j in ((12, 0), (0, 2), (-12, 4)):
            y = g.top() + g.height() * j / 4
            p.drawText(QRectF(r.left() + 2, y - 6, 26, 12), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")
        for hz, lab in ((100, "100"), (1000, "1к"), (8000, "8к")):
            x = g.left() + g.width() * (math.log10(hz) - math.log10(20)) / (math.log10(20000) - math.log10(20))
            p.drawText(QRectF(x - 14, g.bottom() + 1, 28, 12), Qt.AlignCenter, lab)
        p.setFont(THEME.font("screen", 10))
        p.setPen(QColor(61, 255, 122, 170))
        p.drawText(QRectF(r.left() + 8, r.top() + 3, r.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "ЭКВАЛАЙЗЕР · ВЫХОД  дБ / Гц")
        n = int(g.width())
        resp = self.response(max(n, 2))
        path = QPainterPath()
        for i, db in enumerate(resp):
            pt = QPointF(g.left() + i, g.center().y() - db / 12.0 * g.height() / 2)
            path.lineTo(pt) if i else path.moveTo(pt)
        fg = THEME.c("screen_fg")
        glow = QColor(fg)
        glow.setAlpha(70)
        p.setPen(QPen(glow, 5))
        p.drawPath(path)
        p.setPen(QPen(fg, 1.6))
        p.drawPath(path)
        p.end()


class EyeFill(QFrame):
    """Пустое место внизу вкладки: грязный, почти незаметный глаз «со дна коробки». Когда места мало
    (поднят фейдербанк) — не рисуется."""

    def __init__(self, opacity=0.045):
        super().__init__()
        self.opacity = opacity
        self._pm = None
        self.setMinimumHeight(0)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, _):
        from PySide6.QtGui import QPixmap
        if self._pm is None:
            f = THEME.textures.get("eye")
            self._pm = QPixmap(str(THEME.dir / f)) if f else QPixmap()
        if self._pm.isNull() or self.height() < 90:
            return
        p = QPainter(self)
        pm = self._pm.scaledToHeight(int(min(self.height() * 0.7, 220)), Qt.SmoothTransformation)
        if pm.width() > self.width() * 0.6:
            pm = self._pm.scaledToWidth(int(self.width() * 0.6), Qt.SmoothTransformation)
        p.setOpacity(self.opacity)
        p.drawPixmap(int((self.width() - pm.width()) / 2), int((self.height() - pm.height()) / 2), pm)
        p.setOpacity(self.opacity * 0.8)                  # грязь: тёмные пятна поверх
        rng = np.random.default_rng(3)
        for _ in range(30):
            x = int((self.width() - pm.width()) / 2 + rng.uniform(0, pm.width()))
            y = int((self.height() - pm.height()) / 2 + rng.uniform(0, pm.height()))
            r = int(rng.uniform(4, 18))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 200))
            p.drawEllipse(QPointF(x, y), r, r * 0.7)
        p.end()
