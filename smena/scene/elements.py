"""Экземпляр фото в кадре и состояние его элементов (SPEC §2.5, §4.1; эталон — render_demo.fit_photo /
element_frame). Всё время — в долях сцены (см. clock.py), координаты — пиксели холста вывода.

Каждый цикл создаёт свежий экземпляр: одно и то же фото может быть одновременно past и future
(папка из двух фото), у экземпляров своё состояние.
"""
import math
import random

ENTRY_STEPS = 8            # ступенчатый въезд (почерк №6)
EXIT_BEATS = 1.0           # выезд past — 1 доля (SPEC §2.5)
FLICKER_BEATS = 1.0        # мерцание перед исчезновением в исключениях №1/№12
DEMO_W, DEMO_H = 1280, 848 # холст эталона: скорости и число полос заданы в его пикселях
STRIP_PX = 60              # примерная ширина полосы в пикселях эталона


def ease_out(u):
    return 1 - (1 - u) ** 3


def fit_rect(pw, ph, W, H, fill=False):
    """Фото в холсте: целиком (contain) или на весь кадр с обрезкой краёв (cover): (ox, oy, s)."""
    s = max(W / pw, H / ph) if fill else min(W / pw, H / ph)
    return (W - pw * s) / 2, (H - ph * s) / 2, s


