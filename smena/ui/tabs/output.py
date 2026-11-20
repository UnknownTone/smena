"""Вкладка ВЫВОД: монитор и окно вывода (HDMI), BLACKOUT, разрешение рендера, GL_RENDERER, fps;
калибровка геометрии сеткой узлов и маска (вырезать изображение под мапинг) — простыми инструментами мышью.

Холст показывает выход (без маски — видно, что вырезаешь), маску — жёлтым. Сохраняется по монитору сразу
после каждого действия (render/mapping.py).
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from smena.render.mapping import MASK_H, MASK_W
from smena.ui.widgets import Fader

SIZES = [(1920, 1080), (1280, 720), (2560, 1440), (3840, 2160)]
TOOLS = [("grid", "⊞ СЕТКА", "сетка — тяните узлы мышью: изображение изгибается (кривой экран, угол стены, трапеция)"),
         ("rect", "▭", "маска-прямоугольник: тяните мышью — область станет видимой"),
         ("poly", "⬠", "маска-многоугольник: клик — точка, двойной клик — замкнуть"),
         ("brush", "✎", "кисть — дорисовать маску от руки"),
         ("erase", "⌫", "ластик — стереть часть маски")]


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(True)
    return w


class MapCanvas(QWidget):
    """Холст калибровки: снимок выхода, сетка узлов, маска."""

    def __init__(self, mapping, changed):
        super().__init__()
        self.m = mapping
        self.changed = changed            # вызвать после правки (сохранить)
        self.tool = "grid"
        self.brush = 30
        self.snap = None
        self.poly = []
        self._node = None
        self._start = None
        self._cur = None
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_snapshot(self, w, h, data):
        img = QImage(data, w, h, 4 * w, QImage.Format_RGBA8888).mirrored(False, True)
        self.snap = img.copy()
        self.update()

    def frame(self):
        W, H = self.width() - 16, self.height() - 16
        k = min(W / 16, H / 9)
        w, h = 16 * k, 9 * k
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def to_norm(self, pos):
        r = self.frame()
        return (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()

    def to_px(self, x, y):
        r = self.frame()
        return QPointF(r.x() + x * r.width(), r.y() + y * r.height())

    # ------------------------------------------------------------- рисование
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.frame()
        p.fillRect(r, QColor("#000"))
        if self.snap:
            p.drawImage(r, self.snap)
        if self.m.mask is not None:                    # маска: снаружи — затемнение, граница — жёлтым
            a = self.m.mask if not self.m.invert else self._inverted(self.m.mask)
            alpha = QImage(a.constBits(), a.width(), a.height(), a.bytesPerLine(), QImage.Format_Alpha8).copy()
            tint = QImage(a.size(), QImage.Format_ARGB32_Premultiplied)
            tint.fill(QColor(0, 0, 0, 170))
            pm = QPainter(tint)
            pm.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            pm.drawImage(0, 0, alpha)                  # где маска видна — затемнение снимается
            pm.end()
            p.drawImage(r, tint)
        nx, ny, nodes = self.m.nx, self.m.ny, self.m.out_nodes()   # как на выходе: с шириной / высотой / сдвигом
        grid_on = self.tool == "grid"
        p.setPen(QPen(QColor(61, 255, 122, 220 if grid_on else 90), 1))
        for j in range(ny):
            for i in range(nx):
                a = self.to_px(*nodes[j * nx + i])
                if i < nx - 1:
                    p.drawLine(a, self.to_px(*nodes[j * nx + i + 1]))
                if j < ny - 1:
                    p.drawLine(a, self.to_px(*nodes[(j + 1) * nx + i]))
        if grid_on:
            for k, n in enumerate(nodes):
                c = self.to_px(*n)
                p.setBrush(QColor("#3dff7a") if k == self._node else QColor("#04130a"))
                p.setPen(QPen(QColor("#3dff7a"), 2))
                p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
        y = QColor("#ffcf3d")
        if self.tool == "rect" and self._start and self._cur:
            p.setPen(QPen(y, 2, Qt.DashLine))
            p.setBrush(QColor(255, 207, 61, 40))
            p.drawRect(QRectF(self._start, self._cur).normalized())
        if self.tool == "poly" and self.poly:
            pts = [self.to_px(*q) for q in self.poly] + ([self._cur] if self._cur else [])
            p.setPen(QPen(y, 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts))
            p.setBrush(y)
            for q in pts[:len(self.poly)]:
                p.drawEllipse(q, 4, 4)
        if self.tool in ("brush", "erase") and self._cur:
            rad = self.brush / MASK_W * r.width()
            p.setPen(QPen(y if self.tool == "brush" else QColor("#ff6050"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self._cur, rad, rad)
        p.setPen(QPen(QColor("#1e8a44"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        p.end()

    @staticmethod
    def _inverted(img):
        out = QImage(img)
        out.invertPixels()
        return out

    # ------------------------------------------------------------- маска
    def _mask_painter(self, white):
        img = self.m.ensure_mask()
        if self.m.invert:                                # рисуем в «видимое» и при инверсии
            white = not white
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(255, 255, 255) if white else QColor(0, 0, 0)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        return p, c

    def _mpt(self, nx_ny):
        return QPointF(nx_ny[0] * MASK_W, nx_ny[1] * MASK_H)

    def _dab(self, pos, white):
        p, c = self._mask_painter(white)
        x, y = self.to_norm(pos)
        p.drawEllipse(self._mpt((x, y)), self.brush, self.brush)
        p.end()
        self.m.touch()

    # ------------------------------------------------------------- мышь
    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() != Qt.LeftButton:
            if self.tool == "poly":
                self.poly = []
                self.update()
            return
        if self.tool == "grid":
            best = None
            for k, n in enumerate(self.m.out_nodes()):
                d = (self.to_px(*n) - pos).manhattanLength()
                if d < 18 and (best is None or d < best[0]):
                    best = (d, k)
            self._node = best[1] if best else None
        elif self.tool == "rect":
            self._start = self._cur = pos
        elif self.tool == "poly":
            self.poly.append(self.to_norm(pos))
        else:
            self._dab(pos, self.tool == "brush")
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._cur = pos
        if e.buttons() & Qt.LeftButton:
            if self.tool == "grid" and self._node is not None:
                x, y = self.to_norm(pos)                     # обратно из выхода в узел сетки
                m = self.m
                x = 0.5 + (x - 0.5 - m.dx) / max(m.sx, 0.01)
                y = 0.5 + (y - 0.5 - m.dy) / max(m.sy, 0.01)
                m.nodes[self._node] = [min(max(x, -0.5), 1.5), min(max(y, -0.5), 1.5)]
                self.m.touch()
            elif self.tool in ("brush", "erase"):
                self._dab(pos, self.tool == "brush")
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.tool == "rect" and self._start:
            a, b = self.to_norm(self._start), self.to_norm(e.position())
            if abs(a[0] - b[0]) > 0.005 and abs(a[1] - b[1]) > 0.005:
                p, _ = self._mask_painter(True)
                p.drawRect(QRectF(self._mpt(a), self._mpt(b)).normalized())
                p.end()
                self.m.touch()
            self._start = None
        self._node = None
        self.changed()
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.tool == "poly" and len(self.poly) >= 3:
            p, _ = self._mask_painter(True)
            path = QPainterPath()
            path.addPolygon(QPolygonF([self._mpt(q) for q in self.poly]))
            p.fillPath(path, QBrush(QColor(255, 255, 255) if not self.m.invert else QColor(0, 0, 0)))
            p.end()
            self.poly = []
            self.m.touch()
            self.changed()
            self.update()

    def leaveEvent(self, _):
        self._cur = None
        self.update()


class OutputTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.settings
        self.mapping = win.mapping
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.addWidget(lbl("МОНИТОР", "dim"), 0, 0)
        self.monitor = QComboBox()
        self.monitor.setToolTip("монитор / проектор для окна вывода (HDMI)")
        self.monitor.currentIndexChanged.connect(self._monitor)
        g.addWidget(self.monitor, 0, 1)
        b = QPushButton("Обновить")
        b.setToolTip("перечитать список мониторов")
        b.clicked.connect(self.refresh_monitors)
        g.addWidget(b, 0, 2)
        self.show_btn = QPushButton("ВЫВОД ▶")
        self.show_btn.setCheckable(True)
        self.show_btn.setToolTip("открыть / закрыть окно вывода на выбранном мониторе. В окне: F — полный экран, "
                                 "Esc — в окно")
        self.show_btn.toggled.connect(win.set_output)
        g.addWidget(self.show_btn, 1, 0)
        self.full = QCheckBox("на весь экран")
        self.full.setToolTip("окно вывода — на весь экран без рамки")
        self.full.setChecked(bool(s["output_fullscreen"]))
        self.full.toggled.connect(self._full)
        g.addWidget(self.full, 1, 1)
        self.blackout = QPushButton("BLACKOUT")
        self.blackout.setCheckable(True)
        self.blackout.setProperty("role", "warn")
        self.blackout.setToolTip("BLACKOUT — чёрный на выходе (HDMI и запись); превью тоже темнеет")
        self.blackout.toggled.connect(win.set_blackout)
        g.addWidget(self.blackout, 1, 2)
        g.addWidget(lbl("РЕНДЕР", "dim"), 2, 0)
        self.size = QComboBox()
        self.size.setToolTip("разрешение рендера и выхода")
        for w, h in SIZES:
            self.size.addItem(f"{w}×{h}", [w, h])
        i = next((k for k, wh in enumerate(SIZES) if list(wh) == list(s["render_size"])), 0)
        self.size.setCurrentIndex(i)
        self.size.currentIndexChanged.connect(self._size)
        g.addWidget(self.size, 2, 1)
        self.fill = QCheckBox("фото на весь кадр")
        self.fill.setToolTip("фото заполняет весь кадр (края обрезаются, без серых полос по бокам) — элементы "
                             "летают до края экрана; выключено — фото целиком с размытой подложкой")
        self.fill.setChecked(bool(s["photo_fill"]))
        self.fill.toggled.connect(self._fill)
        g.addWidget(self.fill, 2, 2)
        v.addLayout(g)

        v.addWidget(lbl("КАЛИБРОВКА ГЕОМЕТРИИ · МАСКА", "title"))
        tools = QHBoxLayout()
        tools.setSpacing(2)
        self.tool_group = QButtonGroup(self)
        for k, (key, text, tip) in enumerate(TOOLS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setStyleSheet("padding: 2px 6px;")
            if key != "grid":
                b.setProperty("role", "warn")
            self.tool_group.addButton(b, k)
            tools.addWidget(b)
        self.tool_group.button(0).setChecked(True)
        self.tool_group.idClicked.connect(self._tool)
        self.grid = QComboBox()
        self.grid.setToolTip("плотность сетки узлов")
        for n in range(2, 9):
            self.grid.addItem(f"{n}×{n}", n)
        self.grid.setCurrentIndex(max(0, self.mapping.nx - 2))
        self.grid.currentIndexChanged.connect(lambda _: self._grid())
        tools.addSpacing(8)
        for text, fn, tip in (("⇆", self._invert, "инвертировать маску: видно снаружи ↔ внутри"),
                              ("РОВНО", self._reset_grid, "сетка — ровная (узлы на места)"),
                              ("БЕЗ МАСКИ", self._clear_mask, "убрать маску — видно всё")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setStyleSheet("padding: 2px 6px;")
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch()
        tools.addWidget(lbl("СЕТКА", "dim"))           # плотность сетки — справа
        tools.addWidget(self.grid)
        v.addLayout(tools)

        self.canvas = MapCanvas(self.mapping, self._changed)
        geo = QHBoxLayout()
        self.geo = {}
        for key, name, lo, hi, step, unit, hint in (
                ("sx", "ШИР.", 10, 200, 1, "%", "ширина картинки на выходе"),
                ("sy", "ВЫС.", 10, 200, 1, "%", "высота картинки на выходе"),
                ("dx", "X", -50, 50, 0.5, "%", "сдвиг картинки по горизонтали"),
                ("dy", "Y", -50, 50, 0.5, "%", "сдвиг картинки по вертикали")):
            f = Fader(lo, hi, 100 if key in ("sx", "sy") else 0, step, label=name, unit=unit, variant="screen",
                      hint=hint)
            f.setFixedSize(40, 90)
            f.valueChanged.connect(lambda x, key=key: self._geo(key, x))
            self.geo[key] = f
            col = QVBoxLayout()
            col.addWidget(f, 0, Qt.AlignHCenter)
            col.addWidget(lbl(name, "dim"), 0, Qt.AlignHCenter)
            geo.addLayout(col)
        self.geo_box = QWidget()                        # КАРТИНКА — слева от холста (или снизу)
        gbox = QVBoxLayout(self.geo_box)
        gbox.setContentsMargins(0, 0, 0, 0)
        gbox.addWidget(lbl("КАРТИНКА", "dim"))
        gbox.addLayout(geo)
        gbox.addStretch()
        faders = QHBoxLayout()
        self.feather = Fader(0, 60, 12, 1, label="РАСТУШЁВКА", unit="px", variant="screen",
                             hint="мягкость края маски")
        self.offset = Fader(-40, 40, 0, 1, label="ОТСТУП", unit="px", variant="screen",
                            hint="расширить (+) или сузить (−) маску")
        self.brush = Fader(4, 120, 30, 1, label="КИСТЬ", unit="px", variant="screen", hint="размер кисти и ластика")
        for f, name in ((self.feather, "РАСТ."), (self.offset, "ОТСТ."), (self.brush, "КИСТЬ")):
            f.setFixedSize(40, 90)
            col = QVBoxLayout()
            col.addWidget(f, 0, Qt.AlignHCenter)
            col.addWidget(lbl(name, "dim"), 0, Qt.AlignHCenter)
            faders.addLayout(col)
        self.feather.set_value(self.mapping.feather, emit=False)
        self.offset.set_value(self.mapping.offset, emit=False)
        self.feather.valueChanged.connect(self._mask_opts)
        self.offset.valueChanged.connect(self._mask_opts)
        self.brush.valueChanged.connect(lambda x: setattr(self.canvas, "brush", int(x)))
        self.mask_box = QWidget()                       # МАСКА — справа от холста (или снизу)
        mbox = QVBoxLayout(self.mask_box)
        mbox.setContentsMargins(0, 0, 0, 0)
        mbox.addWidget(lbl("МАСКА", "dim"))
        mbox.addLayout(faders)
        mbox.addStretch()
        self.area = QGridLayout()
        self.area.setSpacing(8)
        v.addLayout(self.area, 1)
        self._side = None
        self._arrange(True)
        bottom = QHBoxLayout()
        bottom.addWidget(lbl("калибровка хранится по монитору, отдельно от пресетов", "dim"), 1)
        reset = QPushButton("↺ СБРОС")
        reset.setToolTip("сбросить калибровку этого монитора: сетка ровная, без маски, ширина / высота 100 %, "
                         "без сдвига")
        reset.clicked.connect(self._reset_all)
        bottom.addWidget(reset)
        v.addLayout(bottom)

        info = QHBoxLayout()
        self.renderer = lbl("…", "dim")
        info.addWidget(self.renderer, 1)
        self.fps = lbl("", "dim")
        info.addWidget(self.fps)
        v.addLayout(info)
        self.gpu_warn = lbl("", "warn")
        v.addWidget(self.gpu_warn)
        self.refresh_monitors()
        self._sync_geo()

    # ------------------------------------------------------------- раскладка
    SIDE_H = 640           # ниже этой высоты (поднят отсек управления) — фейдеры по бокам холста

    def _arrange(self, side):
        """side — фейдеры слева и справа от холста; иначе — под холстом на всю ширину."""
        if side == self._side:
            return
        self._side = side
        for w in (self.geo_box, self.canvas, self.mask_box):
            self.area.removeWidget(w)
        for c in range(3):
            self.area.setColumnStretch(c, 0)
        self.area.setRowStretch(0, 0)
        self.area.setRowStretch(1, 0)
        if side:
            self.area.addWidget(self.geo_box, 0, 0)
            self.area.addWidget(self.canvas, 0, 1)
            self.area.addWidget(self.mask_box, 0, 2)
            self.area.setColumnStretch(1, 1)
            self.area.setRowStretch(0, 1)
        else:
            self.area.addWidget(self.canvas, 0, 0, 1, 3)
            self.area.addWidget(self.geo_box, 1, 0)
            self.area.addWidget(self.mask_box, 1, 1)
            self.area.setColumnStretch(2, 1)
            self.area.setRowStretch(0, 1)

    def resizeEvent(self, e):
        self._arrange(self.height() < self.SIDE_H)
        super().resizeEvent(e)

    # ------------------------------------------------------------- настройки
    def _fill(self, x):
        self._save("photo_fill", x)
        self.win.clock.set_fill(x)

    def _geo(self, key, x):
        setattr(self.mapping, key, x / 100.0)
        self.mapping.touch()
        self._changed()

    def _sync_geo(self):
        for key, f in self.geo.items():
            f.set_value(getattr(self.mapping, key) * 100.0, emit=False)
    def _save(self, k, val):
        self.win.settings[k] = val
        self.win.settings.save()

    def _size(self, k):
        self._save("render_size", list(SIZES[k]))
        self.win.set_render_size(SIZES[k])

    def _full(self, x):
        self._save("output_fullscreen", x)
        self.win.place_output()

    def refresh_monitors(self):
        self.monitor.blockSignals(True)
        self.monitor.clear()
        for i, sc in enumerate(QGuiApplication.screens(), 1):
            g = sc.geometry()
            r = sc.devicePixelRatio()
            self.monitor.addItem(f"{i}: {sc.name()} · {round(g.width() * r)}×{round(g.height() * r)} "
                                 f"· {sc.refreshRate():.0f} Гц")
        want = int(self.win.settings["output_monitor"]) - 1
        self.monitor.setCurrentIndex(min(max(want, 0), self.monitor.count() - 1))
        self.monitor.blockSignals(False)

    def _monitor(self, i):
        if i >= 0:
            self._save("output_monitor", i + 1)
            self.mapping.load(i + 1)
            self.grid.blockSignals(True)
            self.grid.setCurrentIndex(max(0, self.mapping.nx - 2))
            self.grid.blockSignals(False)
            self.feather.set_value(self.mapping.feather, emit=False)
            self.offset.set_value(self.mapping.offset, emit=False)
            self._sync_geo()
            self.win.place_output()
            self.canvas.update()

    # ------------------------------------------------------------- калибровка
    def _tool(self, k):
        self.canvas.tool = TOOLS[k][0]
        self.canvas.poly = []
        self.canvas.update()

    def _grid(self):
        n = self.grid.currentData()
        self.mapping.set_grid(n, n)
        self._changed()

    def _reset_all(self):
        m = self.mapping
        m.nx = m.ny = 2
        m.nodes = m.grid_nodes(2, 2)
        m.mask, m.invert, m.feather, m.offset = None, False, 12, 0
        m.sx = m.sy = 1.0
        m.dx = m.dy = 0.0
        m.touch()
        self.grid.blockSignals(True)
        self.grid.setCurrentIndex(0)
        self.grid.blockSignals(False)
        self.feather.set_value(12, emit=False)
        self.offset.set_value(0, emit=False)
        self._sync_geo()
        self._changed()
        self.win.engine.log_event("ВЫВОД: калибровка сброшена")

    def _reset_grid(self):
        self.mapping.reset_grid()
        self._changed()

    def _invert(self):
        if self.mapping.mask is None:
            return
        self.mapping.invert = not self.mapping.invert
        self.mapping.touch()
        self._changed()

    def _clear_mask(self):
        self.mapping.clear_mask()
        self._changed()

    def _mask_opts(self, *_):
        self.mapping.feather = int(self.feather.value)
        self.mapping.offset = int(self.offset.value)
        self.mapping.touch()
        self._changed()

    def _changed(self):
        self.mapping.save()
        self.canvas.update()

    # ------------------------------------------------------------- статус
    def set_renderer(self, text):
        self.renderer.setText(f"GL: {text}")
        if "nvidia" in text.lower():
            self.gpu_warn.setText("")
        else:
            self.gpu_warn.setText("Визуал идёт не на NVIDIA. Параметры Windows → Система → Дисплей → Графика → "
                                  "SMENA → «Высокая производительность», затем перезапустить программу.")

    def tick(self, fps):
        self.fps.setText(f"превью: {fps:.0f} fps")

