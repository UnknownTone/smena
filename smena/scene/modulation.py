"""LFO и провода (вкладка ФЕЙДЕРЫ, секция LFO) + верхнее фото.

Четыре LFO: форма (синус / треугольник / пила / меандр / S&H), скорость, глубина, синхронизация с BPM.
Провод «LFO i → фейдер» добавляет к положению фейдера depth · lfo(t) · ½ диапазона; к одному фейдеру можно
подать несколько проводов — они складываются. Сцена берёт значения через `Modulation.v(key)`, а не из Params.
"""
import math
import random
import time

from smena.triggers_table import N_LFO, RANGES

# скорость в режиме BPM: длина цикла в долях — от 1/4 доли до 256 тактов
SYNC_BEATS = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
HZ_MIN, HZ_MAX = 0.001, 8.0


def rate_hz(r):
    """Ручка 0..100 → Гц (логарифмически, от 1/1000 до 8 Гц)."""
    return 10 ** (math.log10(HZ_MIN) + (math.log10(HZ_MAX) - math.log10(HZ_MIN)) * r / 100.0)


def rate_beats(r):
    """Ручка 0..100 → длина цикла в долях (режим BPM); больше ручка — быстрее."""
    return SYNC_BEATS[len(SYNC_BEATS) - 1 - round(r / 100.0 * (len(SYNC_BEATS) - 1))]


def rate_text(r, sync):
    if sync:
        b = rate_beats(r)
        if b < 1:
            return f"1/{round(1 / b)} доли"
        if b < 4:
            return f"{b:g} доли"
        return f"{b / 4:g} такт" + ("а" if b / 4 in (2, 3, 4) else "ов" if b >= 20 else "")
    hz = rate_hz(r)
    return f"{hz:.2f} Гц" if hz >= 0.1 else f"1/{1 / hz:.0f} Гц"


class Lfo:
    def __init__(self, i, params):
        self.i, self.p = i, params
        self.phase = 0.0
        self._cycle = 0
        self._sh = 0.0
        self.value = 0.0
        self.rng = random.Random(i * 7919)

    def k(self, name):
        return self.p[f"lfo{self.i}.{name}"]

    def update(self, dt, beat):
        """Фаза: в режиме BPM — от доли сцены (цикл стоит на сетке), иначе — от времени."""
        if self.k("sync"):
            total = beat / rate_beats(self.k("rate"))
            self.phase = total % 1.0
            cycle = math.floor(total)
        else:
            self.phase += dt * rate_hz(self.k("rate"))
            cycle = self._cycle + int(self.phase)
            self.phase %= 1.0
        if cycle != self._cycle:
            self._cycle = cycle
            self._sh = self.rng.uniform(-1, 1)
        ph = self.phase
        w = int(self.k("wave"))
        self.value = (math.sin(2 * math.pi * ph) if w == 0 else
                      1 - 4 * abs(ph - 0.5) if w == 1 else
                      2 * ph - 1 if w == 2 else
                      (1.0 if ph < 0.5 else -1.0) if w == 3 else self._sh)
        return self.value


class Modulation:
    def __init__(self, params):
        self.p = params
        self.lfos = [Lfo(i, params) for i in range(1, N_LFO + 1)]
        self._t = None
        self.offsets = {}             # ключ → смещение в единицах фейдера (для «призрака» на фейдере)

    def update(self, beat, now=None):
        now = time.perf_counter() if now is None else now
        dt = 0.0 if self._t is None else min(0.2, now - self._t)
        self._t = now
        vals = [lfo.update(dt, beat) for lfo in self.lfos]
        off = {}
        for i, key in self.p["lfo.wires"]:
            r = RANGES.get(key)
            if r is None or not (1 <= i <= len(vals)):
                continue
            depth = self.p[f"lfo{i}.depth"] / 100.0
            off[key] = off.get(key, 0.0) + vals[i - 1] * depth * (r[1] - r[0]) / 2
        self.offsets = off

    def v(self, key):
        """Значение с учётом проводов LFO (в пределах фейдера)."""
        x = self.p[key]
        d = self.offsets.get(key)
        if d is None:
            return x
        lo, hi = RANGES[key]
        return min(max(x + d, lo), hi)


class ModView:
    """Params для сцены (мастер-клок, действия): фейдеры с проводами — с учётом LFO, остальное — как есть."""

    def __init__(self, params, mod):
        self.p, self.mod = params, mod

    def __getitem__(self, k):
        return self.mod.v(k) if k in self.mod.offsets else self.p[k]

    def __getattr__(self, name):
        return getattr(self.p, name)


class Overlay:
    """Верхнее фото: включается тоглом, держится «ДЕРЖАТЬ» секунд, появляется и уходит за «ПРОЯВЛ.»."""

    def __init__(self, params, mod):
        self.p, self.mod = params, mod
        self.t_on = None
        self.t_off = None
        self.alpha = 0.0
        params.changed.connect(self._changed)

    def _changed(self, k):
        if k != "ov.on":
            return
        now = time.perf_counter()
        if self.p["ov.on"]:
            self.t_on, self.t_off = now, None
        elif self.t_on is not None and self.t_off is None:
            self.t_off = now

    def update(self, now):
        fade = max(0.01, self.mod.v("ov.fade"))
        hold = self.mod.v("ov.hold")
        if self.t_on is None:
            self.alpha = 0.0
            return
        if self.t_off is None and hold > 0 and now - self.t_on > hold:
            self.p.set("ov.on", False)                         # срок вышел — тогл выключается сам
        a = min(1.0, (now - self.t_on) / fade)
        if self.t_off is not None:
            a = min(a, max(0.0, 1.0 - (now - self.t_off) / fade))
            if a <= 0:
                self.t_on = self.t_off = None
        self.alpha = a
