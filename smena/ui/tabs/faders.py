"""Вкладка ФЕЙДЕРЫ: верхнее фото, образ (ОРИГИНАЛ, СИЛА ЭФФ., ЭЛЕМЕНТЫ, ЯРКОСТЬ), смена кадров и 4 LFO с проводами.

Под каждым фейдером — гнездо: провод от выхода LFO к гнезду модулирует фейдер (несколько проводов складываются).
Провод тянется мышью от выхода LFO к гнезду; правый клик по гнезду снимает его провода; провод можно взять
с гнезда фейдера и перенести (или бросить мимо — снять).
"""
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from smena.scene.modulation import rate_text
from smena.ui.instruments import EyeFill, Scope
from smena.triggers_table import (N_LFO, ORDER_NAMES, QUANT_NAMES, SCENE_BY_KEY, TRANSITION_TIPS, TRANSITIONS,
                                  WAVE_TIPS, WAVES)
from smena.ui.widgets import Fader, Jack, Knob, fmt_num

WIRE_COLORS = ["#d5e22b", "#f1d81f", "#efeedd", "#3dff7a"]


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


def value_text(key, x):
    g = SCENE_BY_KEY[key]
    if key == "tr.kind":
        return TRANSITIONS[int(round(x))].lower()
    if key == "tr.quant":
        return QUANT_NAMES[int(round(x))]
    if key == "tr.order":
        return ORDER_NAMES[int(round(x))]
    return f"{fmt_num(x, g.step)} {g.unit}".strip()


class ScreenFader(QWidget):
    """Подпись, фейдер экрана, значение и гнездо модуляции."""

    def __init__(self, key, params, patch):
        super().__init__()
        self.key, self.p = key, params
        g = SCENE_BY_KEY[key]
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        name = lbl(g.label.replace(" ", "\n", 1) if len(g.label) > 7 else g.label, "dim")
        name.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        name.setFixedHeight(24)
        name.setStyleSheet("font-size: 9px;")
        v.addWidget(name)
        self.fader = Fader(g.lo, g.hi, g.default, g.step, label=g.label, unit=g.unit, variant="screen", hint=g.hint)
        self.fader.setFixedSize(40, 96)
        v.addWidget(self.fader, 0, Qt.AlignHCenter)
        self.val = lbl("", "")
        self.val.setAlignment(Qt.AlignHCenter)
        self.val.setStyleSheet("font-size: 11px;")
        v.addWidget(self.val)
        self.jack = Jack(patch, key)
        v.addWidget(self.jack, 0, Qt.AlignHCenter)
        self.setFixedWidth(44)
        for w in (name, self.val):
            w.setToolTip(f"{g.label} — {g.hint}")
        self.fader.valueChanged.connect(lambda x: params.set(key, x))
        params.changed.connect(lambda k: k == key and self.refresh())
        self.refresh()

    def refresh(self):
        x = self.p[self.key]
        self.fader.set_value(x, emit=False)
        self.val.setText(value_text(self.key, x))

    def show_mod(self, x):
        """Положение с учётом LFO — «призрак» на фейдере."""
        if x != self.fader.auto_value:
            self.fader.auto_value = x
            self.fader.update()


