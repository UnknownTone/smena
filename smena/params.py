"""Значения фейдеров, пресеты и таблицы триггеров.

Ключи: `t{n}.on`, `t{n}.gain`, `t{n}.sens` — каналы триггеров (ТАБЛИЦА ТРИГГЕРОВ); GLOBALS — глобальные фейдеры
банка; SCENE_FADERS — вкладка ФЕЙДЕРЫ; `lfo{i}.*` и `lfo.wires` — генераторы и провода; `ov.*` — верхнее фото.

Хранятся раздельно (так удобнее собирать пресеты разным людям):
  пресет  — всё, кроме каналов триггеров и сдвига бита: %APPDATA%\\SMENA\\presets\\*.json;
  таблица триггеров — каналы 20 триггеров: <кеш набора>\\triggers\\*.json (у каждого набора фото свои).
Изменение значения рассылается сигналом `changed(key)` — все виды одного значения синхронны.
"""
import copy
import json
import logging
import random
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from smena.settings import PRESET_DIR
from smena.triggers_table import GLOBALS, N_LFO, SCENE_FADERS, TRIGGERS

log = logging.getLogger("smena.params")

DEFAULTS = {}
for _t in TRIGGERS:
    DEFAULTS.update({f"t{_t.n}.on": True, f"t{_t.n}.gain": 100.0, f"t{_t.n}.sens": 100.0})
for _g in GLOBALS + SCENE_FADERS:
    DEFAULTS[_g.key] = _g.default
for _i in range(1, N_LFO + 1):
    DEFAULTS.update({f"lfo{_i}.wave": 0, f"lfo{_i}.rate": 40.0, f"lfo{_i}.depth": 50.0, f"lfo{_i}.sync": True})
DEFAULTS.update({"lfo.wires": [], "ov.on": False, "ov.file": "",
                 "img.smooth": False,      # ОБРАЗ: резко (сразу) / плавно (со следующего фото, мягко)
                 "img.alpha": False,       # ОБРАЗ: прозрачность элементов при СИЛЕ ЭФФ. / ОРИГИНАЛЕ (выкл — целиком)
                 "tr.on": True})           # МОРФИНГ: выкл — смена кадров как в первых версиях

TRIGGER_KEYS = [k for k in DEFAULTS if k.startswith("t") and k[1:2].isdigit()]
# в пресет не входят: каналы триггеров (свой файл), сдвиг бита (зависит от машины), включение верхнего фото (действие)
PRESET_KEYS = [k for k in DEFAULTS if k not in TRIGGER_KEYS and k not in ("sync_ms", "ov.on")]
BANK_KEYS = TRIGGER_KEYS + [g.key for g in GLOBALS if g.key != "sync_ms"]
# вкладка ФЕЙДЕРЫ: фейдеры сцены, тоглы, LFO и провода, верхнее фото (кроме включения)
SCENE_KEYS = [g.key for g in SCENE_FADERS] + ["img.smooth", "img.alpha", "tr.on", "lfo.wires", "ov.file"] + \
    [k for k in DEFAULTS if k.startswith("lfo") and k != "lfo.wires"]
FACTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "presets"


class Params(QObject):
    changed = Signal(str)
    preset_changed = Signal(str)      # имя текущего пресета (последний загруженный / сохранённый)

    def __init__(self):
        super().__init__()
        self.v = copy.deepcopy(DEFAULTS)
        self.current = None
        self._undo = None             # снимок до СБРОС / RANDOM (Ctrl+Z)
        self.rng = random.Random()

    def __getitem__(self, k):
        return self.v[k]

    def set(self, k, val):
        if self.v.get(k) != val:
            self.v[k] = val
            self.changed.emit(k)

    def apply(self, data, keys):
        for k in keys:
            if k in data:
                self.set(k, copy.deepcopy(data[k]))

    # ------------------------------------------------------------- пресеты
    @staticmethod
    def preset_names():
        if not PRESET_DIR.exists():
            return []
        return sorted(p.stem for p in PRESET_DIR.glob("*.json"))

    def save_preset(self, name):
        PRESET_DIR.mkdir(parents=True, exist_ok=True)
        data = {k: self.v[k] for k in PRESET_KEYS}
        (PRESET_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._current(name)

    def load_preset(self, name):
        data = json.loads((PRESET_DIR / f"{name}.json").read_text(encoding="utf-8"))
        self.apply({k: data.get(k, DEFAULTS[k]) for k in PRESET_KEYS}, PRESET_KEYS)
        self._current(name)

    def _current(self, name):
        self.current = name
        self.preset_changed.emit(name or "")

    @staticmethod
    def delete_preset(name):
        (PRESET_DIR / f"{name}.json").unlink(missing_ok=True)

    def reset(self):
        self.apply(DEFAULTS, PRESET_KEYS)

    def reset_scene(self):
        """«Сбросить настройки» вкладки ФЕЙДЕРЫ — заводское состояние (фейдеры, тоглы, LFO, провода)."""
        self.apply(DEFAULTS, SCENE_KEYS)

    @staticmethod
    def install_factory():
        """Заводские пресеты (slow / medium / trance) — в папку пресетов, если их там нет."""
        try:
            PRESET_DIR.mkdir(parents=True, exist_ok=True)
            for f in FACTORY_DIR.glob("*.json"):
                if not (PRESET_DIR / f.name).exists():
                    (PRESET_DIR / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            log.exception("заводские пресеты не установлены")

    # ------------------------------------------------------- таблицы триггеров
    @staticmethod
    def trigger_dir(cache_dir):
        return Path(cache_dir) / "triggers"

    @classmethod
    def trigger_names(cls, cache_dir):
        d = cls.trigger_dir(cache_dir)
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    def save_triggers(self, cache_dir, name):
        d = self.trigger_dir(cache_dir)
        d.mkdir(parents=True, exist_ok=True)
        data = {k: self.v[k] for k in TRIGGER_KEYS}
        (d / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_triggers(self, cache_dir, name):
        f = self.trigger_dir(cache_dir) / f"{name}.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        self.apply({k: data.get(k, DEFAULTS[k]) for k in TRIGGER_KEYS}, TRIGGER_KEYS)

    # ------------------------------------------------- фейдербанк: сброс и случай
    def _snapshot(self):
        self._undo = {k: copy.deepcopy(self.v[k]) for k in BANK_KEYS}

    def reset_bank(self):
        """СБРОС: каналы триггеров и глобальные фейдеры банка — по умолчанию."""
        self._snapshot()
        self.apply(DEFAULTS, BANK_KEYS)

    def randomize_bank(self):
        """RANDOM: каждый раз новый случайный набор ручек — в разумных пределах вокруг значений по умолчанию."""
        self._snapshot()
        r = self.rng
        for t in TRIGGERS:
            n = t.n
            self.set(f"t{n}.on", r.random() < 0.85)
            self.set(f"t{n}.gain", float(round(r.uniform(40, 170))))
            self.set(f"t{n}.sens", float(round(r.uniform(60, 150))))
        for g in GLOBALS:
            if g.key in ("sync_ms",):
                continue
            x = g.default + (r.uniform(g.lo, g.hi) - g.default) * 0.65
            x = g.lo + round((x - g.lo) / g.step) * g.step
            self.set(g.key, round(min(max(x, g.lo), g.hi), 6))

    def undo_bank(self):
        if self._undo:
            data, self._undo = self._undo, None
            self.apply(data, BANK_KEYS)
            return True
        return False


