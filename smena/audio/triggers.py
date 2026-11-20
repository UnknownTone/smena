"""Триггеры таблицы автора в реальном времени (SPEC §5, docs/build/05_TRIGGERS_FADERS.md).
Эталон — render_demo.Triggers / detect_events / onsets, но всё только по прошлому (скользящие окна).

Работает в потоке звука после Features: уровни → нормализация по скользящим перцентилям (5–95%),
«активен» = значимое изменение за 2 доли против 8 предыдущих, ks по числу активных (ряд Фибоначчи),
импульсы (акценты, бочка, атаки 2–6 кГц, обрывы) и события (смена части, гармония, ясность пульса).
Фейдеры: ВКЛ, СИЛА (множитель действия — применяется в сцене), ЧУВСТВ. (делит пороги).

Наружу (читается без блокировок): levels {№: 0..1}, active {№}, ks, events (deque (№, время, сила)),
flash {№: время последнего срабатывания}, entry {"bottom"/"top": время последнего триггера въезда}.
"""
import math
import time
from collections import deque

import numpy as np

FIB = [1, 1, 2, 3, 5, 8, 13, 21]
ACTIVE_Z, ACTIVE_MIN = 1.0, 0.04      # активен: |Δ| / (σ + 0.03) > 1 и |Δ| > 0.04
LEVELS = {  # № таблицы: признак Features.raw
    2: "bass", 3: "centroid", 5: "side", 6: "perc", 7: "tonal", 8: "flat", 9: "sub", 10: "high",
    11: "lowmid", 13: "flux_high", 16: "mid", 17: "lfo", 18: "himid", 19: "rms", 20: "wobble",
}
RISING = (7, 9, 13, 19)               # срабатывают на «рост активности»
SECTION_KEYS = ("bass", "sub", "high", "centroid", "flat", "side", "perc", "mid", "lowmid", "rms")
DECIM = 4                             # история уровней — каждый 4-й блок (~23 Гц)
HIST_S = 40.0                         # окно перцентилей и событий, с
ONSET_S = 4.0                         # локальный фон для импульсов (медиана/MAD), с


class Onsets:
    """Пики выше локального фона: z = (x − медиана) / MAD за 4 с, не чаще min_gap."""

    def __init__(self, fps, z_thr, min_gap, pct=None):
        self.buf = deque(maxlen=int(ONSET_S * fps))
        self.z_thr, self.min_gap, self.pct = z_thr, min_gap, pct
        self.med, self.mad, self.p = 0.0, 1.0, 1e9
        self.last = -1e9
        self.n = 0
        self.prev_z = 0.0

    def push(self, x, now, sens):
        self.buf.append(x)
        self.n += 1
        if self.n % 8 == 0 and len(self.buf) > 20:
            a = np.asarray(self.buf)
            self.med = float(np.median(a))
            self.mad = float(np.median(np.abs(a - self.med))) * 1.4826 + 1e-9
            if self.pct:
                self.p = float(np.percentile(a, self.pct))
        z = (x - self.med) / self.mad
        hit = None
        thr = self.z_thr / max(sens, 0.05)
        if z > thr and self.prev_z <= thr and now - self.last > self.min_gap and (not self.pct or x > self.p):
            self.last = now
            hit = z
        self.prev_z = z
        return hit


