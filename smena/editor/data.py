"""Данные редактора элементов (06_LABELING_TOOL.yaml): набор фото, кандидаты SAM 2, авто- и ручной выбор,
история изменений (undo/redo), журнал меток для обучения (labels.jsonl).

Ручной выбор — selection_manual.json рядом с авто-выбором (формат build_elements.py):
  {"<фото>": {"els": [[3], [5, 6], {"n": 4, "box": […], "torn": seed}], "extra": ["extra_1.png"], "rect": [2],
              "half": {"1": "top"}, "polarity": {"2": "X"}, "line_y": 0.62, "pause": false, "checked": true,
              "genre": "architecture", "note": ""}}
Номера элементов (rect/half/polarity) — с 1, по порядку: els, затем extra.
"""
import copy
import datetime
import json
import os
import re
import shutil
import sys
from pathlib import Path

import numpy as np

from smena.runtime import FROZEN
from smena.settings import DATA_DIR, ROOT

sys.path.insert(0, str(ROOT / "tools" / "prep"))
try:
    from torn import torn_piece                      # рваный край крупных кусков — та же маска, что при сборке
except Exception:                                    # pragma: no cover
    torn_piece = None

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
GENRES = [("architecture", "архитектура"), ("people", "люди"), ("nature", "природа"),
          ("bw_film", "ч/б плёнка"), ("night_neon", "ночь / неон"), ("other", "другое")]
LABELS_PATH = ROOT / "data" / "labels" / "labels.jsonl"
if FROZEN:                                           # сборка: папка приложения только для чтения — метки у пользователя
    LABELS_PATH = DATA_DIR / "labels" / "labels.jsonl"
    _seed = ROOT / "data" / "labels" / "model.json"  # готовая модель отбора — копия при первом запуске
    if _seed.is_file() and not (LABELS_PATH.parent / "model.json").is_file():
        try:
            LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_seed, LABELS_PATH.parent / "model.json")
        except OSError:
            pass
MAX_OVERLAP = 0.15
MAX_ELEMENTS = 32


