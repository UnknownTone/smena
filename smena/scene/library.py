"""Папка фото → кеш элементов (формат SPEC §3.6: photo.json, background.png, el_*.png).

Кеш бывает двух видов: «плоский» `<кеш>/<фото>/photo.json` (vj/cache/sel56, data/sample_cache)
и как пишет build_elements.py — `<кеш>/elements/<фото>/photo.json`. Понимаем оба.
Порядок — по номеру в имени файла: числа внутри имени сравниваются как числа (2 раньше 10).
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("smena.library")

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def natural_key(name):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


@dataclass
class PhotoEntry:
    name: str                       # имя без расширения = имя папки в кеше
    source: Path | None = None      # исходное фото (может не быть — только кеш)
    cache: Path | None = None       # папка элементов с photo.json
    meta: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ready(self):
        return self.cache is not None and not self.error

    @property
    def n_top(self):
        return sum(1 for e in self.meta.get("elements", []) if e.get("half") == "top")

    @property
    def n_bottom(self):
        return sum(1 for e in self.meta.get("elements", []) if e.get("half") != "top")

    @property
    def preview(self):
        """Миниатюра: preview.jpg кеша, иначе исходное фото."""
        if self.cache and (self.cache / "preview.jpg").exists():
            return self.cache / "preview.jpg"
        return self.source

    @property
    def status(self):
        if self.error:
            return "ошибка"
        return "готово" if self.cache else "нет кеша"


def cache_roots(cache_dir):
    root = Path(cache_dir)
    return [root / "elements", root]


def scan(photos_dir, cache_dir):
    """Список фото по порядку. Если исходных фото нет — показываем то, что есть в кеше."""
    photos_dir, cache_dir = Path(photos_dir), Path(cache_dir)
    cached = {}
    for root in cache_roots(cache_dir):
        if root.is_dir():
            for d in root.iterdir():
                if d.name not in cached and (d / "photo.json").is_file():
                    cached[d.name] = d

    entries = {}
    if photos_dir.is_dir():
        for p in photos_dir.iterdir():
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("._"):   # «._*» — файлы macOS
                entries[p.stem] = PhotoEntry(p.stem, source=p, cache=cached.get(p.stem))
    if not entries:
        entries = {n: PhotoEntry(n, cache=d) for n, d in cached.items()}

    for e in entries.values():
        if e.cache:
            try:
                e.meta = json.loads((e.cache / "photo.json").read_text(encoding="utf-8"))
                missing = [el["file"] for el in e.meta.get("elements", [])
                           if not (e.cache / el["file"]).is_file()]
                if not (e.cache / "background.png").is_file():
                    missing.insert(0, "background.png")
                if missing:
                    e.error = "нет файлов: " + ", ".join(missing)
            except Exception as ex:
                e.error = f"photo.json: {ex}"
                log.warning("кеш %s: %s", e.cache, ex)
    return sorted(entries.values(), key=lambda e: natural_key(e.name))
