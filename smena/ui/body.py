"""Корпус SMENA: старая жестяная коробка из-под леденцов (текстура темы `tin`), под видоискатель и консоль —
грубо вырезанные отверстия с ржавой кромкой; крышка левого фейдербанка с хромированной надписью «Смена»
(рукописная, с длинным росчерком снизу — в духе шильдика «Жигули»).
"""
import hashlib
import json
import logging
import math
import random
from pathlib import Path

from PySide6.QtCore import QPointF, QProcess, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QWidget

from smena.runtime import script_cmd, shell_available
from smena.settings import DATA_DIR, ROOT
from smena.ui.theme import THEME

log = logging.getLogger("smena.body")
SHELL_DIR = DATA_DIR / "shell"
SHELL_SCRIPT = ROOT / "tools" / "render" / "tin_shell.py"

RUST_DARK = QColor("#3a1d0c")
RUST = QColor("#7d4320")
RUST_LIGHT = QColor("#b0703c")
BLOCK_FONTS = ("Impact", "Bahnschrift", "Arial Black")


def jagged(rect, seed, margin=5, step=7, amp=3.2):
    """Контур отверстия «как вырезано ножницами по жести»: прямоугольник чуть больше виджета с неровным краем."""
    r = rect.adjusted(-margin, -margin, margin, margin)
    rng = random.Random(seed)
    pts = []

    def side(p0, p1, nx, ny):
        n = max(2, int(math.dist((p0.x(), p0.y()), (p1.x(), p1.y())) / step))
        for i in range(n):
            t = i / n
            j = rng.uniform(-amp, amp) + (rng.random() < 0.08) * rng.uniform(3, 9)   # рваные заусенцы
            pts.append(QPointF(p0.x() + (p1.x() - p0.x()) * t + nx * j, p0.y() + (p1.y() - p0.y()) * t + ny * j))
    side(r.topLeft(), r.topRight(), 0, -1)
    side(r.topRight(), r.bottomRight(), 1, 0)
    side(r.bottomRight(), r.bottomLeft(), 0, 1)
    side(r.bottomLeft(), r.topLeft(), -1, 0)
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