def natural_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def atomic_write(path, text):
    """Запись через временный файл и подмену — файл не портится при сбое (решение 7)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class SetPaths:
    """Где лежит всё для набора фото (решение 4: любой набор, не только 56 фото альбома)."""

    def __init__(self, photos_dir, cache_dir):
        self.photos = Path(photos_dir)
        cache = Path(cache_dir)
        stems = sorted((p.stem for p in self.photos.iterdir()
                        if p.suffix.lower() in EXTS and not p.name.startswith("._")), key=natural_key) \
            if self.photos.is_dir() else []
        self.stems = stems
        probe = stems[0] if stems else None
        # кандидаты: <кеш>\cands, сам кеш, соседние папки кеша (альбом: cache\sel54 рядом с cache\sel56v2)
        options = [cache / "cands", cache] + (sorted(cache.parent.iterdir()) if cache.parent.is_dir() else [])
        self.cands = next((d for d in options if probe and (d / probe / "cands.npz").is_file()), cache / "cands")
        # авто-выбор: <кеш>\selection.json, иначе data\selection_*.json с этими фото (новее — по имени)
        auto = cache / "selection.json"
        if not auto.is_file():
            for f in sorted((ROOT / "data").glob("selection_*.json"), key=lambda p: p.name, reverse=True):
                if "manual" in f.name:
                    continue
                try:
                    if probe in json.loads(f.read_text(encoding="utf-8")):
                        auto = f
                        break
                except Exception:
                    pass
        self.auto = auto
        self.manual = auto.parent / "selection_manual.json"
        self.elements = cache / "elements" if (cache / "elements").is_dir() else cache
        self.labels = LABELS_PATH
        self.set_name = self.photos.name


class PhotoData:
    """Кандидаты одного фото: маски (H×W), метаданные, признаки, контуры для показа."""

    def __init__(self, paths, stem):
        self.stem = stem
        self.dir = paths.cands / stem
        z = np.load(self.dir / "cands.npz")
        H, W = (int(v) for v in z["shape"])
        self.H, self.W = H, W
        self.masks = np.unpackbits(z["masks"], axis=-1)[..., :W].astype(bool)
        meta = json.loads((self.dir / "cands.json").read_text(encoding="utf-8"))
        self.cands = {c["n"]: c for c in meta["cands"]}
        self.features = {}
        self.load_features()
        self.source = next((p for p in paths.photos.iterdir() if p.stem == stem and p.suffix.lower() in EXTS), None)
        self._extra = {}

    def load_features(self):
        f = self.dir / "features.json"
        if f.is_file():
            try:
                self.features = json.loads(f.read_text(encoding="utf-8")).get("cands", {})
            except Exception:
                self.features = {}

    def cand_mask(self, n):
        return self.masks[n - 1]

    def extra_mask(self, name):
        if name not in self._extra:
            from PySide6.QtGui import QImage
            img = QImage(str(self.dir / name)).convertToFormat(QImage.Format_Grayscale8)
            a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width()]
            self._extra[name] = a > 127
        return self._extra[name]

    def save_extra(self, name, mask):
        from PySide6.QtGui import QImage
        a = np.ascontiguousarray((mask * 255).astype(np.uint8))
        QImage(a.data, a.shape[1], a.shape[0], a.shape[1], QImage.Format_Grayscale8).copy().save(str(self.dir / name))
        self._extra[name] = mask.copy()

    def group_mask(self, g):
        if isinstance(g, dict):
            m = self.cand_mask(g["n"])
            if "torn" in g and torn_piece:
                return torn_piece(m, g["box"], g["torn"])
            out = np.zeros_like(m)
            x0, y0, x1, y1 = g["box"]
            out[y0:y1, x0:x1] = m[y0:y1, x0:x1]
            return out
        out = np.zeros((self.H, self.W), bool)
        for n in g:
            out |= self.cand_mask(n)
        return out

    def next_extra_name(self):
        k = 1
        while (self.dir / f"extra_{k}.png").exists():
            k += 1
        return f"extra_{k}.png"


def empty_entry():
    return {"els": [], "extra": [], "rect": [], "half": {}, "polarity": {}, "line_y": None,
            "pause": False, "checked": False, "genre": None, "note": ""}


def normalize(e):
    out = empty_entry()
    out.update({k: copy.deepcopy(v) for k, v in e.items() if k in out or k == "note"})
    return out


class Selections:
    """Авто- и ручной выбор, история на фото, автосохранение, журнал меток."""

    def __init__(self, paths):
        self.paths = paths
        self.auto = self._read(paths.auto)
        self.manual = self._read(paths.manual)
        self.undo, self.redo = {}, {}

    @staticmethod
    def _read(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else {}
        except Exception:
            return {}

    def entry(self, stem):
        """Текущий выбор фото: ручной, если есть, иначе авто (копия)."""
        if stem in self.manual:
            return self.manual[stem]
        return normalize(self.auto.get(stem, {}))

    def status(self, stem):
        e = self.manual.get(stem)
        if e is None:
            return "auto"
        if e.get("pause"):
            return "pause"
        return "checked" if e.get("checked") else "edited"

    def count(self, stem):
        e = self.entry(stem)
        return 0 if e.get("pause") else len(e.get("els", [])) + len(e.get("extra", []))

    # ------------------------------------------------------------- изменения
    def change(self, stem, fn):
        """Применить изменение fn(entry) с записью в историю и автосохранением."""
        cur = normalize(self.entry(stem))
        self.undo.setdefault(stem, []).append(json.dumps(cur, ensure_ascii=False))
        self.redo[stem] = []
        fn(cur)
        self.manual[stem] = cur
        self.save()

    def step(self, stem, back=True):
        src, dst = (self.undo, self.redo) if back else (self.redo, self.undo)
        if not src.get(stem):
            return False
        dst.setdefault(stem, []).append(json.dumps(normalize(self.entry(stem)), ensure_ascii=False))
        self.manual[stem] = json.loads(src[stem].pop())
        self.save()
        return True

    def reset_to_auto(self, stem):
        self.change(stem, lambda e: (e.clear(), e.update(normalize(self.auto.get(stem, {})))))

    def save(self):
        atomic_write(self.paths.manual, json.dumps(self.manual, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------- метки
    def log(self, rec):
        """Одна строка = одно решение; только дописывать."""
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "set": self.paths.set_name, **rec}
        self.paths.labels.parent.mkdir(parents=True, exist_ok=True)
        with open(self.paths.labels, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def auto_cands(self, stem):
        out = set()
        for g in self.auto.get(stem, {}).get("els", []):
            out.update([g["n"]] if isinstance(g, dict) else g)
        return out


def elements_of(entry):
    """[(вид, источник)] по порядку номеров элементов: els, затем extra."""
    if entry.get("pause"):
        return []
    return [("cand", g) for g in entry.get("els", [])] + [("extra", n) for n in entry.get("extra", [])]


def element_cands(kind, src):
    if kind != "cand":
        return []
    return [src["n"]] if isinstance(src, dict) else list(src)
