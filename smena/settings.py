"""Пути программы и настройки: <папка данных>/settings.json (Windows — %APPDATA%/SMENA, macOS —
~/Library/Application Support/SMENA; docs/build/04_PACKAGING.md §3, §5)."""
import json
import logging
from pathlib import Path

from smena.runtime import PKG_DIR, ROOT, data_dir, default_prep_python

log = logging.getLogger("smena")

THEMES_DIR = PKG_DIR / "ui" / "theme"
SAMPLE_CACHE = ROOT / "data" / "sample_cache"

DATA_DIR = data_dir()
SETTINGS_FILE = DATA_DIR / "settings.json"
PRESET_DIR = DATA_DIR / "presets"
LOG_DIR = DATA_DIR / "logs"

DEFAULTS = {
    "photos_dir": str(SAMPLE_CACHE),   # на новой машине — демо-набор; дальше — выбор на вкладке ФОТО
    "cache_dir": str(SAMPLE_CACHE),
    "prep_python": default_prep_python(),
    "prep_scripts": str(ROOT / "tools" / "prep"),
    "audio_device": None,          # None — Windows: loopback вывода по умолчанию; macOS: BlackHole или микрофон
    "output_monitor": 1,
    "output_fullscreen": True,
    "render_size": [1920, 1080],
    "hud": False,
    "theme": "smena_pipboy",
    "theme_effects": True,         # развёртка и свечение экрана Pip-Boy
    "last_preset": None,
    "sync_ms": 0.0,
    "test_file": None,             # режим «файл»: последний аудиофайл
    "window_geometry": None,
    "trigger_config": None,        # таблица триггеров — имя файла в <кеш>/triggers
    "eq": [0.0, 0.0, 0.0],         # НИЗ / СЕР / ВЕРХ, дБ
    "volume": 100.0,
    "mute": False,
    "bank_open": False,            # фейдербанк раскрыт
    "ui_scale": None,              # масштаб интерфейса (None — подобрать по экрану при первом запуске)
    "photo_fill": True,            # фото на весь кадр (края обрезаются) / целиком с подложкой по бокам
}


class Settings:
    def __init__(self):
        self.v = dict(DEFAULTS)
        try:
            if SETTINGS_FILE.exists():
                self.v.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            log.exception("настройки не прочитаны, взяты значения по умолчанию")
        # на машине без данных автора — демо-набор
        if not Path(self.v["cache_dir"]).exists() and not Path(self.v["photos_dir"]).exists():
            self.v["photos_dir"] = self.v["cache_dir"] = str(SAMPLE_CACHE)
        # скрипты подготовки и python: пути из старых настроек (другая машина, сборка) — на свои
        if not Path(self.v["prep_scripts"]).is_dir():
            self.v["prep_scripts"] = DEFAULTS["prep_scripts"]
        if not Path(self.v["prep_python"] or "").is_file():
            self.v["prep_python"] = DEFAULTS["prep_python"]

    def __getitem__(self, k):
        return self.v[k]

    def __setitem__(self, k, val):
        self.v[k] = val

    def save(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.v, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            log.exception("настройки не сохранены")
