"""Главное окно SMENA 0.1.2: верхняя панель (ut2 · SMENA, источник, СДВИГ / FX, ⏮ ПУСК/СТОП, ◀ счётчик ▶, BPM,
TAP · RESET, HUD, SAVE, REC), видоискатель, экран с вкладками, фейдербанк под катом внизу.
Таймер 30 Гц обновляет индикаторы, 60 Гц — сцену и превью; после кадра — выходной проход (HDMI), запись REC.

Клавиши: Пробел — пуск / стоп, ← → — фото, Home — к первому фото, T — tap, H — HUD, B — фейдербанк,
M — беззвучно, Ctrl+S — SAVE, Ctrl+Z — отмена СБРОС / RANDOM банка, Ctrl+R — перечитать тему.
"""
import os
import time

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

from smena import VERSION
from smena.render.mapping import Mapping
from smena.render.recorder import Recorder
from smena.scene.actions import Actions
from smena.scene.assets import AssetLoader
from smena.scene.clock import MasterClock
from smena.scene.modulation import Modulation, ModView, Overlay
from smena.triggers_table import TRIGGERS
from smena.ui.body import Lid, TinBody
from smena.ui.shutter import Shutter
from smena.ui.faderbank import GlobalBank, TriggerBank
from smena.ui.tabs.faders import FadersTab, PatchLayer
from smena.ui.tabs.log import LogTab
from smena.ui.tabs.output import OutputTab
from smena.ui.tabs.photos import PhotosTab
from smena.ui.tabs.presets import PresetsTab
from smena.ui.tabs.triggers import TriggersTab
from smena.ui.tabs.sound import SoundTab
from smena.ui.theme import THEME
from smena.ui.viewfinder import Viewfinder
from smena.ui.widgets import BeatIndicator, FrameCounter, Knob, PlateButton, Scanlines

BANK_H = 282


def engrave(text, role="engrave"):
    lb = QLabel(text)
    lb.setProperty("role", role)
    return lb


def button(text, tip, fn=None, w=None, h=40, checkable=False, name=None):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCheckable(checkable)
    if w:
        b.setFixedWidth(w)
    b.setFixedHeight(h)
    if name:
        b.setObjectName(name)
    if fn:
        (b.toggled if checkable else b.clicked).connect(fn)
    return b


