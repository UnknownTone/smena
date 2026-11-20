"""Фоновая подгрузка картинок фото (фон, размытая подложка, элементы) — без рывков рендера.

Декодирование — в отдельном потоке (QImage потокобезопасен), текстуры создаёт рендер в главном потоке.
"""
import logging
import queue
import threading

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

log = logging.getLogger("smena.assets")

BLUR_W = 48               # ширина подложки: при растяжении билинейно выходит мягкое размытие


def _rgba(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return img.width(), img.height(), bytes(img.constBits())[:img.width() * img.height() * 4]


def _max_window(a, r, axis):
    """Расширение булевой маски на r пикселей вдоль оси (скользящее окно через накопленную сумму)."""
    c = np.cumsum(np.pad(a, [(r + 1, r) if i == axis else (0, 0) for i in range(2)]).astype(np.int32), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) > 0


def _box_blur(a, r, axis):
    c = np.cumsum(np.pad(a, [(r + 1, r) if i == axis else (0, 0) for i in range(2)], mode="edge"), axis=axis)
    n = a.shape[axis]
    return (np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
            - np.take(c, np.arange(0, n), axis=axis)) / (2 * r + 1)


def paper(rgba_bytes, w, h, seed):
    """Бумага газетной вырезки (SPEC §4.6): кайма вокруг силуэта с неровным краем «как от ножниц»
    и её размытая копия для тени. → (поле M, W2, H2, байты RG: R — бумага, G — размытая бумага)."""
    alpha = np.frombuffer(rgba_bytes, np.uint8).reshape(h, w, 4)[..., 3] > 127
    r = int(min(max(round(0.035 * min(w, h)), 3), 14))         # ширина каймы
    r2 = int(r * 1.8)
    M = r2 + r + 2                                             # поле: кайма + место для тени
    A = np.pad(alpha, M)
    small = _max_window(_max_window(A, r, 0), r, 1)
    big = _max_window(_max_window(A, r2, 0), r2, 1)
    rng = np.random.default_rng(seed)
    H2, W2 = A.shape
    g = rng.random((H2 // 6 + 2, W2 // 6 + 2))                 # крупные выступы края
    noise = np.kron(g, np.ones((6, 6)))[:H2, :W2] > 0.55
    p = small | (big & noise)
    pf = p.astype(np.float32)
    rb = max(2, r // 2)
    blur = _box_blur(_box_blur(pf, rb, 0), rb, 1)
    rg = np.dstack([(pf * 255).astype(np.uint8), (np.clip(blur, 0, 1) * 255).astype(np.uint8)])
    return M, W2, H2, rg.tobytes()


class PhotoAssets:
    def __init__(self, key):
        self.key = key
        self.images = {}          # имя → (w, h, байты RGBA)
        self.papers = {}          # имя элемента → (поле M, w, h, байты RG) — газетные вырезки


class AssetLoader:
    def __init__(self):
        self.ready = {}           # ключ (папка кеша) → PhotoAssets
        self._pending = set()
        self._q = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, name="assets", daemon=True).start()

    @staticmethod
    def key(entry):
        return str(entry.cache)

    def request(self, entry):
        k = self.key(entry)
        with self._lock:
            if k in self.ready or k in self._pending:
                return
            self._pending.add(k)
        self._q.put(entry)

    def get(self, entry):
        return self.ready.get(self.key(entry))

    def keep_only(self, entries):
        """Освободить память фото, которые больше не нужны."""
        keep = {self.key(e) for e in entries}
        with self._lock:
            for k in [k for k in self.ready if k not in keep]:
                del self.ready[k]

    def _loop(self):
        while True:
            entry = self._q.get()
            k = self.key(entry)
            a = PhotoAssets(k)
            try:
                bg = QImage(str(entry.cache / "background.png"))
                if bg.isNull():
                    raise IOError("background.png не читается")
                a.images["background.png"] = _rgba(bg)
                small = bg.scaledToWidth(BLUR_W, Qt.SmoothTransformation)
                a.images["_blur"] = _rgba(small)
                for el in entry.meta.get("elements", []):
                    im = QImage(str(entry.cache / el["file"]))
                    if not im.isNull():
                        a.images[el["file"]] = w, h, data = _rgba(im)
                        a.papers[el["file"]] = paper(data, w, h, seed=hash((k, el["file"])) & 0xFFFFFFFF)
            except Exception:
                log.exception("фото не загружено: %s", entry.cache)
            with self._lock:
                self.ready[k] = a
                self._pending.discard(k)
