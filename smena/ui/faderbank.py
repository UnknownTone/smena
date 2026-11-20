"""Фейдербанки (02_UI_DESIGN.md §6), каждый под своей крышкой: левый — каналы 20 триггеров (под видоискателем),
правый — глобальные фейдеры (под консолью). Между ними — плашка: ut2, SMENA · ЛОМО · VJ, СБРОС и RANDOM.
Под каждым фейдером — гнездо для провода LFO. Значения — в Params (сигнал changed); те же каналы правит
таблица триггеров на вкладке ПРЕСЕТЫ.
"""
import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from smena.triggers_table import BANK_SKIP, GAIN_RANGE, GLOBALS, SENS_RANGE, TRIGGERS
from smena.ui.theme import THEME
from smena.ui.widgets import Fader, Jack, Knob, Lamp, Meter


def _label(text, role, align=Qt.AlignCenter):
    lb = QLabel(text)
    lb.setProperty("role", role)
    lb.setAlignment(align)
    return lb


class TriggerChannel(QFrame):
    manual = Signal(int)      # ручной запуск ▶

    def __init__(self, trig, params, variant="body", width=58, patch=None):
        super().__init__()
        self.t, self.params, self.variant = trig, params, variant
        self.setFixedWidth(width)
        self.setToolTip(f"№{trig.n} {trig.short} — {trig.name}\n{trig.kind}: {trig.action}")
        role = "engrave" if variant == "body" else ""
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(3)
        v.addWidget(_label(f"{trig.n:02d}", "engrave_red" if variant == "body" else "dim"))
        v.addWidget(_label(trig.short, role))

        row = QHBoxLayout()
        row.setSpacing(4)
        self.lamp = Lamp(variant, 9)
        self.lamp.setToolTip("лампа — срабатывание триггера")
        self.meter = Meter(variant, 10)
        self.meter.setToolTip(f"уровень признака: {trig.name}")
        self.meter.setFixedSize(6, 34)
        row.addStretch()
        row.addWidget(self.lamp, 0, Qt.AlignTop)
        row.addWidget(self.meter)
        row.addStretch()
        v.addLayout(row)

        n = trig.n
        self.gain = Fader(*GAIN_RANGE, 100.0, 1.0, label=f"№{n} {trig.short} · СИЛА", unit="%", variant=variant,
                          marks=(0, 100, 200), hint=f"сила действия: {trig.action}")
        v.addWidget(self.gain, 1)
        self.jack = Jack(patch, f"t{trig.n}.gain") if patch else None
        if self.jack:
            patch.register(self.jack)
            v.addWidget(self.jack, 0, Qt.AlignHCenter)
        row2 = QHBoxLayout()
        row2.setSpacing(2)
        self.sens = Knob(*SENS_RANGE, 100.0, 1.0, label=f"№{n} {trig.short} · ЧУВСТВ.", unit="%", variant=variant,
                         size=24, hint=f"чувствительность — порог срабатывания по признаку «{trig.name}»; "
                                       "больше — срабатывает чаще")
        row2.addWidget(self.sens)
        self.play = QPushButton("▶")
        self.play.setToolTip(f"▶ запустить действие №{n} вручную: {trig.action}")
        self.play.setFixedSize(22, 22)
        self.play.setEnabled(trig.manual)
        if not trig.manual:
            self.play.setText("·")
        row2.addWidget(self.play)
        v.addLayout(row2)

        self.on = QPushButton("ВКЛ")
        self.on.setCheckable(True)
        self.on.setToolTip(f"ВКЛ / ВЫКЛ триггер №{n} {trig.short}")
        self.on.setFixedHeight(22)
        v.addWidget(self.on)
        for b in (self.on, self.play):
            b.setStyleSheet("padding: 0px;")

        self.gain.valueChanged.connect(lambda x: params.set(f"t{n}.gain", x))
        self.sens.valueChanged.connect(lambda x: params.set(f"t{n}.sens", x))
        self.on.toggled.connect(lambda x: params.set(f"t{n}.on", x))
        self.play.clicked.connect(self._manual)
        params.changed.connect(self._sync)
        self.refresh()

    def _manual(self):
        self.lamp.flash()
        self.manual.emit(self.t.n)

    def refresh(self):
        n = self.t.n
        self.gain.set_value(self.params[f"t{n}.gain"], emit=False)
        self.sens.set_value(self.params[f"t{n}.sens"], emit=False)
        self.on.blockSignals(True)
        self.on.setChecked(bool(self.params[f"t{n}.on"]))
        self.on.setText("ВКЛ" if self.on.isChecked() else "ВЫКЛ")
        self.on.blockSignals(False)

    def _sync(self, key):
        if key.startswith(f"t{self.t.n}."):
            self.refresh()