class LfoPanel(QFrame):
    def __init__(self, i, params, patch):
        super().__init__()
        self.i, self.p = i, params
        self.setProperty("role", "group")
        self.setFixedWidth(134)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)
        top = QHBoxLayout()
        title = lbl(f"LFO {i}", "lfo")
        self.setToolTip("LFO — тяните провод от «ВЫХ» к гнезду под любым фейдером (вкладка, оба банка); "
                        "к одному фейдеру можно несколько; правый клик по гнезду — снять")
        title.setStyleSheet(f"color: {WIRE_COLORS[i - 1]};")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(lbl("ВЫХ", "dim"))
        self.out = Jack(patch, f"lfo{i}", out=True)
        top.addWidget(self.out)
        v.addLayout(top)

        waves = QHBoxLayout()
        waves.setSpacing(2)
        self.wave_group = QButtonGroup(self)
        for k, (w, tip) in enumerate(zip(WAVES, WAVE_TIPS)):
            b = QPushButton(w)
            b.setCheckable(True)
            b.setToolTip(f"форма волны: {tip}")
            b.setStyleSheet("padding: 1px 0px; font-size: 10px;")
            self.wave_group.addButton(b, k)
            waves.addWidget(b)
        self.wave_group.idClicked.connect(lambda k: params.set(f"lfo{i}.wave", k))
        v.addLayout(waves)

        g = QGridLayout()
        g.setSpacing(2)
        self.rate = Knob(0, 100, 40, 1, label=f"LFO {i} · СКОРОСТЬ", variant="screen", size=30,
                         hint="скорость: в режиме BPM — от 1/4 доли до 256 тактов на цикл, в режиме Гц — от 8 Гц "
                              "до 1 цикла за ~17 минут")
        self.rate.valueChanged.connect(lambda x: params.set(f"lfo{i}.rate", x))
        g.addWidget(self.rate, 0, 0)
        self.rate_lbl = lbl("", "")
        self.rate_lbl.setStyleSheet("font-size: 10px;")
        g.addWidget(self.rate_lbl, 1, 0, 1, 2)
        self.depth = Knob(0, 100, 50, 1, label=f"LFO {i} · ГЛУБИНА", unit="%", variant="screen", size=30,
                          hint="глубина: насколько LFO двигает фейдеры (100 % — на половину хода в обе стороны)")
        self.depth.valueChanged.connect(lambda x: params.set(f"lfo{i}.depth", x))
        g.addWidget(self.depth, 0, 1)
        self.depth_lbl = lbl("", "")
        self.depth_lbl.setStyleSheet("font-size: 10px;")
        g.addWidget(self.depth_lbl, 1, 2)
        self.sync = QPushButton("BPM")
        g.addWidget(self.sync, 0, 2)
        v.addLayout(g)
        self.sync.setCheckable(True)
        self.sync.setToolTip("BPM — скорость в тактах, цикл стоит на сетке трека; выключено — свободно, в Гц")
        self.sync.setStyleSheet("padding: 1px 4px; font-size: 11px;")
        self.sync.toggled.connect(lambda x: params.set(f"lfo{i}.sync", x))
        params.changed.connect(lambda k: k.startswith(f"lfo{i}.") and self.refresh())
        self.refresh()

    def refresh(self):
        p, i = self.p, self.i
        self.wave_group.button(int(p[f"lfo{i}.wave"])).setChecked(True)
        self.rate.set_value(p[f"lfo{i}.rate"], emit=False)
        self.depth.set_value(p[f"lfo{i}.depth"], emit=False)
        self.sync.blockSignals(True)
        self.sync.setChecked(bool(p[f"lfo{i}.sync"]))
        self.sync.setText("BPM" if p[f"lfo{i}.sync"] else "Гц")
        self.sync.blockSignals(False)
        self.rate_lbl.setText(rate_text(p[f"lfo{i}.rate"], p[f"lfo{i}.sync"]))
        self.depth_lbl.setText(f"{p[f'lfo{i}.depth']:.0f}%")


