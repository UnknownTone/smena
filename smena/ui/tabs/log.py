"""Вкладка ЖУРНАЛ: все действия — события программы (журнал AudioEngine: триггеры, смены фото, кнопки, REC…)
и изменения фейдеров / переключателей. Движение фейдера записывается одной строкой «было → стало», когда
фейдер отпустили (через 0.6 с тишины). Всё то же уходит в файл журнала %APPDATA%\\SMENA\\logs\\smena.log.
"""
import time
from datetime import datetime

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from smena.settings import LOG_DIR
from smena.triggers_table import GLOBALS, SCENE_FADERS, TRIGGERS

NAMES = {g.key: g.label for g in GLOBALS + SCENE_FADERS}
for _t in TRIGGERS:
    NAMES.update({f"t{_t.n}.gain": f"№{_t.n} {_t.short} СИЛА", f"t{_t.n}.sens": f"№{_t.n} {_t.short} ЧУВСТВ.",
                  f"t{_t.n}.on": f"№{_t.n} {_t.short} ВКЛ"})
NAMES.update({"img.smooth": "ОБРАЗ плавно", "img.alpha": "ОБРАЗ прозрачность", "tr.on": "МОРФИНГ",
              "ov.on": "ВЕРХНЕЕ ФОТО", "ov.file": "ВЕРХНЕЕ ФОТО файл", "lfo.wires": "провода LFO"})
for _i in range(1, 5):
    NAMES.update({f"lfo{_i}.wave": f"LFO {_i} форма", f"lfo{_i}.rate": f"LFO {_i} скорость",
                  f"lfo{_i}.depth": f"LFO {_i} глубина", f"lfo{_i}.sync": f"LFO {_i} BPM"})
QUIET = 0.6


def fmt(v):
    if isinstance(v, bool):
        return "вкл" if v else "выкл"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, list):
        return f"{len(v)} шт." if v and isinstance(v[0], list) else str(v)
    return str(v)


class LogTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        t = QLabel("ЖУРНАЛ ДЕЙСТВИЙ")
        t.setProperty("role", "title")
        row.addWidget(t)
        row.addStretch()
        self.trig = QCheckBox("срабатывания триггеров")
        self.trig.setToolTip("показывать и срабатывания триггеров (их много)")
        self.trig.setChecked(True)
        row.addWidget(self.trig)
        b = QPushButton("ОЧИСТИТЬ")
        b.setToolTip("очистить экран журнала (файл журнала не трогается)")
        b.clicked.connect(lambda: self.text.clear())
        row.addWidget(b)
        v.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(3000)
        v.addWidget(self.text, 1)
        info = QLabel(f"файл: {LOG_DIR / 'smena.log'}")
        info.setProperty("role", "dim")
        info.setStyleSheet("font-size: 10px;")
        v.addWidget(info)
        self._seq = 0
        self._pending = {}           # ключ → (было, время последнего изменения)
        self._last = dict(win.params.v)
        win.params.changed.connect(self._changed)

    def _changed(self, k):
        if k not in self._pending:
            self._pending[k] = (self._last.get(k), time.perf_counter())
        else:
            self._pending[k] = (self._pending[k][0], time.perf_counter())

    def tick(self):
        now = time.perf_counter()
        p = self.win.params
        for k, (old, t) in list(self._pending.items()):
            if now - t < QUIET:
                continue
            del self._pending[k]
            new = p[k]
            self._last[k] = new
            if new != old:
                self.win.engine.log_event(f"{NAMES.get(k, k)}: {fmt(old)} → {fmt(new)}")
        for seq, ts, text in list(self.win.engine.events):
            if seq <= self._seq:
                continue
            self._seq = seq
            if not self.trig.isChecked() and text.startswith("№"):
                continue
            self.text.appendPlainText(f"{datetime.fromtimestamp(ts):%H:%M:%S}  {text}")