class GlobalChannel(QFrame):
    news = Signal()

    def __init__(self, g, params, variant="body", width=58, patch=None):
        super().__init__()
        self.g, self.params = g, params
        self.setFixedWidth(width)
        self.setToolTip(f"{g.label} — {g.hint}\nпо умолчанию {g.default:g} {g.unit}")
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(3)
        v.addWidget(_label(g.label, "engrave" if variant == "body" else "title"))
        self.val = _label("", "engrave_red" if variant == "body" else "dim")
        v.addWidget(self.val)
        self.fader = Fader(g.lo, g.hi, g.default, g.step, label=g.label, unit=g.unit, variant=variant,
                           marks=g.marks, hint=g.hint)
        v.addWidget(self.fader, 1)
        self.jack = Jack(patch, g.key) if patch else None
        if self.jack:
            patch.register(self.jack)
            v.addWidget(self.jack, 0, Qt.AlignHCenter)
        v.addWidget(_label(g.unit or " ", "engrave" if variant == "body" else "dim"))

        self.fader.valueChanged.connect(lambda x: params.set(g.key, x))
        params.changed.connect(lambda k: k == g.key and self.refresh())
        self.refresh()

    def refresh(self):
        x = self.params[self.g.key]
        self.fader.set_value(x, emit=False)
        if self.g.key == "spread":
            self.val.setText(f"{1 - x:.2f}–{1 + x:.2f}")
        else:
            self.val.setText(f"{x:g}" if self.g.step < 1 else f"{x:.0f}")


class Strip(QScrollArea):
    """Лента каналов с горизонтальной прокруткой."""

    def __init__(self, widgets):
        super().__init__()
        self.setObjectName("FaderBank")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        h = QHBoxLayout(inner)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(0)
        for w in widgets:                              # каналы ровно по всей ширине (прокрутка — если не влезают)
            h.addStretch(1)
            h.addWidget(w)
        h.addStretch(1)
        self.setWidget(inner)


class VText(QWidget):
    """Гравировка вертикально (снизу вверх)."""

    def __init__(self, text, px, role_color, spacing=4):
        super().__init__()
        self.text, self.px, self.color, self.spacing = text, px, role_color, spacing
        f = THEME.font("engrave", px, bold=True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        self.f = f
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        self.setFixedSize(fm.height() + 2, fm.horizontalAdvance(text) + 6)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self.f)
        p.setPen(THEME.c(self.color))
        p.translate(0, self.height())
        p.rotate(-90)
        p.drawText(QRectF(0, 0, self.height(), self.width()), Qt.AlignCenter, self.text)
        p.end()


class Plate(QFrame):
    """Плашка у правого края левого банка: СБРОС и RANDOM друг над другом (действуют на оба банка)."""

    def __init__(self, params):
        super().__init__()
        self.setObjectName("Plate")
        self.setFixedWidth(64)
        pv = QVBoxLayout(self)
        pv.setContentsMargins(8, 0, 0, 0)
        pv.setSpacing(8)
        pv.addStretch()
        self.reset_btn = QPushButton("↺" + chr(10) + "СБРОС")
        self.reset_btn.setToolTip("СБРОС — все каналы и глобальные фейдеры обоих банков — по умолчанию (Ctrl+Z — отмена)")
        self.reset_btn.clicked.connect(params.reset_bank)
        self.rnd_btn = QPushButton("⚄" + chr(10) + "RND")
        self.rnd_btn.setToolTip("RANDOM — случайный набор ручек обоих банков, каждый раз новый (в разумных пределах). "
                                "Понравилось — SAVE. Ctrl+Z — отмена")
        self.rnd_btn.clicked.connect(params.randomize_bank)
        for b in (self.reset_btn, self.rnd_btn):
            b.setFixedSize(50, 46)
            b.setStyleSheet("padding: 2px; font-size: 11px;")
            pv.addWidget(b, 0, Qt.AlignHCenter)
        pv.addStretch()