class Element:
    def __init__(self, meta, W, H, ox, oy, s, s_demo, rng):
        self.id = meta["id"]
        self.file = meta["file"]
        self.half = meta.get("half", "bottom")
        self.pol = meta.get("polarity", "X")
        x, y, w, h = meta["bbox"]
        self.w, self.h = w * s, h * s
        self.home = (ox + x * s, oy + y * s)
        hx, hy = self.home
        # луч — к ближайшей стене фото, старт — за краем холста (render_demo.fit_photo)
        dists = {"left": hx - ox, "right": (W - ox) - (hx + self.w),
                 "top": hy - oy, "bottom": (H - oy) - (hy + self.h)}
        self.edge = min(dists, key=dists.get)
        self.start = {"left": (-self.w - 10, hy), "right": (W + 10, hy),
                      "top": (hx, -self.h - 10), "bottom": (hx, H + 10)}[self.edge]
        cx, cy = hx + self.w / 2 - W / 2, hy + self.h / 2 - H / 2
        self.central = abs(cx) < W * 0.25
        self.angle = (math.degrees(math.atan2(cx, -cy)) + 360) % 360   # по часовой от верха
        # полосы содержимого поперёк полярности; число — как в эталоне
        dim_demo = (h if self.pol == "X" else w) * s_demo
        self.nstrip = int(min(max(round(dim_demo / STRIP_PX), 2), 6))
        self.u = [rng.uniform(-1, 1) for _ in range(self.nstrip)]      # разброс скоростей: 1 + РАЗБРОС·u
        self.d = [rng.choice((-1, 1)) for _ in range(self.nstrip)]     # направление полосы
        self.off = [0.0] * self.nstrip                                 # сдвиг полосы, пиксели холста
        self.px_scale = s / s_demo                                     # пиксели эталона → холста

        self.t_in = None           # доля начала въезда (None — ещё не назначен)
        self.t_out = None          # доля начала выезда
        # от триггеров (M3): смещение, угол, исключения и импульсы
        self.dx = self.dy = self.ang = 0.0
        self.hidden = False        # PWM №15 (на кадр)
        self.flicker_from = None   # №1/№12: мерцание 1 доля (доли сцены)
        self.gone_from = None      # после мерцания — исчез (доля)
        self.blink_from = -1e9     # №7 мигание (доля)
        self.shake = (-1e9, 0.0, 0.0, 0.0)   # №4: (секунды, направление x, y, амплитуда)
        self.bounce = -1e9         # №18 отскок (секунды)
        self.boost = 1.0           # №14 быстрая смена содержимого — множитель скорости полос
        self.vib = 0.0             # №8 вибрация содержимого, пиксели эталона
        self.rng = rng
        # появление мерцанием на месте вместо въезда (SPEC §2.5): случайное число фиксировано за элементом,
        # доля мерцающих — ручка «МЕРЦ» (clock выставляет flick_in на кадр)
        self.appear_u = rng.random()
        self.flick_in = False
        # газетная вырезка (SPEC §4.6): с какой доли, сколько долей, наклон
        self.news_from = None
        self.news_len = 0.0
        self.news_tilt = 0.0
        self.rank = 0              # место по размеру (0 — самый крупный), см. PhotoInstance

    def news(self, beat):
        """Сила газетного эффекта 0..1 (короткое нарастание и спад по 1/4 доли)."""
        if self.news_from is None or not (self.news_from <= beat < self.news_from + self.news_len):
            return 0.0
        r = beat - self.news_from
        return min(1.0, r / 0.25, (self.news_len - r) / 0.25)

    @property
    def dim_along(self):
        return self.w if self.pol == "X" else self.h

    def strip_offsets(self):
        """Сдвиги полос в долях размера элемента вдоль полярности (для шейдера); №8 — дрожь полос."""
        d = self.dim_along or 1.0
        if self.vib > 0:
            v = self.vib * self.px_scale
            return [(o + self.rng.uniform(-v, v)) / d for o in self.off]
        return [o / d for o in self.off]

    def advance_strips(self, speed_demo_px, dt, spread):
        k = speed_demo_px * self.px_scale * dt * self.boost
        for j in range(self.nstrip):
            self.off[j] = (self.off[j] + k * (1 + spread * self.u[j]) * self.d[j]) % (2 * self.dim_along or 1)

    def new_pattern(self):
        """№13: новый паттерн полос (скорости и направления)."""
        self.u = [self.rng.uniform(-1, 1) for _ in range(self.nstrip)]
        self.d = [self.rng.choice((-1, 1)) for _ in range(self.nstrip)]

    def present(self, beat):
        """В кадре по расписанию: от начала въезда до конца выезда."""
        if self.t_in is None or beat < self.t_in:
            return False
        return self.t_out is None or beat <= self.t_out + EXIT_BEATS

    def visible(self, beat):
        """Виден в этом кадре: расписание + исключения (мерцание, исчезновение) + мигание + PWM."""
        if self.gone_from is not None and beat >= self.gone_from:
            return False
        if self.flicker_from is not None and self.flicker_from <= beat < self.flicker_from + FLICKER_BEATS:
            return int((beat - self.flicker_from) * 8) % 2 == 0     # мерцание по 1/8 доли
        if self.hidden or not self.present(beat):
            return False
        if self.flick_in and self.t_in <= beat < self.t_in + FLICKER_BEATS:
            return int((beat - self.t_in) * 8) % 2 == 0               # появление мерцанием на месте
        if 0 <= beat - self.blink_from < 0.5 and int((beat - self.blink_from) * 8) % 2 == 0:
            return False                                              # №7 мигание по 1/8 доли
        return True

    def position(self, beat, entry_beats, stepped=False):
        """Позиция с учётом въезда/выезда по лучу."""
        x, y = self.home[0] + self.dx, self.home[1] + self.dy
        sx, sy = self.start
        if self.t_in is not None and beat < self.t_in + entry_beats and not self.flick_in:
            u = max(0.0, (beat - self.t_in) / entry_beats)
            if stepped:
                u = math.floor(u * ENTRY_STEPS) / ENTRY_STEPS
            u = ease_out(min(1.0, u))
            x, y = sx + (x - sx) * u, sy + (y - sy) * u
        if self.t_out is not None and beat > self.t_out:
            u = min(1.0, (beat - self.t_out) / EXIT_BEATS) ** 2
            x, y = x + (sx - x) * u, y + (sy - y) * u
        return x, y


class PhotoInstance:
    """Фото в одной из ролей past / master / future."""

    def __init__(self, entry, index, W, H, seed, fill=False):
        self.entry = entry
        self.index = index                 # номер в списке фото (0..N-1)
        self.name = entry.name
        meta = entry.meta
        pw, ph = meta["size"]
        self.ox, self.oy, self.s = fit_rect(pw, ph, W, H, fill)
        s_demo = min(DEMO_W / pw, DEMO_H / ph)
        rng = random.Random(seed)
        self.elements = [Element(m, W, H, self.ox, self.oy, self.s, s_demo, rng)
                         for m in meta.get("elements", [])]
        # гранулярность (фейдер ЭЛЕМЕНТЫ): двигаются первые N по размеру, остальные стоят как часть фото
        for r, e in enumerate(sorted(self.elements, key=lambda e: -e.w * e.h)):
            e.rank = r
        self.rect = (self.ox, self.oy, pw * self.s, ph * self.s)
        self.full = self.ox <= 1 and self.oy <= 1           # заполняет холст — подложка не нужна

    def clockwise(self):
        return sorted(self.elements, key=lambda e: e.angle)
