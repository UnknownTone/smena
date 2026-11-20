"""Калибровка выхода (вкладка ВЫВОД): сетка узлов (геометрия под проектор / экран) и маска (вырезать
изображение под мапинг). Хранится по монитору: %APPDATA%\\SMENA\\mapping\\monitor_N.json + _mask.png.

Узлы — позиции в долях кадра выхода (x вправо, y вниз), сетка nx×ny. Маска — 8 бит, 960×540 (белое — видно);
нет маски — видно всё. Растушёвка и отступ применяются при сборке маски для рендера.
"""
import json
import logging

import numpy as np
from PySide6.QtGui import QImage

from smena.settings import DATA_DIR

log = logging.getLogger("smena.mapping")
MAP_DIR = DATA_DIR / "mapping"
MASK_W, MASK_H = 960, 540


def _box(a, r, axis):
    c = np.cumsum(np.pad(a, [(r + 1, r) if i == axis else (0, 0) for i in range(2)], mode="edge"), axis=axis)
    n = a.shape[axis]
    return (np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis) - np.take(c, np.arange(0, n), axis=axis)) \
        / (2 * r + 1)


class Mapping:
    def __init__(self, monitor=1):
        self.monitor = monitor
        self.version = 0
        self.nx = self.ny = 2
        self.nodes = self.grid_nodes(2, 2)
        self.mask = None              # QImage Grayscale8 MASK_W×MASK_H или None
        self.invert = False
        self.feather = 12             # пиксели маски
        self.offset = 0               # + расширить, − сузить
        self.sx = self.sy = 1.0       # ширина и высота картинки на выходе (доли)
        self.dx = self.dy = 0.0       # сдвиг картинки (доли кадра)
        self.load(monitor)

    def out_nodes(self):
        """Узлы для рендера: сетка калибровки, растянутая / сдвинутая (ширина, высота, X, Y) от центра."""
        return [[0.5 + (x - 0.5) * self.sx + self.dx, 0.5 + (y - 0.5) * self.sy + self.dy] for x, y in self.nodes]

    @staticmethod
    def grid_nodes(nx, ny):
        return [[i / (nx - 1), j / (ny - 1)] for j in range(ny) for i in range(nx)]

    def touch(self):
        self.version += 1

    # ------------------------------------------------------------- сетка
    def set_grid(self, nx, ny):
        """Новая плотность сетки — узлы ставятся по текущей геометрии (билинейно)."""
        old = np.array(self.nodes, np.float32).reshape(self.ny, self.nx, 2)
        new = []
        for j in range(ny):
            for i in range(nx):
                x, y = i / (nx - 1) * (self.nx - 1), j / (ny - 1) * (self.ny - 1)
                i0, j0 = min(int(x), self.nx - 2), min(int(y), self.ny - 2)
                a, b = x - i0, y - j0
                p = (old[j0, i0] * (1 - a) * (1 - b) + old[j0, i0 + 1] * a * (1 - b)
                     + old[j0 + 1, i0] * (1 - a) * b + old[j0 + 1, i0 + 1] * a * b)
                new.append([float(p[0]), float(p[1])])
        self.nx, self.ny, self.nodes = nx, ny, new
        self.touch()

    def reset_grid(self):
        self.nodes = self.grid_nodes(self.nx, self.ny)
        self.touch()

    # ------------------------------------------------------------- маска
    def ensure_mask(self):
        if self.mask is None:
            self.mask = QImage(MASK_W, MASK_H, QImage.Format_Grayscale8)
            self.mask.fill(0)
        return self.mask

    def clear_mask(self):
        self.mask = None
        self.invert = False
        self.touch()

    def mask_bytes(self):
        """Маска для рендера: (w, h, байты) с инверсией, отступом и растушёвкой; None — видно всё."""
        if self.mask is None:
            return None
        img = self.mask
        a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width()]
        m = a.astype(np.float32) / 255.0
        if self.invert:
            m = 1.0 - m
        if self.offset:
            r = abs(int(self.offset))
            b = m > 0.5
            if self.offset < 0:
                b = ~b
            c = _box(_box(b.astype(np.float32), r, 0), r, 1) > 0
            m = (c if self.offset > 0 else ~c).astype(np.float32)
        if self.feather > 0:
            r = int(self.feather)
            m = _box(_box(m, r, 0), r, 1)
        return MASK_W, MASK_H, (np.clip(m, 0, 1) * 255).astype(np.uint8).tobytes()

    # ------------------------------------------------------------- файлы
    def _paths(self, monitor):
        return MAP_DIR / f"monitor_{monitor}.json", MAP_DIR / f"monitor_{monitor}_mask.png"

    def load(self, monitor):
        self.monitor = monitor
        js, png = self._paths(monitor)
        self.nx = self.ny = 2
        self.nodes = self.grid_nodes(2, 2)
        self.mask, self.invert, self.feather, self.offset = None, False, 12, 0
        self.sx = self.sy = 1.0
        self.dx = self.dy = 0.0
        try:
            if js.is_file():
                d = json.loads(js.read_text(encoding="utf-8"))
                self.nx, self.ny, self.nodes = d["nx"], d["ny"], d["nodes"]
                self.invert, self.feather, self.offset = d.get("invert", False), d.get("feather", 12), d.get("offset", 0)
                self.sx, self.sy = d.get("sx", 1.0), d.get("sy", 1.0)
                self.dx, self.dy = d.get("dx", 0.0), d.get("dy", 0.0)
            if png.is_file():
                img = QImage(str(png)).convertToFormat(QImage.Format_Grayscale8)
                if not img.isNull():
                    self.mask = img.scaled(MASK_W, MASK_H)
        except Exception:
            log.exception("калибровка не прочитана — по умолчанию")
        self.touch()

    def save(self):
        js, png = self._paths(self.monitor)
        MAP_DIR.mkdir(parents=True, exist_ok=True)
        js.write_text(json.dumps({"nx": self.nx, "ny": self.ny, "nodes": self.nodes, "invert": self.invert,
                                  "feather": self.feather, "offset": self.offset, "sx": self.sx, "sy": self.sy,
                                  "dx": self.dx, "dy": self.dy}, indent=1), encoding="utf-8")
        if self.mask is not None:
            self.mask.save(str(png))
        else:
            png.unlink(missing_ok=True)