class PatchLayer(QWidget):
    """Провода поверх всего окна (мышь проходит насквозь): от выходов LFO на вкладке ФЕЙДЕРЫ к гнёздам любых
    фейдеров — вкладки и обоих фейдербанков. Провод рисуется, когда оба гнезда на экране; провода между
    консолью и банками — полупрозрачные. Логика перетаскивания — для гнёзд Jack."""

    def __init__(self, parent, params):
        super().__init__(parent)
        self.p = params
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.jacks = {}               # ключ → Jack ("lfo1"… — выходы)
        self.local = set()            # ключи гнёзд вкладки ФЕЙДЕРЫ (провода к ним — непрозрачные)
        self._drag = None             # (номер LFO, глобальная точка конца)
        self._dirty = QRect()
        parent.installEventFilter(self)
        params.changed.connect(lambda k: k == "lfo.wires" and self._wires_changed())

    def register(self, jack):
        self.jacks[jack.key] = jack

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Resize:
            self.setGeometry(obj.rect())
            self.raise_()
        return False

    def wires(self):
        return [tuple(w) for w in self.p["lfo.wires"]]

    def _set(self, wires):
        self.p.set("lfo.wires", [list(w) for w in wires])

    def _wires_changed(self):
        for j in self.jacks.values():
            j.update()
        self.update()

    def tick(self):
        """Гнёзда двигаются (прокрутка, крышки банков, вкладки) — перерисовать только область проводов."""
        if not self.wires() and self._dirty.isEmpty():
            return
        r = QRect()
        sig = []
        for i, key in self.wires():
            a, b = self.jacks.get(f"lfo{i}"), self.jacks.get(key)
            if a and b and self._shown(a) and self._shown(b):
                pa, pb = self._center(a), self._center(b)
                sig.append((i, key, pa.toTuple(), pb.toTuple()))
                r = r.united(QRect(pa.toPoint(), pb.toPoint()).normalized().adjusted(-30, -30, 30, 140))
        if sig == getattr(self, "_sig", None):         # ничего не сдвинулось — не перерисовываем
            return
        self._sig = sig
        self.update(r.united(self._dirty))
        self._dirty = r

    @staticmethod
    def _shown(jack):
        return jack.isVisible() and not jack.visibleRegion().isEmpty()

    def busy(self, jack):
        return any(k == jack.key for _, k in self.wires())

    # --------------------------------------------------------- перетаскивание
    def begin(self, jack, gpos):
        if jack.out:
            self._drag = [int(jack.key[3:]), gpos]
        else:                                          # взять последний провод с гнезда фейдера
            ws = self.wires()
            mine = [w for w in ws if w[1] == jack.key]
            if not mine:
                return
            ws.remove(mine[-1])
            self._set(ws)
            self._drag = [mine[-1][0], gpos]
        self.update()

    def drag(self, gpos):
        if self._drag:
            self._drag[1] = gpos
            self.update()

    def end(self, gpos):
        if not self._drag:
            return
        i = self._drag[0]
        self._drag = None
        w = QApplication.widgetAt(gpos.toPoint())
        if isinstance(w, Jack) and not w.out:
            ws = self.wires()
            if (i, w.key) not in ws:
                self._set(ws + [(i, w.key)])
        self.update()

    def unplug(self, jack):
        if jack.out:
            n = int(jack.key[3:])
            self._set([w for w in self.wires() if w[0] != n])
        else:
            self._set([w for w in self.wires() if w[1] != jack.key])

    # --------------------------------------------------------- рисование
    def _center(self, jack):
        return QPointF(self.mapFromGlobal(jack.mapToGlobal(jack.rect().center())))

    def _cable(self, p, a, b, col):
        path = QPainterPath(a)
        sag = max(a.y(), b.y()) + 40 + min(abs(a.x() - b.x()) * 0.08, 60)
        path.cubicTo(QPointF(a.x() + 20, sag), QPointF(b.x() - 20, sag), b)
        p.setPen(QPen(QColor(0, 0, 0, min(160, QColor(col).alpha())), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(QColor(col), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        for i, key in self.wires():
            a, b = self.jacks.get(f"lfo{i}"), self.jacks.get(key)
            if a and b and self._shown(a) and self._shown(b):
                col = QColor(WIRE_COLORS[(i - 1) % 4])
                if key not in self.local:                      # провод из консоли в фейдербанк
                    col.setAlpha(130)
                self._cable(p, self._center(a), self._center(b), col)
        if self._drag:
            a = self.jacks[f"lfo{self._drag[0]}"]
            self._cable(p, self._center(a), QPointF(self.mapFromGlobal(self._drag[1].toPoint())),
                        WIRE_COLORS[(self._drag[0] - 1) % 4])
        p.end()


class FadersTab(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win, self.p = win, win.params
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.setWidget(inner)
        self.patch = win.patch
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(6)
        self.faders = {}

        def group(title, keys, extra=None):
            f = QFrame()
            f.setProperty("role", "group")
            gv = QVBoxLayout(f)
            gv.setContentsMargins(6, 4, 6, 4)
            gv.setSpacing(3)
            gv.addWidget(lbl(title, "dim"))
            if extra:
                gv.addLayout(extra)
            row = QHBoxLayout()
            row.setSpacing(2)
            for k in keys:
                sf = ScreenFader(k, self.p, self.patch)
                self.patch.register(sf.jack)
                self.patch.local.add(k)
                self.faders[k] = sf
                row.addWidget(sf)
            row.addStretch()
            gv.addLayout(row)
            return f

        row1 = QHBoxLayout()
        img = QHBoxLayout()
        self.smooth = QPushButton("РЕЗКО")
        self.smooth.setCheckable(True)
        self.smooth.setToolTip("РЕЗКО — фейдеры ОБРАЗА действуют сразу; ПЛАВНО — новые положения берутся со "
                               "следующего фото и мягко перетекают")
        self.smooth.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        self.smooth.toggled.connect(lambda x: self.p.set("img.smooth", x))
        img.addWidget(self.smooth)
        self.alpha = QPushButton("ПРОЗР. ВЫКЛ")
        self.alpha.setCheckable(True)
        self.alpha.setToolTip("ПРОЗРАЧНОСТЬ — ВКЛ: при СИЛЕ ЭФФ. и ОРИГИНАЛЕ элементы становятся полупрозрачными; "
                              "ВЫКЛ: элементы всегда целиком — сила уменьшает число элементов в игре и движение")
        self.alpha.setStyleSheet("padding: 2px 6px; font-size: 11px;")
        self.alpha.toggled.connect(lambda x: self.p.set("img.alpha", x))
        img.addWidget(self.alpha)
        img.addStretch()
        row1.addWidget(group("ОБРАЗ", ["orig", "orig.hold", "orig.flash", "strength", "gran", "bright"], img))

        # смена кадров: кнопки видов (ставят фейдер ВИД) + фейдеры
        kinds = QHBoxLayout()
        kinds.setSpacing(2)
        self.morph = QPushButton("ON")
        self.morph.setCheckable(True)
        self.morph.setProperty("role", "warn")
        self.morph.setToolTip("МОРФИНГ ON — смена кадров по этим фейдерам; OFF — как в первых версиях: элементы, "
                              "период T из фейдербанка, на такт, по папке")
        self.morph.setStyleSheet("padding: 2px 4px; font-size: 10px;")
        self.morph.toggled.connect(lambda x: self.p.set("tr.on", x))
        kinds.addWidget(self.morph)
        kinds.addSpacing(6)
        self.kind_group = QButtonGroup(self)
        for k, (name, tip) in enumerate(zip(TRANSITIONS, TRANSITION_TIPS)):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setStyleSheet("padding: 2px 2px; font-size: 9px;")
            self.kind_group.addButton(b, k)
            kinds.addWidget(b)
        kinds.addStretch()
        self.kind_group.idClicked.connect(lambda k: self.p.set("tr.kind", float(k)))
        row1.addWidget(group("СМЕНА КАДРОВ · МОРФИНГ", ["tr.kind", "T", "tr.dur", "tr.curve", "tr.quant", "tr.rand",
                                                         "tr.order"], kinds))
        row1.addStretch()
        row1.setSpacing(10)
        v.addLayout(row1)                             # ОБРАЗ и МОРФИНГ — рядом, LFO — под ними: всё в один экран

        self.scope = Scope(win.mod)                       # LFO — в экране осциллографа
        lfos = QHBoxLayout(self.scope)
        lfos.setContentsMargins(14, 22 + Scope.STRIP, 14, 12)
        lfos.setSpacing(4)
        self.lfos = []
        for i in range(1, N_LFO + 1):
            lp = LfoPanel(i, self.p, self.patch)
            lp.setProperty("role", "scope_lfo")
            self.patch.register(lp.out)
            self.lfos.append(lp)
            lfos.addWidget(lp)
        v.addWidget(self.scope)
        v.addWidget(EyeFill(), 1)                         # пустое место — почти незаметный глаз со дна
        self.p.changed.connect(self._param)
        for k in ("tr.kind", "img.smooth", "img.alpha", "tr.on"):
            self._param(k)

    def _choose_overlay(self):
        cur = self.p["ov.file"]
        path, _ = QFileDialog.getOpenFileName(self, "Верхнее фото", cur or "",
                                              "Картинки (*.png *.jpg *.jpeg *.webp *.bmp);;Все файлы (*)")
        if path:
            self.p.set("ov.file", path)

    def _reset(self):
        if QMessageBox.question(self, "Сбросить настройки",
                                "Все фейдеры, переключатели, LFO и провода вкладки ФЕЙДЕРЫ — к заводскому состоянию?"
                                ) == QMessageBox.Yes:
            self.p.reset_scene()
            self.win.engine.log_event("ФЕЙДЕРЫ: заводские настройки")

    def _param(self, k):
        if k == "img.alpha":
            on = bool(self.p["img.alpha"])
            self.alpha.blockSignals(True)
            self.alpha.setChecked(on)
            self.alpha.setText("ПРОЗР. ВКЛ" if on else "ПРОЗР. ВЫКЛ")
            self.alpha.blockSignals(False)
            return
        if k == "img.smooth":
            on = bool(self.p["img.smooth"])
            self.smooth.blockSignals(True)
            self.smooth.setChecked(on)
            self.smooth.setText("ПЛАВНО" if on else "РЕЗКО")
            self.smooth.blockSignals(False)
            return
        if k == "tr.on":
            on = bool(self.p["tr.on"])
            self.morph.blockSignals(True)
            self.morph.setChecked(on)
            self.morph.setText("ON" if on else "OFF")
            self.morph.blockSignals(False)
            for key in ("tr.kind", "T", "tr.dur", "tr.curve", "tr.quant", "tr.rand", "tr.order"):
                self.faders[key].setEnabled(on)
            for b in self.kind_group.buttons():
                b.setEnabled(on)
            return
        if k == "tr.kind":
            b = self.kind_group.button(int(round(self.p["tr.kind"])))
            if b:
                b.setChecked(True)

    def tick(self, mod):
        """«Призраки» на фейдерах с проводами — положение с учётом LFO."""
        for k, sf in self.faders.items():
            sf.show_mod(mod.v(k) if k in mod.offsets else None)
        self.scope.update()