def paint_plate(w, e):
    """Плита банка: чёрный потёртый металл, жёлтая обводка, «зебра» по краям, ржавые винты в углах."""
    QFrame.paintEvent(w, e)
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(w.rect()).adjusted(1, 1, -1, -1)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor("#1a1915"))
    g.setColorAt(1, QColor("#0c0b09"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(r, 4, 4)
    rng = random.Random(5)
    for _ in range(int(r.width() * r.height() / 2500)):              # потёртости
        x0, y0 = rng.uniform(r.left(), r.right()), rng.uniform(r.top(), r.bottom())
        a = rng.uniform(0, math.pi)
        L = rng.uniform(6, 40)
        p.setPen(QPen(QColor(200, 190, 160, rng.randint(8, 22)), 0.8))
        p.drawLine(QPointF(x0, y0), QPointF(x0 + math.cos(a) * L, y0 + math.sin(a) * L))
    inner = r.adjusted(12, 8, -12, -8)
    yel = THEME.c("hazard")
    pin = QColor(yel)
    pin.setAlpha(170)
    p.setPen(QPen(pin, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(inner, 6, 6)
    zeb = QColor(yel)
    zeb.setAlpha(200)
    for xs in (inner.left() + 4, inner.right() - 12):
        p.save()
        p.setClipRect(QRectF(xs, inner.top() + 14, 8, inner.height() - 28))
        p.setPen(Qt.NoPen)
        p.setBrush(zeb)
        y = inner.top() + 14
        while y < inner.bottom():
            p.drawPolygon(QPolygonF([QPointF(xs, y), QPointF(xs + 8, y - 8), QPointF(xs + 8, y - 2),
                                     QPointF(xs, y + 6)]))
            y += 16
        p.restore()
    for cx, cy in ((r.left() + 8, r.top() + 8), (r.right() - 8, r.top() + 8),
                   (r.left() + 8, r.bottom() - 8), (r.right() - 8, r.bottom() - 8)):
        rg = QRadialGradient(QPointF(cx - 1, cy - 1), 5)
        rg.setColorAt(0, QColor("#8a5a34"))
        rg.setColorAt(1, QColor("#3a2210"))
        p.setPen(QPen(QColor("#1a0e05"), 0.8))
        p.setBrush(rg)
        p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        p.setPen(QPen(QColor("#1a0e05"), 1.1))
        p.drawLine(QPointF(cx - 2.5, cy), QPointF(cx + 2.5, cy))
        p.drawLine(QPointF(cx, cy - 2.5), QPointF(cx, cy + 2.5))
    p.end()


class TriggerBank(QFrame):
    """Левый банк: 20 каналов триггеров + плашка справа (между банками)."""
    manual = Signal(int)

    def __init__(self, params, patch):
        super().__init__()
        self.setObjectName("Bank")
        self.setAttribute(Qt.WA_StyledBackground)
        h = QHBoxLayout(self)
        h.setContentsMargins(20, 12, 20, 12)
        h.setSpacing(6)
        self.channels = {}
        for t in TRIGGERS:
            ch = TriggerChannel(t, params, "body", width=50, patch=patch)
            ch.manual.connect(self.manual)
            self.channels[t.n] = ch
        h.addWidget(Strip(list(self.channels.values())), 1)
        self.plate = Plate(params)
        h.addWidget(self.plate)

    def paintEvent(self, e):
        paint_plate(self, e)


class GlobalBank(QFrame):
    """Правый банк: глобальные фейдеры."""
    news = Signal()

    def __init__(self, params, patch):
        super().__init__()
        self.setObjectName("Bank")
        self.setAttribute(Qt.WA_StyledBackground)
        h = QHBoxLayout(self)
        h.setContentsMargins(20, 12, 20, 12)
        self.globals = {}
        for g in GLOBALS:
            if g.key in BANK_SKIP:                      # СДВИГ и FX — ручки наверху
                continue
            ch = GlobalChannel(g, params, "body", width=52, patch=patch)
            ch.news.connect(self.news)
            self.globals[g.key] = ch
        h.addWidget(Strip(list(self.globals.values())), 1)

    def paintEvent(self, e):
        paint_plate(self, e)