class Triggers:
    def __init__(self, engine, params):
        self.eng, self.params = engine, params
        fps = engine.sr / 512
        self.fps = fps
        self.hfps = fps / DECIM
        n = int(HIST_S * self.hfps)
        self.keys = sorted(set(LEVELS.values()) | set(SECTION_KEYS))
        self.hist = {k: deque(maxlen=n) for k in self.keys}
        self.chroma_hist = deque(maxlen=n)
        self.conf_hist = deque(maxlen=int(HIST_S * 2))       # ясность пульса, 2 раза в с
        self.dist_hist = deque(maxlen=n)
        self.lo = {k: 0.0 for k in self.keys}
        self.hi = {k: 1.0 for k in self.keys}
        self.accent = Onsets(fps, 6.0, 0.25, pct=99)          # №4
        self.kick = Onsets(fps, 3.0, 0.18)                   # въезд нижних
        self.himid = Onsets(fps, 4.0, 0.15)                  # въезд верхних
        self.bounce = Onsets(fps, 8.0, 0.5)                  # №18 отскок — только сильные атаки 2–6 кГц
        self.drop_armed = True
        self.rms_s = deque(maxlen=max(1, int(0.25 * fps)))   # №15: RMS за 0.25 с
        self.blocks = 0
        self.t0 = time.perf_counter()

        # --- наружу ---
        self.levels = {n_: 0.0 for n_ in LEVELS}
        self.active = set()
        self.ks = 1
        self.n_active = 0
        self.events = deque(maxlen=256)
        self.flash = {n_: -1e9 for n_ in range(1, 21)}
        self.entry = {"bottom": -1e9, "top": -1e9}
        self.dropout_on = False
        self.last = {1: -1e9, 12: -1e9, 14: -1e9, 4: -1e9, 15: -1e9}

    # ---------------------------------------------------------------- фейдеры
    def on(self, n):
        return bool(self.params[f"t{n}.on"])

    def sens(self, n):
        return self.params[f"t{n}.sens"] / 100.0

    def fire(self, n, now, mag=1.0, manual=False):
        """Срабатывание: в очередь для сцены, лампа, журнал (кроме частых импульсов)."""
        if not manual and not self.on(n):
            return
        self.events.append((n, now, float(mag)))
        self.flash[n] = now
        if n in (1, 12, 14, 15) or manual:
            from smena.triggers_table import TRIGGERS
            t = TRIGGERS[n - 1]
            self.eng.log_event(f"{'▶ ' if manual else ''}№{n} {t.short}: {t.action}")

    def manual(self, n):
        self.fire(n, time.perf_counter(), 1.0, manual=True)

    # ------------------------------------------------------------------ блок
    def process(self, now):
        f = self.eng.features
        r = f.raw
        self.blocks += 1
        if f.silent:
            return
        beat = 60.0 / self.eng.beat.grid_bpm

        # импульсы — каждый блок
        z = self.accent.push(r["flux"], now, self.sens(4))
        if z is not None:
            self.fire(4, now, z)
            self.entry["top"] = now
            self.last[4] = now
        if self.kick.push(r["flux_bass"], now, 1.0) is not None:
            self.entry["bottom"] = now
        if self.himid.push(r["flux_himid"], now, 1.0) is not None:
            self.entry["top"] = now
        if self.bounce.push(r["flux_himid"], now, self.sens(18)) is not None:
            self.fire(18, now)
        self.rms_s.append(r["rms"])

        if self.blocks % DECIM:
            return
        for k in self.keys:
            self.hist[k].append(r[k])
        self.chroma_hist.append(f.chroma.copy())
        if self.blocks % (DECIM * 12) == 0:            # ~2 раза в секунду
            self._percentiles()
            self.conf_hist.append(self.eng.beat.confidence)
            self._events(now, beat)
        self._levels_and_activity(now, beat)
        self._dropout(now, beat)

    # -------------------------------------------------------------- уровни
    def _percentiles(self):
        for k in self.keys:
            h = self.hist[k]
            if len(h) > 30:
                a = np.asarray(h)
                self.lo[k], self.hi[k] = float(np.percentile(a, 5)), float(np.percentile(a, 95))

    def norm(self, k, x):
        return float(np.clip((x - self.lo[k]) / (self.hi[k] - self.lo[k] + 1e-9), 0, 1))

    def _levels_and_activity(self, now, beat):
        a2 = max(2, int(2 * beat * self.hfps))
        a8 = max(4, int(8 * beat * self.hfps))
        active = set()
        for n, k in LEVELS.items():
            h = self.hist[k]
            last = list(h)[-3:]
            self.levels[n] = self.norm(k, sum(last) / len(last))
            if len(h) < a2 + a8 or not self.on(n):
                continue
            arr = (np.asarray(h)[-(a2 + a8):] - self.lo[k]) / (self.hi[k] - self.lo[k] + 1e-9)
            arr = np.clip(arr, 0, 1)
            c2, prev = arr[-a2:].mean(), arr[:a8]
            d = abs(c2 - prev.mean())
            s = self.sens(n)
            if d / (prev.std() + 0.03) > ACTIVE_Z / s and d > ACTIVE_MIN / s:
                active.add(n)
        for n in RISING:                                # «рост активности» → событие
            if n in active and n not in self.active:
                self.fire(n, now, self.levels[n])
        win = 2 * beat
        n_act = len(active)
        n_act += (now - self.last[4] < win) + (now - self.last[1] < win)
        n_act += (now - self.last[12] < win) + (now - self.last[15] < win)
        self.active = active
        self.n_active = n_act
        ks = 1 if n_act == 0 else FIB[min(n_act, 8) - 1]
        self.ks = int(min(ks, self.params["ks_max"]))

    def _dropout(self, now, beat):
        """№15: RMS за 0.25 с ниже медианы на 6 дБ (ЧУВСТВ. уменьшает требуемый провал).
        Эпизод: повторно — только после возврата громкости (выше медианы − 3 дБ) и не чаще раза в 2 такта."""
        h = self.hist["rms"]
        if len(h) < 50:
            return
        med = float(np.median(np.asarray(h)))
        r = sum(self.rms_s) / len(self.rms_s)
        low = r < med - 6.0 / max(self.sens(15), 0.2)
        if r > med - 3.0:
            self.drop_armed = True
        if low and self.drop_armed and now - self.last[15] > 8 * beat:
            self.fire(15, now)
            self.last[15] = now
            self.drop_armed = False
        self.dropout_on = low

    # --------------------------------------------------------------- события
    def _events(self, now, beat):
        bar = 4 * beat
        a2 = int(2 * bar * self.hfps)
        a8 = int(8 * bar * self.hfps)
        if len(self.hist["rms"]) < a2 + a8 or now - self.t0 < 10 * bar:
            return
        # №1 смена части: ≥ 3 признака значимо сменились (2 такта против 8 предыдущих)
        s1 = self.sens(1)
        count = 0
        for k in SECTION_KEYS:
            arr = np.clip((np.asarray(self.hist[k])[-(a2 + a8):] - self.lo[k]) / (self.hi[k] - self.lo[k] + 1e-9), 0, 1)
            c2, prev = arr[-a2:].mean(), arr[:a8]
            d = abs(c2 - prev.mean())
            count += d / (prev.std() + 0.03) > 2.5 / s1 and d > 0.12 / s1
        if count >= 3 and now - self.last[1] > 8 * bar:
            self.last[1] = now
            self.fire(1, now, count)
        # №12 гармония: хрома 2 тактов далеко от 8 предыдущих
        ch = np.asarray(self.chroma_hist)[-(a2 + a8):]
        c2, c8 = ch[-a2:].mean(0), ch[:a8].mean(0)
        dist = 1 - float(c2 @ c8 / (np.linalg.norm(c2) * np.linalg.norm(c8) + 1e-9))
        self.dist_hist.append(dist)
        if len(self.dist_hist) > 20:
            dh = np.asarray(self.dist_hist)
            med = np.median(dh)
            z = (dist - med) / (1.4826 * np.median(np.abs(dh - med)) + 1e-9)
            s12 = self.sens(12)
            if z > 4 / s12 and dist > 0.02 / s12 and now - self.last[12] > 16 * bar:
                self.last[12] = now
                self.fire(12, now, z)
        # №14 ритмичность: ясность пульса за 8 с изменилась больше чем на 0.1; сила — крутизна
        c = list(self.conf_hist)
        if len(c) >= 32:
            d = float(np.mean(c[-16:]) - np.mean(c[-32:-16]))
            if abs(d) > 0.1 / self.sens(14) and now - self.last[14] > 8 * bar:
                self.last[14] = now
                self.fire(14, now, abs(d))
