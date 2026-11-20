"""Вкладка ЗВУК: устройство, индикаторы полос и RMS, темп (авто / tap / ×2 / ÷2 / ручной / сильная доля),
сдвиг синхронизации, эквалайзер выхода (НИЗ / СЕР / ВЕРХ), громкость, «беззвучно» (журнал — вкладка ЖУРНАЛ)."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from smena.audio.capture import SILENCE_HINT_S
from smena.audio.features import BANDS
from smena.runtime import IS_MAC
from smena.ui.instruments import EqScope
from smena.ui.widgets import BeatIndicator, Fader, Meter

BAND_LABELS = {"sub": "SUB", "bass": "BASS", "lowmid": "LMID", "mid": "MID", "himid": "HMID", "high": "HIGH"}
ASIO_HINT = ("тишина > 5 с. Traktor / Reaper на ASIO не видны в loopback: выберите вход карты "
             "или виртуальный кабель (docs/build/03_AUDIO_CAPTURE.md)")
if IS_MAC:
    ASIO_HINT = ("тишина > 5 с. macOS не отдаёт звук системы напрямую: поставьте BlackHole 2ch, сделайте "
                 "«Устройство с несколькими выходами» (колонки + BlackHole) или выберите вход звуковой карты")


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


class SoundTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        eng = win.engine
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # --- устройство
        row = QHBoxLayout()
        row.addWidget(lbl("ИСТОЧНИК", "dim"))
        self.devices = QComboBox()
        self.devices.setMinimumWidth(200)
        row.addWidget(self.devices, 1)
        b = QPushButton("Обновить")
        b.clicked.connect(win.refresh_devices)
        row.addWidget(b)
        v.addLayout(row)
        frow = QHBoxLayout()
        frow.addWidget(lbl("ФАЙЛ", "dim"))
        bf = QPushButton("Файл…")
        bf.setToolTip("тестовый режим: программа сама играет аудиофайл и анализирует его")
        bf.clicked.connect(self._choose_file)
        frow.addWidget(bf)
        self.play_btn = QPushButton("▶")
        self.play_btn.setToolTip("играть / остановить тестовый файл (затем — снова захват устройства)")
        self.play_btn.clicked.connect(self._toggle_file)
        frow.addWidget(self.play_btn)
        self.file_label = lbl("", "dim")
        frow.addWidget(self.file_label, 1)
        v.addLayout(frow)
        self.status = lbl("", "dim")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        # --- полосы
        meters = QGridLayout()
        meters.setHorizontalSpacing(10)
        meters.setVerticalSpacing(2)
        self.meters = {}
        names = list(BANDS) + ["rms"]
        for i, k in enumerate(names):
            m = Meter("screen", 20)
            m.setFixedWidth(22)
            m.setMinimumHeight(110)
            self.meters[k] = m
            meters.addWidget(m, 0, i, Qt.AlignHCenter)
            meters.addWidget(lbl(BAND_LABELS.get(k, "RMS"), "dim"), 1, i, Qt.AlignHCenter)
        self.db = lbl("−∞ дБ", "dim")
        meters.addWidget(self.db, 2, len(names) - 1, Qt.AlignHCenter)
        meters.setColumnStretch(len(names), 1)
        self.meter_row = QHBoxLayout()                 # индикаторы слева, экран эквалайзера справа
        self.meter_row.addLayout(meters, 1)
        v.addLayout(self.meter_row)

        # --- темп
        tempo = QGridLayout()
        tempo.setHorizontalSpacing(6)
        self.bpm = lbl("---.-", "big")
        tempo.addWidget(self.bpm, 0, 0, 2, 1)
        self.mode = lbl("", "dim")
        tempo.addWidget(self.mode, 0, 1, 1, 3)
        self.beats = BeatIndicator("screen")
        tempo.addWidget(self.beats, 1, 1, 1, 2)
        btns = QHBoxLayout()
        for text, fn, tip in (("АВТО", lambda: eng.beat.set_auto(), "темп по звуку"),
                              ("TAP", win.tap, "нажимать в долю (клавиша T)"),
                              ("×2", lambda: eng.beat.scale(2.0), "удвоить темп"),
                              ("÷2", lambda: eng.beat.scale(0.5), "половина темпа"),
                              ("СИЛЬНАЯ", win.downbeat, "нажать на первую долю такта")):
            bt = QPushButton(text)
            bt.setToolTip(tip)
            bt.clicked.connect(fn)
            btns.addWidget(bt)
        tempo.addLayout(btns, 2, 0, 1, 4)
        man = QHBoxLayout()
        man.addWidget(lbl("ручной BPM", "dim"))
        self.manual = QDoubleSpinBox()
        self.manual.setRange(40, 300)
        self.manual.setDecimals(1)
        self.manual.setValue(120.0)
        man.addWidget(self.manual)
        bset = QPushButton("Задать")
        bset.clicked.connect(lambda: eng.beat.set_manual(self.manual.value()))
        man.addWidget(bset)
        man.addSpacing(12)
        man.addWidget(lbl("сдвиг, мс", "dim"))
        self.sync = QDoubleSpinBox()
        self.sync.setRange(-200, 200)
        self.sync.setDecimals(0)
        self.sync.setSingleStep(5)
        self.sync.setToolTip("компенсация задержки: + — визуал раньше")
        self.sync.valueChanged.connect(lambda x: win.params.set("sync_ms", float(x)))
        man.addWidget(self.sync)
        man.addStretch()
        tempo.addLayout(man, 3, 0, 1, 4)
        v.addLayout(tempo)

        # --- выход: эквалайзер, громкость, беззвучно (звук SMENA в режиме «файл» и звук записи REC) — свой экран
        self.eq_scope = EqScope(win.engine.eq)
        self.eq_scope.setFixedSize(420, 300)
        out = QHBoxLayout(self.eq_scope)
        out.setContentsMargins(10, 160, 10, 8)
        out.setSpacing(4)
        st = win.settings
        self.eq = []
        for i, (name, f) in enumerate((("SUB", "100 Гц"), ("MID", "1 кГц"), ("HI", "8 кГц"))):
            fd = Fader(-12, 12, 0, 0.5, label=f"EQ {name}", unit="дБ", variant="screen",
                       hint=f"эквалайзер, {f}: ±12 дБ — звук, который играет SMENA (файл), и звук записи REC; "
                            "на триггеры не влияет")
            fd.setFixedSize(42, 100)
            fd.set_value(float(st["eq"][i]), emit=False)
            fd.valueChanged.connect(self._eq)
            self.eq.append(fd)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(fd, 0, Qt.AlignHCenter)
            col.addWidget(lbl(name, "dim"), 0, Qt.AlignHCenter)
            out.addLayout(col)
        out.addSpacing(10)
        self.vol = Fader(0, 100, 100, 1, label="ГРОМКОСТЬ", unit="%", variant="screen",
                         hint="общая громкость выхода SMENA (режим «файл») и записи REC")
        self.vol.setFixedSize(42, 100)
        self.vol.set_value(float(st["volume"]), emit=False)
        self.vol.valueChanged.connect(self._eq)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.vol, 0, Qt.AlignHCenter)
        col.addWidget(lbl("VOL", "dim"), 0, Qt.AlignHCenter)
        out.addLayout(col)
        side = QVBoxLayout()
        self.mute = QPushButton("БЕЗЗВУЧНО")
        self.mute.setCheckable(True)
        self.mute.setProperty("role", "warn")
        self.mute.setChecked(bool(st["mute"]))
        self.mute.setToolTip("БЕЗЗВУЧНО — выключить звук на выходе (анализ продолжает слушать). Клавиша M")
        self.mute.toggled.connect(self._eq)
        side.addWidget(self.mute)
        b0 = QPushButton("EQ 0 дБ")
        b0.setToolTip("эквалайзер — все полосы на 0 дБ")
        b0.clicked.connect(lambda: [f.set_value(0.0) for f in self.eq])
        side.addWidget(b0)
        note = lbl("звук SMENA (файл) и REC; Traktor / foobar — громкость в плеере", "dim")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 10px;")
        side.addWidget(note)
        side.addStretch()
        out.addLayout(side, 1)
        v.addSpacing(10)
        eq_row = QHBoxLayout()                         # экран эквалайзера — внизу вкладки
        eq_row.addWidget(self.eq_scope)
        eq_row.addStretch()
        v.addLayout(eq_row)
        self._eq()

        v.addStretch()                 # журнал событий — вкладка ЖУРНАЛ
        win.params.changed.connect(self._param)
        self._param("sync_ms")

    def _eq(self, *_):
        st = self.win.settings
        st["eq"] = [f.value for f in self.eq]
        st["volume"] = self.vol.value
        st["mute"] = self.mute.isChecked()
        st.save()
        self.win.engine.eq.set(*st["eq"], st["volume"] / 100.0, st["mute"])
        self.eq_scope.update()
        if hasattr(self.win, "sync_eq_knobs"):
            self.win.sync_eq_knobs()

    def toggle_mute(self):
        self.mute.toggle()

    def _choose_file(self):
        start = self.win.settings.v.get("test_file") or ""
        path, _ = QFileDialog.getOpenFileName(self, "Тестовый аудиофайл", str(Path(start).parent) if start else "",
                                              "Аудио (*.mp3 *.flac *.wav *.ogg *.m4a *.aac *.aiff);;Все файлы (*)")
        if path:
            self.win.settings["test_file"] = str(Path(path))
            self.win.settings.save()
            self.win.engine.start_file(path)

    def _toggle_file(self):
        eng = self.win.engine
        if eng.file_path and eng.running:
            eng.start(self.win.settings["audio_device"])
        else:
            f = self.win.settings.v.get("test_file")
            if f and Path(f).is_file():
                eng.start_file(f)
            else:
                self._choose_file()

    def _param(self, k):
        if k == "sync_ms":
            self.sync.blockSignals(True)
            self.sync.setValue(self.win.params["sync_ms"])
            self.sync.blockSignals(False)

    def tick(self, now):
        eng = self.win.engine
        f = eng.features
        for k in BANDS:
            self.meters[k].set_value(f.level[k])
        self.meters["rms"].set_value((f.rms_db + 60.0) / 60.0)
        self.db.setText("−∞ дБ" if f.rms_db < -89 else f"{f.rms_db:.0f} дБ")

        bt = eng.beat
        b = bt.position(now)
        self.bpm.setText(f"{bt.grid_bpm:5.1f}")
        if bt.manual_bpm > 0:
            mode = "ручной"
        elif bt.conditional:
            mode = "условная сетка 120 (темп не найден)"
        else:
            mode = f"авто · уверенность {bt.confidence:.2f}"
        self.mode.setText(f"{mode} · такт {b['bar']}")
        self.beats.set(b["in_bar"], b["phase"], bt.conditional)

        if eng.error:
            self.status.setProperty("role", "warn")
            self.status.setText(f"ошибка захвата: {eng.error}")
        elif eng.stalled(now):
            self.status.setProperty("role", "warn")
            self.status.setText("нет данных от устройства — проверьте подключение или выберите другое")
        elif eng.silence_s(now) > SILENCE_HINT_S:
            self.status.setProperty("role", "warn")
            self.status.setText(ASIO_HINT)
        else:
            self.status.setProperty("role", "dim")
            self.status.setText(("сигнал есть · " if not f.silent else "тишина · ") + (eng.device_name or ""))
        self.status.style().polish(self.status)

        playing = bool(eng.file_path and eng.running)
        self.play_btn.setText("■" if playing else "▶")
        f = self.win.settings.v.get("test_file")
        if playing:
            mm = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
            self.file_label.setText(f"{Path(eng.file_path).name} · {mm(eng.file_pos)} / {mm(eng.file_dur)}")
        else:
            self.file_label.setText(Path(f).name if f else "не выбран")