class CutHandle(QFrame):
    """Полоса «▲ ГЛОБАЛЬНЫЕ» над правым фейдербанком — клик раскрывает / прячет его."""
    clicked = Signal()

    def __init__(self, title, sub, key):
        super().__init__()
        self.setObjectName("CutHandle")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{title} — нажмите, чтобы раскрыть / спрятать (клавиша {key})")
        self.setFixedHeight(30)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 2, 6, 2)
        self.arrow = engrave("▲", "engrave_red")
        h.addWidget(self.arrow)
        h.addWidget(engrave(title, "engrave_red"))
        grip = QFrame()
        grip.setFixedHeight(6)
        grip.setStyleSheet(f"background: {THEME.colors.get('olive', '#3e3c1c')}; border-radius: 3px;")
        h.addWidget(grip, 1)
        if sub:
            h.addWidget(engrave(sub, "engrave_dim"))
        self.arrow2 = engrave("▲", "engrave_red")
        h.addWidget(self.arrow2)

    def set_open(self, on):
        for a in (self.arrow, self.arrow2):
            a.setText("▼" if on else "▲")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class MainWindow(QMainWindow):
    def __init__(self, app, settings, engine, params):
        super().__init__()
        self.app, self.settings, self.engine, self.params = app, settings, engine, params
        self.setWindowTitle(f"SMENA {VERSION}")
        self.setMinimumSize(1560, 900)
        self._device_ids = []
        size = tuple(settings["render_size"])
        self.mod = Modulation(params)
        self.overlay = Overlay(params, self.mod)
        self.mapping = Mapping(int(settings["output_monitor"]))
        self.recorder = Recorder(engine.log_event)
        self.output_win = None
        self._snap_t = 0.0
        self.loader = AssetLoader()
        self.mview = ModView(params, self.mod)            # сцена видит фейдеры с учётом проводов LFO
        self.clock = MasterClock(engine, self.mview, size, self.mod)
        self.clock.fill = bool(settings["photo_fill"])
        self.actions = Actions(self.clock, engine.triggers, self.mview)
        self._flash_seen = {}

        body = TinBody(settings["prep_python"])           # жестяная коробка с вырезами
        self.body = body
        self.setCentralWidget(body)
        self.patch = PatchLayer(body, params)             # провода LFO поверх всего окна
        root = QVBoxLayout(body)
        root.setContentsMargins(42, 32, 42, 58)          # поля по краю коробки — снизу шире («от дна»)
        root.setSpacing(34)

        self.topbar = QFrame()                            # верхняя панель — тёмная плашка в вырезе жести
        self.topbar.setObjectName("TopBar")
        self.topbar.setAttribute(Qt.WA_StyledBackground)
        tb = self._top_bar()
        tb.setContentsMargins(18, 7, 18, 7)
        self.topbar.setLayout(tb)
        root.addWidget(self.topbar)

        mid = QHBoxLayout()
        mid.setSpacing(44)
        left = QVBoxLayout()
        left.setSpacing(34)
        right = QVBoxLayout()
        right.setSpacing(34)
        self.view = Viewfinder(self.clock, self.loader, size)
        self.view.hud.show_hud = bool(settings["hud"])
        self.view.gl.ready.connect(self._gl_ready)
        self.view.gl.host = self
        self.view.set_side(self._overlay_panel())    # ВЕРХНЕЕ ФОТО — в чёрной полосе слева от картинки
        left.addWidget(self.view, 1)

        screen = QFrame()
        screen.setObjectName("PipScreen")
        sv = QVBoxLayout(screen)
        sv.setContentsMargins(10, 8, 10, 10)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("ScreenTabs")
        self.sound_tab = SoundTab(self)
        self.faders_tab = FadersTab(self)
        self.output_tab = OutputTab(self)
        self.presets_tab = PresetsTab(self)
        self.triggers_tab = TriggersTab(self)
        self.log_tab = LogTab(self)
        self.photos_tab = PhotosTab(self)      # сразу сканирует папку и ставит счётчик кадров
        self.photos_tab.setMinimumHeight(600)  # при поднятом правом банке — прокрутка вниз
        photos_scroll = QScrollArea()
        photos_scroll.setWidgetResizable(True)
        photos_scroll.setFrameShape(QFrame.NoFrame)
        photos_scroll.setWidget(self.photos_tab)
        sound_scroll = QScrollArea()                   # ЗВУК — с прокруткой (эквалайзер внизу)
        sound_scroll.setWidgetResizable(True)
        sound_scroll.setFrameShape(QFrame.NoFrame)
        sound_scroll.setWidget(self.sound_tab)
        self.tabs.addTab(sound_scroll, "ЗВУК")
        self.tabs.addTab(photos_scroll, "ФОТО")
        self.tabs.addTab(self.faders_tab, "ФЕЙДЕРЫ")
        self.tabs.addTab(self.output_tab, "ВЫВОД")
        self.tabs.addTab(self.presets_tab, "ПРЕСЕТЫ")
        self.tabs.addTab(self.triggers_tab, "ТРИГГЕРЫ")
        self.tabs.addTab(self.log_tab, "ЖУРНАЛ")
        sv.addWidget(self.tabs)
        reset = QPushButton("↺")                         # сброс вкладки ФЕЙДЕРЫ — в строке вкладок (место по высоте)
        reset.setToolTip("СБРОСИТЬ НАСТРОЙКИ вкладки ФЕЙДЕРЫ — фейдеры, переключатели, LFO и провода к заводскому "
                         "состоянию (банки и таблица триггеров не меняются)")
        reset.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        reset.clicked.connect(self.faders_tab._reset)
        self.tabs.setCornerWidget(reset)
        self.tabs.currentChanged.connect(lambda i: reset.setVisible(self.tabs.widget(i) is self.faders_tab))
        self.shutter_w = Shutter(self.view)              # шторка с правилами — при первом открытии ВЫВОДА
        self._shutter_done = False
        self.shutter_btn = PlateButton("down", w=46, h=20, parent=self.view)   # вызов шторки — сверху по центру
        self.shutter_btn.setToolTip("ШТОРКА — правила подключения и руководство смены (ещё раз — поднять)")
        self.shutter_btn.clicked.connect(self.toggle_shutter)
        self.shutter_w.closed.connect(lambda: self.shutter_btn.setIcon("down"))
        self.view.top_btn = self.shutter_btn
        self.tabs.currentChanged.connect(self._tab_changed)
        reset.setVisible(False)
        self.scan = Scanlines(screen) if settings["theme_effects"] else None
        screen.setMinimumWidth(600)
        right.addWidget(screen, 1)

        # два фейдербанка, у каждого своя крышка: левый — триггеры (под кадром), правый — глобальные (под консолью)
        self.lid_l = Lid(version=VERSION)
        self.lid_l.clicked.connect(lambda: self.toggle_bank("l"))
        self.bank_l = TriggerBank(params, self.patch)
        self.bank_l.setFixedHeight(BANK_H)
        self.bank_l.manual.connect(self.manual_trigger)
        self.lid_r = CutHandle("ОТСЕК УПРАВЛЕНИЯ", "", "N")
        self.lid_r.clicked.connect(lambda: self.toggle_bank("r"))
        self.bank_r = GlobalBank(params, self.patch)
        self.bank_r.setFixedHeight(BANK_H)
        self.lid_r.setFixedHeight(self.lid_l.height())
        for col, lid, bank in ((left, self.lid_l, self.bank_l), (right, self.lid_r, self.bank_r)):
            box = QVBoxLayout()                            # крышка вплотную к банку
            box.setSpacing(0)
            box.addWidget(lid)
            box.addWidget(bank)
            col.addLayout(box)
        mid.addLayout(left, 7)
        mid.addLayout(right, 4)
        root.addLayout(mid, 1)
        body.add_hole(self.topbar)
        body.add_hole(self.view)
        body.add_hole(screen)
        body.add_hole(self.lid_l, self.bank_l)
        body.add_hole(self.lid_r, self.bank_r)
        self.set_bank("l", bool(settings.v.get("bank_open_l", settings["bank_open"])))
        self.set_bank("r", bool(settings.v.get("bank_open_r", settings["bank_open"])))
        self.patch.raise_()
        if params.current:
            self.preset_lbl.setText(f"пресет: {params.current}")

        params.changed.connect(self._param)
        self._param("sync_ms")
        self.sound_tab.devices.activated.connect(lambda i: self.select_device(self._device_ids[i]))
        self.refresh_devices()
        cfg = settings["trigger_config"]
        if cfg and cfg in params.trigger_names(settings["cache_dir"]):
            self.triggers_tab.load_cfg(cfg)

        for key, fn in (("Ctrl+R", self.reload_theme), ("Ctrl+S", self.save_all), ("Ctrl+Z", self.undo_bank)):
            QShortcut(QKeySequence(key), self, activated=fn)
        self._fps_n, self._fps_t, self.fps = 0, time.perf_counter(), 0.0
        self.ui_timer = QTimer(self, timeout=self.tick)
        self.ui_timer.start(33)
        self.gl_timer = QTimer(self, timeout=self.frame)
        self.gl_timer.setTimerType(Qt.PreciseTimer)
        self.gl_timer.start(16)

        geo = settings["window_geometry"]
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))

    # ------------------------------------------------------------- верх корпуса
    def _top_bar(self):
        """Верхняя полоса — узкая, в одну строку; группы разделены тонкими линиями."""
        top = QHBoxLayout()
        top.setSpacing(14)

        def sep():                                       # равные промежутки: растяжка · линия · растяжка
            top.addStretch(1)
            top.addWidget(self._vsep())
            top.addStretch(1)

        def group(*items, spacing=6, vertical=False):
            lay = QVBoxLayout() if vertical else QHBoxLayout()
            lay.setSpacing(spacing)
            for it in items:
                if isinstance(it, QWidget):
                    lay.addWidget(it)
                else:
                    lay.addLayout(it)
            return lay

        # SMENA, под ним глаз и ЛОМО · VJ
        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = engrave("SMENA", "brand")
        name.setToolTip(f"SMENA {VERSION} · ЛОМО · VJ — живой визуал из элементов фотографий под музыку")
        brand.addWidget(name)
        sub = QHBoxLayout()
        sub.setSpacing(6)
        eye = QLabel()
        pm = QPixmap(str(THEME.dir / THEME.textures.get("eye", ""))) if THEME.textures.get("eye") else QPixmap()
        if not pm.isNull():
            eye.setPixmap(pm.scaledToHeight(18, Qt.SmoothTransformation))
        sub.addWidget(eye)
        sub.addWidget(engrave("ЛОМО · VJ", "engrave_red"))
        sub.addStretch()
        brand.addLayout(sub)
        top.addLayout(brand)
        sep()

        src = QVBoxLayout()
        src.setSpacing(2)
        src.addWidget(engrave("ЗВУК · ИСТОЧНИК", "engrave_dim"))
        self.top_devices = QComboBox()
        self.top_devices.setFixedWidth(210)
        self.top_devices.setToolTip("откуда брать звук: системный вывод (loopback) или вход звуковой карты")
        self.top_devices.activated.connect(lambda i: self.select_device(self._device_ids[i]))
        src.addWidget(self.top_devices)
        top.addLayout(src)
        sep()

        # эквалайзер выхода и громкость — те же значения, что на вкладке ЗВУК
        self.eq_knobs = []
        eqs = []
        st = self.settings
        for i, (name, f) in enumerate((("SUB", "100 Гц"), ("MID", "1 кГц"), ("HI", "8 кГц"))):
            k = Knob(-12, 12, 0, 0.5, label=name, unit="дБ", size=24, ring=True, compact="under", text_w=60,
                     hint=f"эквалайзер выхода, {f}: ±12 дБ — звук SMENA (режим «файл») и запись REC; "
                          "на триггеры не влияет")
            k.set_value(float(st["eq"][i]), emit=False)
            k.valueChanged.connect(lambda x, i=i: self.sound_tab.eq[i].set_value(x))
            self.eq_knobs.append(k)
            eqs.append(k)
        self.vol_knob = Knob(0, 100, 100, 1, label="VOL", unit="%", size=24, ring=True, compact="under", text_w=60,
                             lamp=True, hint="общая громкость выхода SMENA (режим «файл») и записи REC; лампочка: "
                                             "красная — звук выключен (0), зелёная — тем ярче, чем громче")
        self.vol_knob.set_value(float(st["volume"]), emit=False)
        self.vol_knob.valueChanged.connect(lambda x: self.sound_tab.vol.set_value(x))
        top.addLayout(group(*eqs, self.vol_knob, spacing=0))
        sep()

        self.sync_ring = Knob(-200, 200, 0, 1, label="ЗАДЕРЖКА", unit="мс", size=26, ring=True, compact=True,
                              text_w=70, hint="ЗАДЕРЖКА — компенсация задержки звука: крутите, пока вспышки не совпадут "
                                              "с бочкой; + — визуал раньше")
        self.sync_ring.valueChanged.connect(lambda x: self.params.set("sync_ms", x))
        self.fx_ring = Knob(0, 200, 100, 1, label="FX", unit="%", size=26, ring=True, compact=True,
                            hint="FX — общий множитель силы всех движений от триггеров (сдвиги, повороты, встряски, "
                                 "отскоки). Это та же ручка, что раньше была в банке")
        self.fx_ring.valueChanged.connect(lambda x: self.params.set("fx", x))
        sync_box = QFrame()                              # ЗАДЕРЖКА и FX — одна группа в рамке
        sync_box.setObjectName("KnobGroup")
        sb = QHBoxLayout(sync_box)
        sb.setContentsMargins(6, 2, 6, 2)
        sb.setSpacing(2)
        sb.addWidget(self.sync_ring)
        sb.addWidget(self.fx_ring)
        top.addWidget(sync_box)
        sep()

        first = PlateButton("first", w=48, h=34)
        first.setToolTip("В НАЧАЛО — к первой фотографии папки (Home)")
        first.clicked.connect(self.go_first)
        self.play_btn = PlateButton("play", w=66, h=34, checkable=True)
        self.play_btn.setToolTip("ПУСК / СТОП — остановить или продолжить показ (Пробел). Горит — идёт показ, "
                                 "на стопе кадр замирает")
        self.play_btn.setChecked(True)
        self.play_btn.toggled.connect(self.set_playing)
        fwd = PlateButton("next", w=48, h=34)
        fwd.setToolTip("ВПЕРЁД — следующее фото (→), сменится на ближайшей сильной доле")
        fwd.clicked.connect(self.go_next)
        top.addLayout(group(first, self.play_btn, fwd, spacing=4))
        sep()

        self.counter = FrameCounter()
        self.counter.setFixedSize(124, 36)
        top.addLayout(group(button("◀", "◀ предыдущее фото (←)", self.go_prev, w=30, h=34), self.counter,
                            button("▶", "▶ следующее фото (→) — сменится на ближайшей сильной доле", self.go_next,
                                   w=30, h=34), spacing=4))
        sep()

        bpm = QVBoxLayout()
        bpm.setSpacing(0)
        self.bpm_label = engrave("---.-", "digits")
        self.bpm_label.setToolTip("темп трека, BPM; полоски — доли такта, яркая — текущая")
        bpm.addWidget(self.bpm_label, 0, Qt.AlignRight)
        self.top_beats = BeatIndicator("body")
        bpm.addWidget(self.top_beats, 0, Qt.AlignRight)
        top.addLayout(bpm)
        top.addWidget(engrave("BPM", "engrave_dim"), 0, Qt.AlignVCenter)
        top.addLayout(group(button("TAP", "TAP — настучать темп (клавиша T), нужно 4+ удара", self.tap, w=64, h=22),
                            button("RESET", "RESET — сбросить настуканный темп, вернуть авто-BPM", self.tap_reset,
                                   w=64, h=22), spacing=4, vertical=True))
        sep()

        self.hud_btn = button("HUD", "HUD — служебные подписи поверх превью (клавиша H); на HDMI не идут",
                              self.set_hud, w=52, h=34, checkable=True)
        self.hud_btn.blockSignals(True)                  # видоискателя ещё нет — HUD ставит он сам
        self.hud_btn.setChecked(bool(self.settings["hud"]))
        self.hud_btn.blockSignals(False)
        sv_col = QVBoxLayout()
        sv_col.setSpacing(1)
        sv_col.addWidget(button("SAVE", "SAVE — сохранить всё: все ручки, LFO, провода и переходы — в текущий пресет "
                                        "(подпись снизу), таблицу триггеров — в её файл (Ctrl+S). Имя спрашивается, "
                                        "только если пресет ещё не выбран", self.save_all, w=64, h=30))
        self.preset_lbl = engrave("пресет —", "engrave_dim")
        self.preset_lbl.setToolTip("текущий пресет — в него пишет SAVE")
        sv_col.addWidget(self.preset_lbl, 0, Qt.AlignHCenter)
        self.params.preset_changed.connect(lambda n: self.preset_lbl.setText(f"пресет: {n}" if n else "пресет —"))
        self.rec_btn = PlateButton("", "REC", w=96, h=34, checkable=True, lamp=True)
        self.rec_btn.setToolTip("REC — запись того, что идёт на HDMI, в mp4 со звуком; повторное нажатие — стоп. "
                                "Лампочка горит, пока идёт запись. Файлы: Видео / SMENA")
        self.rec_btn.toggled.connect(self.set_rec)
        top.addLayout(group(self.hud_btn, sv_col, self.rec_btn, spacing=10))
        return top

    @staticmethod
    def _vsep():
        f = QFrame()
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {THEME.colors.get('olive', '#3e3c1c')};")
        return f

    def _overlay_panel(self):
        """ВЕРХНЕЕ ФОТО — в чёрной полосе слева от картинки в видоискателе: ВКЛ, ФАЙЛ, ДЕРЖАТЬ / ПРОЯВЛ. / РАЗМЕР."""
        from smena.triggers_table import SCENE_BY_KEY
        panel = QWidget()
        panel.setObjectName("OverlayPanel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(6, 10, 4, 10)
        v.setSpacing(6)
        title = engrave("ВЕРХНЕЕ\nФОТО", "engrave_dim")
        title.setAlignment(Qt.AlignLeft)
        v.addWidget(title)
        self.ov_btn = button("ВКЛ", "ВЕРХНЕЕ ФОТО — вкл / выкл картинку поверх показа; через «ДЕРЖАТЬ» секунд "
                                    "выключится сама (0 — пока включено)", lambda x: self.params.set("ov.on", x),
                             w=86, h=26, checkable=True)
        v.addWidget(self.ov_btn)
        v.addWidget(button("ФАЙЛ…", "картинка для верхнего фото (PNG с прозрачностью — логотип, надпись; "
                                    "или любое фото)", lambda: self.faders_tab._choose_overlay(), w=86, h=26))
        self.ov_knobs = {}
        for key in ("ov.hold", "ov.fade", "ov.size"):
            g = SCENE_BY_KEY[key]
            k = Knob(g.lo, g.hi, g.default, g.step, label=g.label, unit=g.unit, size=22, ring=True, compact=True,
                     hint=g.hint)
            k.set_value(self.params[key], emit=False)
            k.valueChanged.connect(lambda x, key=key: self.params.set(key, x))
            self.ov_knobs[key] = k
            v.addWidget(k)
        self.ov_name = engrave("", "engrave_dim")
        self.ov_name.setWordWrap(True)
        self.ov_name.setFixedWidth(88)
        v.addWidget(self.ov_name)
        v.addStretch()
        self.params.changed.connect(self._overlay_param)
        for k in ("ov.on", "ov.file"):
            self._overlay_param(k)
        return panel

    def _overlay_param(self, k):
        if k == "ov.on":
            self.ov_btn.blockSignals(True)
            self.ov_btn.setChecked(bool(self.params["ov.on"]))
            self.ov_btn.blockSignals(False)
        elif k in self.ov_knobs:
            self.ov_knobs[k].set_value(self.params[k], emit=False)
        elif k == "ov.file":
            f = self.params["ov.file"]
            name = f.replace("\\", "/").split("/")[-1] if f else "файл не выбран"
            self.ov_name.setText(name[:28])

    # ------------------------------------------------------------- фейдербанк
    def toggle_shutter(self):
        if self.shutter_w.isVisible():
            self.shutter_w.slide_out()
        else:
            self.shutter_w.slide_in()
            self.shutter_btn.setIcon("up")
            self.shutter_btn.raise_()

    def _tab_changed(self, i):
        if self.tabs.widget(i) is self.output_tab and not self._shutter_done:
            self._shutter_done = True
            self.toggle_shutter()
            self.engine.log_event("ВЫВОД: шторка с правилами подключения")

    def sync_eq_knobs(self):
        """Вкладка ЗВУК изменила эквалайзер / громкость — повернуть ручки наверху."""
        st = self.settings
        for k, v in zip(getattr(self, "eq_knobs", []), st["eq"]):
            k.set_value(float(v), emit=False)
        if hasattr(self, "vol_knob"):
            self.vol_knob.set_value(float(st["volume"]), emit=False)

    def set_bank(self, side, on):
        bank, lid = (self.bank_l, self.lid_l) if side == "l" else (self.bank_r, self.lid_r)
        bank.setVisible(on)
        lid.set_open(on)
        self.settings.v[f"bank_open_{side}"] = on
        self.body.update()

    def toggle_bank(self, side):
        bank = self.bank_l if side == "l" else self.bank_r
        self.set_bank(side, not bank.isVisible())
        self.settings.save()
        self.engine.log_event(("левый" if side == "l" else "правый") + " фейдербанк: "
                              + ("открыт" if bank.isVisible() else "закрыт"))

    def _bank_ghosts(self):
        """«Призраки» LFO на фейдерах банков (глобальные и СИЛА каналов)."""
        off = self.mod.offsets
        if not off and not getattr(self, "_ghosted", None):
            return
        shown = set()
        for key in off:
            if key.startswith("t") and key.endswith(".gain"):
                f = self.bank_l.channels[int(key[1:-5])].gain
            elif key in self.bank_r.globals and key != "pwm":
                f = self.bank_r.globals[key].fader
            else:
                continue
            f.auto_value = self.mod.v(key)
            f.update()
            shown.add(f)
        for f in getattr(self, "_ghosted", set()) - shown:
            f.auto_value = None
            f.update()
        self._ghosted = shown

    def undo_bank(self):
        if self.params.undo_bank():
            self.engine.log_event("фейдербанк: отмена СБРОС / RANDOM")

    # ------------------------------------------------------------------ звук
    def refresh_devices(self):
        devs = self.engine.list_devices()
        self._device_ids = [None] + [d[0] for d in devs]
        labels = [self.engine.default_label()] + [d[1] for d in devs]
        cur = self.settings["audio_device"]
        if cur not in self._device_ids:
            cur = None
        for combo in (self.top_devices, self.sound_tab.devices):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(labels)
            combo.setCurrentIndex(self._device_ids.index(cur))
            combo.blockSignals(False)

    def select_device(self, dev_id):
        self.settings["audio_device"] = dev_id
        self.settings.save()
        i = self._device_ids.index(dev_id)
        for combo in (self.top_devices, self.sound_tab.devices):
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
        self.engine.start(dev_id)

    def tap(self):
        n = self.engine.beat.tap(time.perf_counter())
        if n >= 4:
            self.engine.log_event(f"tap: {self.engine.beat.bpm:.1f} BPM")

    def tap_reset(self):
        self.engine.beat.set_auto()
        self.engine.log_event("tap сброшен — авто-BPM")

    def downbeat(self):
        self.engine.beat.align_downbeat(time.perf_counter())
        self.engine.log_event("сильная доля выровнена")

    # ---------------------------------------------------------------- показ
    def go_first(self):
        self.clock.goto(0)

    def go_prev(self):
        if self.clock.master:
            self.clock.goto(self.clock.master.index - 1)

    def go_next(self):
        self.clock.shutter()

    def set_playing(self, on):
        self.clock.set_paused(not on)
        self.play_btn.setIcon("play" if on else "stop")
        self.engine.log_event("ПУСК" if on else "СТОП — кадр замер")

    def save_all(self):
        """SAVE: пресет (все ручки) + таблица триггеров (её файл в кеше набора)."""
        n = self.presets_tab.save()
        if not n:
            return
        cfg = self.triggers_tab.cfg.currentText()
        if cfg:
            self.triggers_tab.save_cfg()
        else:
            self.params.save_triggers(self.settings["cache_dir"], n)
            self.settings["trigger_config"] = n
            self.triggers_tab.refresh_cfg()
            cfg = n
        self.settings.save()
        self.engine.log_event(f"SAVE: пресет «{n}», таблица триггеров «{cfg}»")

    def set_rec(self, on):
        if on:
            try:
                self.recorder.start(self.view.gl.render_size)
            except Exception as e:
                self.engine.log_event(f"REC: не запустилась — {e}")
                self.rec_btn.blockSignals(True)
                self.rec_btn.setChecked(False)
                self.rec_btn.blockSignals(False)
                return
            self.engine.rec_tap = self.recorder.audio
        else:
            self.engine.rec_tap = None
            self.recorder.stop()
            self.rec_btn.setText("REC")

    # ------------------------------------------------------------------ вывод
    def set_output(self, on):
        if on:
            if self.output_win is None:
                from smena.render.output import OutputWindow
                self.output_win = OutputWindow(self.view.gl)
                self.output_win.closed.connect(self._output_closed)
            self.place_output()
        elif self.output_win:
            w, self.output_win = self.output_win, None
            w.closed.disconnect()
            w.close()
            w.deleteLater()

    def _output_closed(self):
        self.output_win = None
        self.output_tab.show_btn.blockSignals(True)
        self.output_tab.show_btn.setChecked(False)
        self.output_tab.show_btn.blockSignals(False)

    def place_output(self):
        if self.output_win:
            self.output_win.place(int(self.settings["output_monitor"]), bool(self.settings["output_fullscreen"]))

    def set_blackout(self, on):
        r = self.view.gl.renderer
        if r:
            r.blackout = on
        self.engine.log_event("BLACKOUT" if on else "BLACKOUT снят")

    # -------------------------------------------- кадр GL (вызывает GLPreview)
    def overlay_args(self, renderer):
        renderer.set_overlay(self.params["ov.file"])
        return self.overlay.alpha, self.mod.v("ov.size") / 100.0

    def brightness(self):
        return self.clock.bright

    def after_render(self, renderer):
        """Выходной проход (сетка, маска, яркость) → запись REC → снимок для холста калибровки."""
        now = time.perf_counter()
        renderer.output(self.mapping, self.brightness())
        self.recorder.tick(renderer, now)
        if self.output_tab.isVisible() and now - self._snap_t > 0.3:
            self._snap_t = now
            self.output_tab.canvas.set_snapshot(*renderer.snapshot(self.mapping, self.brightness()))

    def frame(self):
        """60 Гц: LFO → мастер-клок → действия триггеров → подгрузка фото → превью и окно вывода."""
        now = time.perf_counter()
        self.mod.update(self.clock.beat, now)
        if not self.clock.paused:
            self.clock.update(now)
            self.actions.update(now)
        self.overlay.update(now)
        need = self.clock.needed()
        for e in need:
            self.loader.request(e)
        self.loader.keep_only(need)
        self.view.gl.update()
        if self.output_win:
            self.output_win.update()

    def open_editor(self):
        """Редактор элементов — отдельное окно (можно на второй монитор, показ не прерывается)."""
        from smena.editor.window import EditorWindow
        if getattr(self, "editor", None) is None or not self.editor.isVisible():
            self.editor = EditorWindow(self)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def set_render_size(self, size):
        self.clock.set_size(size)
        self.view.set_render_size(size)

    def manual_trigger(self, n):
        self.engine.triggers.manual(n)

    def set_hud(self, on):
        self.view.hud.show_hud = on
        self.view.hud.update()
        self.settings["hud"] = on
        self.settings.save()

    def reload_theme(self):
        THEME.load(self.app, self.settings["theme"])
        for w in self.findChildren(QWidget):
            w.update()
        self.engine.log_event(f"тема перезагружена: {THEME.name}")

    def library_changed(self, entries):
        self.clock.set_library(entries)
        self.counter.set(None, len(self.clock.entries))
        has_new = any(e.ready for e in entries)
        if not self.clock.entries:
            self.view.hud.message = "нет фото с кешем — вкладка ФОТО → «Подготовить фото»"
        elif not has_new:
            self.view.hud.message = "в выбранной папке нет фото с кешем — показ продолжается"
        else:
            self.view.hud.message = ""

    def _gl_ready(self, renderer):
        self.output_tab.set_renderer(renderer)
        self.engine.log_event(f"GL_RENDERER: {renderer}")

    def _param(self, k):
        if k == "sync_ms":
            self.engine.beat.sync_ms = float(self.params["sync_ms"])
            self.sync_ring.set_value(self.params["sync_ms"], emit=False)
            self.settings["sync_ms"] = self.params["sync_ms"]
        elif k == "fx":
            self.fx_ring.set_value(self.params["fx"], emit=False)

    def keyPressEvent(self, e):
        # сюда доходят только клавиши, не занятые полем ввода; вторые коды — те же клавиши в русской раскладке
        k, mods = e.key(), e.modifiers()
        if mods & ~Qt.KeypadModifier:
            super().keyPressEvent(e)
        elif k in (Qt.Key_T, 0x0415):
            self.tap()
        elif k in (Qt.Key_H, 0x0420):
            self.hud_btn.toggle()
        elif k in (Qt.Key_B, 0x0418):
            self.toggle_bank("l")
        elif k in (Qt.Key_N, 0x0422):
            self.toggle_bank("r")
        elif k in (Qt.Key_M, 0x042C):
            self.sound_tab.toggle_mute()
        elif k == Qt.Key_Space:
            self.play_btn.toggle()
        elif k == Qt.Key_Left:
            self.go_prev()
        elif k == Qt.Key_Right:
            self.go_next()
        elif k == Qt.Key_Home:
            self.go_first()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------ такт UI
    def tick(self):
        now = time.perf_counter()
        eng = self.engine
        f = eng.features
        bt = eng.beat
        b = bt.position(now)
        self.bpm_label.setText(f"{bt.grid_bpm:5.1f}")
        self.top_beats.set(b["in_bar"], b["phase"], bt.conditional)

        # каналы: индикатор — уровень признака, лампа — срабатывание / активность
        tr = eng.triggers
        for t in TRIGGERS:
            n = t.n
            x = tr.levels.get(n, 0.0)
            on = self.params[f"t{n}.on"]
            flash = tr.flash[n] > self._flash_seen.get(n, -1e9)
            if flash:
                self._flash_seen[n] = tr.flash[n]
            ch = self.bank_l.channels[n]
            if self.bank_l.isVisible():
                ch.meter.set_value(x)
                if flash:
                    ch.lamp.flash()
                ch.lamp.set_level((1.0 if n in tr.active else 0.35 * x) if on else 0.0)
        self._bank_ghosts()
        pwm = self.bank_r.globals["pwm"].fader
        if pwm.auto_value != self.actions.pwm_display:
            pwm.auto_value = self.actions.pwm_display
            pwm.update()

        self.sound_tab.tick(now)
        self.log_tab.tick()
        self.patch.tick()
        if self.faders_tab.isVisible():
            self.faders_tab.tick(self.mod)
        if self.recorder.active:
            t = int(self.recorder.elapsed)
            self.rec_btn.setText(f"{t // 60:02d}:{t % 60:02d}")
        elif self.rec_btn.isChecked():                 # запись остановилась сама
            self.rec_btn.setChecked(False)

        # fps превью
        gl = self.view.gl
        if now - self._fps_t >= 1.0:
            self.fps = (gl.frames - self._fps_n) / (now - self._fps_t)
            self._fps_n, self._fps_t = gl.frames, now
            self.output_tab.tick(self.fps)
        clk = self.clock
        self.counter.set(clk.master.index + 1 if clk.master else None, len(clk.entries))
        hud = self.view.hud
        idle = self.clock.master is None
        if idle or hud.idle:
            hud.idle = idle
            hud.update()
        if hud.show_hud:
            hud.info = {"in_bar": b["in_bar"], "bar": b["bar"], "bpm": f"{bt.grid_bpm:.1f}",
                        "fps": round(self.fps), **clk.hud()}
            hud.update()

    def closeEvent(self, e):
        if not os.environ.get("SMENA_SMOKE"):             # пробный запуск (окно за краем экрана) — не запоминать
            self.settings["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()
            self.settings.save()
        if self.recorder.active:
            self.set_rec(False)
        if self.output_win:
            self.set_output(False)
        if getattr(self, "editor", None):
            self.editor.close()                  # остановить SAM-сервер
        self.engine.stop()
        super().closeEvent(e)