class TinBody(QWidget):
    """Центральный виджет окна: старая бирюзовая жесть с вырезами под панели.

    Настоящий корпус (вмятины, эмаль, ржавчина, рваная жесть, серые окантовки) рисует tools/render/tin_shell.py
    процессом .venv-prep в фоне — по размеру окна и положению панелей; результат кешируется в
    %APPDATA%\\SMENA\\shell. Пока он готовится (или нет .venv-prep) — простой вариант на текстуре."""

    def __init__(self, prep_python=None):
        super().__init__()
        self.setObjectName("Body")
        self.holes = []
        self._tex = None
        self._cache = None             # простой фон (текстура + вырезы) — пока нет настоящего
        self._key = None
        self.prep_python = prep_python
        self.shell = None              # QPixmap настоящего корпуса для текущей геометрии
        self._shell_key = None
        self._proc = None
        self._want = None
        self._timer = QTimer(self, singleShot=True, interval=600, timeout=self._render_shell)

    def add_hole(self, *widgets):
        """Отверстие под один или несколько виджетов (по их общему прямоугольнику — видимых)."""
        self.holes.append(widgets)

    def _rect(self, ws):
        r = QRectF()
        for w in ws:
            if w.isVisible():
                r = r.united(QRectF(w.mapTo(self, w.rect().topLeft()), w.size()))
        return r

    def _geometry_key(self):
        return (self.size().toTuple(),) + tuple(self._rect(ws).getRect() for ws in self.holes)

    def paintEvent(self, e):
        key = self._geometry_key()
        if key != self._shell_key:
            self._request_shell(key)
        p = QPainter(self)
        r = e.rect()
        if self.shell is not None and self.shell.size() == self.size():
            p.drawPixmap(r, self.shell, r)
        else:
            if key != self._key or self._cache is None:
                self._key = key
                self._cache = QPixmap(self.size())
                self._render(QPainter(self._cache))
            p.drawPixmap(r, self._cache, r)
        p.end()

    # ------------------------------------------------------------- настоящий корпус
    def _rects(self):
        out = {}
        for i, ws in enumerate(self.holes):
            r = self._rect(ws)
            if not r.isEmpty():
                out[f"h{i}"] = [r.left(), r.top(), r.right(), r.bottom()]
        return out

    def _request_shell(self, key):
        """Корпус под новую геометрию: из кеша — сразу, иначе — фоновый рендер (с задержкой, пока окно тянут)."""
        self._shell_key = key
        rects = self._rects()
        sig = hashlib.md5(json.dumps([self.width(), self.height(), rects]).encode()).hexdigest()[:16]
        f = SHELL_DIR / f"{sig}.png"
        if f.is_file():
            pm = QPixmap(str(f))
            if not pm.isNull():
                self.shell = pm
                return
        self._want = (sig, rects, self.width(), self.height())
        self._timer.start()

    def _render_shell(self):
        if not self._want or not shell_available(self.prep_python) or not SHELL_SCRIPT.is_file():
            return
        if self._proc is not None:                       # рендер уже идёт — повторим после него
            self._timer.start()
            return
        sig, rects, W, H = self._want
        self._want = None
        SHELL_DIR.mkdir(parents=True, exist_ok=True)
        rj = SHELL_DIR / f"{sig}.json"
        rj.write_text(json.dumps({"rects": rects}), encoding="utf-8")
        out = SHELL_DIR / f"{sig}.png"
        proc = QProcess(self)
        proc.finished.connect(lambda code, _st, out=out, rj=rj: self._shell_done(code, out, rj))
        self._proc = proc
        proc.start(*script_cmd(self.prep_python, SHELL_SCRIPT, ["shell", W, H, rj, out], light=True))

    def _shell_done(self, code, out, rj):
        self._proc = None
        rj.unlink(missing_ok=True)
        if code == 0 and out.is_file():
            key = self._geometry_key()
            sig = out.stem
            cur = hashlib.md5(json.dumps([self.width(), self.height(), self._rects()]).encode()).hexdigest()[:16]
            if sig == cur:
                self.shell = QPixmap(str(out))
                self._shell_key = key
                self.update()
        else:
            log.warning("корпус не отрисован (код %s)", code)
        if self._want:
            self._timer.start()

    def _render(self, p):
        if self._tex is None:
            tex = THEME.textures.get("tin")
            self._tex = QPixmap(str(THEME.dir / tex)) if tex else QPixmap()
        if not self._tex.isNull():
            p.drawTiledPixmap(self.rect(), self._tex)
        else:
            p.fillRect(self.rect(), THEME.c("body"))
        # лёгкая виньетка — коробка старая, края темнее
        g = QRadialGradient(QPointF(self.width() / 2, self.height() / 2), max(self.width(), self.height()) * 0.75)
        g.setColorAt(0.55, QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.fillRect(self.rect(), g)
        p.setRenderHint(QPainter.Antialiasing)
        for i, ws in enumerate(self.holes):
            r = self._rect(ws)
            if r.isEmpty():
                continue
            self._torn(p, r, seed=i * 101 + 7)
        p.end()

    @staticmethod
    def _torn(p, r, seed):
        """Рваный вырез в жести: рыжий ореол ржавчины по краске, загнутая серебристая кромка в ржавых пятнах,
        тёмная глубина (как жесть, вскрытая ножом)."""
        rng = random.Random(seed)
        path = jagged(r, seed)
        halo = QColor(RUST)
        for k in range(6):                                              # ржавчина въелась в краску вокруг
            halo.setAlpha(34)
            p.setPen(QPen(halo, 22 - k * 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path.translated(rng.uniform(-2, 2), rng.uniform(-2, 2)))
        p.fillPath(path.translated(3, 4), QColor(0, 0, 0, 120))           # тень
        p.fillPath(path, QColor("#060605"))                               # глубина
        g = QLinearGradient(r.topLeft(), r.bottomRight())                 # загнутая кромка — светлая жесть
        g.setColorAt(0.0, QColor("#d9d6cb"))
        g.setColorAt(0.5, QColor("#8f8b80"))
        g.setColorAt(1.0, QColor("#c4c0b4"))
        p.setPen(QPen(QBrush(g), 5.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        pen = QPen(RUST, 3.2, Qt.CustomDashLine, Qt.RoundCap)             # ржавые пятна на кромке
        pen.setDashPattern([rng.uniform(1, 6) for _ in range(40)])
        p.setPen(pen)
        p.drawPath(path)
        p.setPen(QPen(QColor(40, 18, 6, 200), 1.2))                       # тёмный край среза
        p.drawPath(path.translated(1.2, 1.4))
        p.setPen(QPen(QColor(255, 255, 250, 110), 0.8))                   # блик
        p.drawPath(path.translated(-1.0, -1.2))

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)


class Lid(QWidget):
    """Крышка левого фейдербанка: тёмная пластина, ut2 и хромированная «Смена»; клик — открыть / закрыть."""
    clicked = Signal()

    def __init__(self, text="СМЕНА", sub="ТРИГГЕРЫ 1–20", version=""):
        super().__init__()
        self.text, self.sub, self.version = text, sub, version
        self.open = False
        self.setFixedHeight(54)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("крышка левого фейдербанка (триггеры 01–20) — нажмите, чтобы открыть / закрыть (клавиша B)")
        logo = THEME.textures.get("logo")
        self.logo = QPixmap(str(THEME.dir / logo)) if logo else QPixmap()
        family = next((f for f in BLOCK_FONTS if QFont(f).exactMatch()), BLOCK_FONTS[-1])
        self.font = QFont(family)
        self.font.setPixelSize(38)
        self.font.setLetterSpacing(QFont.AbsoluteSpacing, 5)

    def set_open(self, on):
        self.open = on
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def _chrome(self, path, top, bottom):
        g = QLinearGradient(0, top, 0, bottom)
        g.setColorAt(0.00, QColor("#ffffff"))
        g.setColorAt(0.30, QColor("#cfd5d9"))
        g.setColorAt(0.49, QColor("#f4f6f7"))
        g.setColorAt(0.51, QColor("#2b2f33"))
        g.setColorAt(0.72, QColor("#7f878d"))
        g.setColorAt(1.00, QColor("#e8ecef"))
        return QBrush(g)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        # пластина крышки: тёмный металл с бликом, ржавая окантовка, заклёпки
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor("#2a2a24"))
        g.setColorAt(0.45, QColor("#16150f"))
        g.setColorAt(1, QColor("#0b0a07"))
        p.setPen(QPen(RUST, 1.5))
        p.setBrush(g)
        p.drawRoundedRect(r, 5, 5)
        for x in (r.left() + 10, r.right() - 10):
            rg = QRadialGradient(QPointF(x - 1, r.center().y() - 1), 4)
            rg.setColorAt(0, QColor("#c9c4b0"))
            rg.setColorAt(1, QColor("#3b3a30"))
            p.setPen(QPen(QColor("#000"), 0.8))
            p.setBrush(rg)
            p.drawEllipse(QPointF(x, r.center().y()), 3.5, 3.5)
        x = r.left() + 24
        if not self.logo.isNull():
            pm = self.logo.scaledToHeight(int(r.height() - 10), Qt.SmoothTransformation)
            p.drawPixmap(int(x), int(r.top() + 5), pm)
            x += pm.width() + 14
        # «СМЕНА»: грубые рубленые буквы, хром, с зарубками — как штамп по металлу
        path = QPainterPath()
        base = r.center().y() + 14
        path.addText(QPointF(x + 6, base), self.font, self.text)
        b = path.boundingRect()
        rng = random.Random(17)
        cuts = QPainterPath()
        for _ in range(26):                                   # зарубки по краям букв
            cx, cy = rng.uniform(b.left(), b.right()), rng.choice((b.top(), b.bottom())) + rng.uniform(-2, 2)
            w, h = rng.uniform(2, 6), rng.uniform(1.5, 4)
            poly = QPolygonF([QPointF(cx, cy), QPointF(cx + w, cy + rng.uniform(-1, 1)), QPointF(cx + w / 2, cy + h)])
            cuts.addPolygon(poly)
        cuts.addRect(QRectF(b.left(), b.center().y() + 1, b.width(), 1.4))   # тонкий рубец посередине
        full = path.subtracted(cuts)
        x1 = b.right() + 30
        top, bottom = b.top(), b.bottom()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))                      # тень
        p.drawPath(full.translated(2.5, 3))
        p.setBrush(self._chrome(full, top, bottom))
        p.setPen(QPen(QColor("#0d0e0f"), 1.1))
        p.drawPath(full)
        p.setPen(QPen(QColor(255, 255, 255, 120), 0.7))       # блик по верхней кромке
        p.drawPath(full.translated(-0.4, -0.6))
        # мелко справа от «СМЕНА»: powered by и версия жёлтыми цифрами; справа у стрелки — ТРИГГЕРЫ 1–20
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        f.setItalic(True)
        p.setFont(f)
        p.setPen(QColor("#9d9a86"))
        tx = b.right() + 16
        p.drawText(QPointF(tx, base - 2), "powered by Unknown_Tone")
        if self.version:
            fv = THEME.font("digits", 15)
            p.setFont(fv)
            p.setPen(THEME.c("hazard"))
            from PySide6.QtGui import QFontMetrics
            p.drawText(QPointF(tx + QFontMetrics(f).horizontalAdvance("powered by Unknown_Tone") + 10, base - 1),
                       self.version)
        p.setFont(THEME.font("engrave", 13, bold=True))
        p.setPen(QColor("#c8c6b4"))
        p.drawText(QRectF(r.right() - 240, r.top(), 190, r.height()), Qt.AlignVCenter | Qt.AlignRight, self.sub)
        p.setPen(THEME.c("accent"))
        p.setFont(THEME.font("engrave", 16, bold=True))
        p.drawText(QRectF(r.right() - 44, r.top(), 24, r.height()), Qt.AlignCenter, "▼" if self.open else "▲")
        p.end()
