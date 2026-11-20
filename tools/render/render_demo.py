"""SMENA — офлайн-демо алгоритма: подготовленные фото + трек → видео со звуком.

Реализует (упрощённо) SPEC v0.2: мастер-клок, роли past/master/future, въезд/выезд по лучам,
мгновенная смена фона на долю, полосы содержимого вдоль полярности, триггеры таблицы v2, ks, исключения №1/№12/№15.

Запуск (окружение .venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\render\\render_demo.py ТРЕК.mp3 КЕШ ВЫХОД.mp4
        [--bpm 139.6] [--dur 60] [--start auto|сек] [--events data/analysis/events.json --track 2]

Ускорение: всё фото проходят за --dur секунд, T = dur / число фото (вместо 16 тактов).
С 2026-10-17: появление мерцанием на месте (--flicker-in, SPEC §2.5), до 32 элементов на фото (въезды/выезды
группами), газетные вырезки (--news, SPEC §4.6).
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv
from PIL import Image, ImageDraw, ImageFont

SR, HOP, NFFT = 44100, 512, 2048
FR = SR / HOP                      # кадров признаков в секунду
W, H, FPS = 1280, 848, 30
FIB = [1, 1, 2, 3, 5, 8, 13, 21]   # ks по числу активных триггеров (1..8+)
ACTIVE_Z, ACTIVE_MIN = 1.0, 0.04   # триггер активен: изменение за 2 доли vs 8 предыдущих
TAIL_GUARD = 20.0                  # не брать последние N секунд трека (затухание)
ENTRY_BEATS = 4                    # длительность въезда элемента, долей (медленно)
SOLO_BARS = 4                      # «моно-показ» master без future, тактов
FLICKER_BEATS = 1                  # мерцание перед исчезновением в исключениях №1/№12
FLICKER_IN = 0.15                  # доля появлений мерцанием на месте вместо въезда (SPEC §2.5; --flicker-in)
STRIP_F = (0.75, 1.25)             # разброс скоростей полос (меньше — мягче швы)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
RNG = np.random.default_rng(7)


# ============================================================ звук и признаки
def load_audio(path):
    p = subprocess.run([FFMPEG, "-v", "quiet", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32).reshape(-1, 2)


def features(a):
    mono, side = a.mean(1), (a[:, 0] - a[:, 1]) / 2
    n = (len(mono) - NFFT) // HOP + 1
    fr = swv(mono, NFFT)[::HOP][:n]
    fs = swv(side, NFFT)[::HOP][:n]
    freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    win = np.hanning(NFFT).astype(np.float32)
    P = np.empty((n, len(freqs)), np.float32)
    for s in range(0, n, 4096):
        P[s:s + 4096] = np.abs(np.fft.rfft(fr[s:s + 4096] * win, axis=1)) ** 2 + 1e-12
    F = {}
    band = lambda lo, hi: P[:, (freqs >= lo) & (freqs < hi)].sum(1)
    F["sub"], F["bass"], F["lowmid"] = band(20, 60), band(60, 150), band(150, 500)
    F["mid"], F["himid"], F["high"] = band(500, 2000), band(2000, 6000), band(6000, 16000)
    F["rms"] = np.sqrt((fr ** 2).mean(1))
    F["side"] = np.sqrt((fs ** 2).mean(1)) / (F["rms"] + 1e-6)
    F["centroid"] = (P * freqs).sum(1) / P.sum(1)
    Pm = P[:, (freqs > 50) & (freqs < 16000)]
    F["flat"] = np.exp(np.log(Pm).mean(1)) / Pm.mean(1)
    lg = np.log1p(np.sqrt(P) * 100)
    d = np.diff(lg, axis=0, prepend=lg[:1]).clip(0)
    F["flux"] = d[:, freqs < 16000].sum(1)
    F["flux_bass"] = d[:, (freqs >= 40) & (freqs < 150)].sum(1)
    F["flux_himid"] = d[:, (freqs >= 2000) & (freqs < 6000)].sum(1)
    F["flux_high"] = d[:, (freqs >= 6000) & (freqs < 16000)].sum(1)
    cm = (freqs >= 55) & (freqs < 4200)
    pc = np.round(69 + 12 * np.log2(freqs[cm] / 440)).astype(int) % 12
    ch = np.stack([P[:, cm][:, pc == i].sum(1) for i in range(12)], 1)
    ch /= ch.sum(1, keepdims=True)
    F["tonal"] = 1 - (-(ch * np.log(ch + 1e-12)).sum(1)) / np.log(12)
    F["chroma"] = ch
    # доля ударного: HPSS по 64 лог-полосам
    edges = np.geomspace(30, 16000, 65)
    lb = np.stack([P[:, (freqs >= edges[i]) & (freqs < edges[i + 1])].sum(1) for i in range(64)], 1)
    Hh = np.median(swv(np.pad(lb, ((15, 15), (0, 0)), mode="edge"), 31, axis=0), axis=-1)
    Pp = np.median(swv(np.pad(lb, ((0, 0), (4, 4)), mode="edge"), 9, axis=1), axis=-1)
    F["perc"] = Pp.sum(1) / (Pp.sum(1) + Hh.sum(1) + 1e-12)
    # пульсация яркости и баса внутри такта (окно ~1 такт)
    k = int(FR * 1.7)
    lc = np.log2(F["centroid"] + 1)
    F["lfo"] = np.sqrt(np.maximum(np.convolve(lc ** 2, np.ones(k) / k, "same") - np.convolve(lc, np.ones(k) / k, "same") ** 2, 0))
    lbass = 10 * np.log10(F["bass"] + 1e-10)
    F["wobble"] = np.sqrt(np.maximum(np.convolve(lbass ** 2, np.ones(k) / k, "same") - np.convolve(lbass, np.ones(k) / k, "same") ** 2, 0))
    for key in ("sub", "bass", "lowmid", "mid", "himid", "high"):
        F[key] = 10 * np.log10(F[key] + 1e-10)
    F["rms"] = 20 * np.log10(F["rms"] + 1e-9)
    F["centroid"] = np.log2(F["centroid"])
    F["flat"] = np.log10(F["flat"] + 1e-9)
    return F


def norm01(x):
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)


def onsets(x, z_thr, min_gap):
    """Пики выше локального фона (медиана/MAD за 4 с)."""
    n, h = len(x), int(2 * FR)
    med = np.array([np.median(x[max(0, i - h):i + h]) for i in range(0, n, 16)]).repeat(16)[:n]
    mad = np.array([np.median(np.abs(x[max(0, i - h):i + h] - np.median(x[max(0, i - h):i + h])))
                    for i in range(0, n, 16)]).repeat(16)[:n] * 1.4826 + 1e-9
    z = (x - med) / mad
    out, last = [], -1e9
    for i in np.flatnonzero(z > z_thr):
        if z[i] == z[max(0, i - 8):i + 9].max() and i / FR - last > min_gap:
            out.append((i / FR, float(z[i])))
            last = i / FR
    return out


def trail(x, w):
    """Скользящее среднее за последние w кадров (только прошлое — как в живом режиме)."""
    c = np.cumsum(np.r_[np.zeros((1,) + x.shape[1:]), x], axis=0)
    i = np.arange(len(x)) + 1
    return (c[i] - c[np.maximum(i - w, 0)]) / np.minimum(i, w).reshape((-1,) + (1,) * (x.ndim - 1))


def estimate_bpm(F, lo=90, hi=180):
    """Темп по автокорреляции атак: гребёнка по 32 долям, шаг 0.05 BPM; предпочтение 110–150."""
    e = F["flux"] + F["flux_bass"]
    k = int(FR * 0.4)
    env = np.maximum(e - np.convolve(e, np.ones(k) / k, "same"), 0)
    env -= env.mean()
    n = len(env)
    f = np.fft.rfft(env, 2 * n)
    acf = np.fft.irfft(f * np.conj(f))[:n]
    acf /= acf[0]
    best, best_s = 120.0, -1e9
    for bpm in np.arange(lo, hi, 0.05):
        lags = np.arange(1, 33) * 60 * FR / bpm
        i = lags.astype(int)
        ok = i + 1 < n
        sc = np.mean(acf[i[ok]] * (1 - (lags[ok] - i[ok])) + acf[i[ok] + 1] * (lags[ok] - i[ok]))
        sc *= np.exp(-0.5 * (np.log2(bpm / 130) / 0.6) ** 2)
        if sc > best_s:
            best, best_s = bpm, sc
    return round(float(best), 2)


def detect_events(F, beat):
    """События по самому звуку (без заранее посчитанного анализа), только по прошлому:
    смена части — значимо сменились ≥ 3 признака (2 такта против 8 предыдущих);
    смена гармонии — хрома 2 тактов далеко от 8 предыдущих."""
    bar = int(4 * beat * FR)
    a2, a8 = 2 * bar, 8 * bar
    n = len(F["rms"])
    count = np.zeros(n)
    for key in ("bass", "sub", "high", "centroid", "flat", "side", "perc", "mid", "lowmid", "rms"):
        x = norm01(F[key])
        c2 = trail(x, a2)
        prev = np.r_[np.full(a2, x[0]), x[:-a2]]
        c8 = trail(prev, a8)
        s8 = np.sqrt(np.maximum(trail(prev ** 2, a8) - c8 ** 2, 0))
        d = np.abs(c2 - c8)
        count += (d / (s8 + 0.03) > 2.5) & (d > 0.12)
    sections, last = [], -1e9
    for i in np.flatnonzero(count >= 3):
        if i > 10 * bar and i - last > 8 * bar and count[i] == count[max(0, i - bar):i + bar].max():
            sections.append({"t": i / FR}); last = i
    ch = F["chroma"]
    c2 = trail(ch, a2)
    c8 = trail(np.r_[np.repeat(ch[:1], a2, 0), ch[:-a2]], a8)
    dist = 1 - (c2 * c8).sum(1) / (np.linalg.norm(c2, axis=1) * np.linalg.norm(c8, axis=1) + 1e-9)
    z = (dist - np.median(dist)) / (1.4826 * np.median(np.abs(dist - np.median(dist))) + 1e-9)
    harmony, last = [], -1e9
    for i in np.flatnonzero((z > 4) & (dist > 0.02)):
        if i > 10 * bar and i - last > 16 * bar and z[i] == z[max(0, i - bar):i + bar].max():
            harmony.append({"t": i / FR}); last = i
    return {"Одновременная смена ≥3 признаков": sections, "Смена гармонии / тонального центра": harmony}


def beat_grid(F, bpm, dur):
    p = 60 * FR / bpm
    env = F["flux_bass"] + 0.3 * F["flux"]
    n = len(env)
    off = max(np.arange(0, p, 1.0), key=lambda o: env[np.arange(o, n, p).astype(int)].sum())
    return off / FR, 60 / bpm


# ============================================================ триггеры
LEVELS = {  # № таблицы: признак
    2: "bass", 3: "centroid", 5: "side", 6: "perc", 7: "tonal", 8: "flat", 9: "sub", 10: "high",
    11: "lowmid", 13: "flux_high", 16: "mid", 17: "lfo", 18: "himid", 19: "rms", 20: "wobble",
}
NAMES = {1: "смена части", 2: "бас", 3: "яркость", 4: "акцент", 5: "стерео", 6: "доля ударного",
         7: "тональность", 8: "шумность", 9: "суббас", 10: "верх", 11: "низ. середина", 12: "гармония",
         13: "хэты", 14: "ритмичность", 15: "обрыв", 16: "середина", 17: "LFO", 18: "2–6 кГц",
         19: "громкость", 20: "wobble"}


class Triggers:
    def __init__(self, F, events, t0, dur, beat0, beat):
        self.t0, self.beat0, self.beat = t0, beat0, beat
        self.L = {k: norm01(F[v]) for k, v in LEVELS.items()}
        self.n = len(F["rms"])
        # активность за последние 2 доли: значимое изменение относительно 8 предыдущих
        a2, a8 = int(2 * beat * FR), int(8 * beat * FR)
        self.active = {}
        for k, x in self.L.items():
            c2 = np.convolve(x, np.ones(a2) / a2, "full")[:self.n]
            c8 = np.convolve(np.r_[np.zeros(a2), x][:self.n], np.ones(a8) / a8, "full")[:self.n]
            s8 = np.sqrt(np.maximum(np.convolve(np.r_[np.zeros(a2), x][:self.n] ** 2, np.ones(a8) / a8, "full")[:self.n] - c8 ** 2, 1e-6))
            self.active[k] = (np.abs(c2 - c8) / (s8 + 0.03) > ACTIVE_Z) & (np.abs(c2 - c8) > ACTIVE_MIN)
        self.accents = onsets(F["flux"], 6, 0.25)
        self.kicks = onsets(F["flux_bass"], 3, 0.18)
        self.himid_on = onsets(F["flux_himid"], 4, 0.15)
        # обрывы: RMS (0.25 с) ниже медианы на 6 дБ
        k = int(0.25 * FR)
        r = np.convolve(F["rms"], np.ones(k) / k, "same")
        low = r < np.median(r) - 6
        self.drop_t = np.flatnonzero(low) / FR
        ev = events or {}
        self.section = [e["t"] for e in ev.get("Одновременная смена ≥3 признаков", [])]
        self.harmony = [e["t"] for e in ev.get("Смена гармонии / тонального центра", [])]
        self.pulse = [e["t"] for e in ev.get("Ритмичность (ясность пульса)", [])]

    def idx(self, ta):
        return min(max(int(ta * FR), 0), self.n - 1)

    def level(self, k, ta):
        return float(self.L[k][self.idx(ta)])

    def is_active(self, k, ta):
        return bool(self.active[k][self.idx(ta)])

    def rising(self, k, ta, dt):
        return self.is_active(k, ta) and not self.is_active(k, ta - dt)

    def recent(self, lst, ta, win):
        return [e for e in lst if ta - win < (e[0] if isinstance(e, tuple) else e) <= ta]

    def n_active(self, ta):
        win = 2 * self.beat
        n = sum(self.is_active(k, ta) for k in self.L)
        n += bool(self.recent(self.accents, ta, win)) + bool(self.recent(self.section, ta, win))
        n += bool(self.recent(self.harmony, ta, win)) + bool(self.dropout(ta))
        return n

    def ks(self, ta):
        n = self.n_active(ta)
        return 1 if n == 0 else FIB[min(n, 8) - 1]

    def dropout(self, ta):
        return np.any((self.drop_t > ta - self.beat) & (self.drop_t <= ta))

    def phase(self, ta):
        return ((ta - self.beat0) / self.beat) % 1.0

    def snap(self, ta):   # к ближайшей следующей доле (предсказуемо, без задержки)
        k = math.ceil((ta - self.beat0) / self.beat - 1e-6)
        return self.beat0 + k * self.beat


def choose_start(events, F, dur, beat0, beat, track_len):
    """Самая активная минута: плотность значимых событий (секции/гармония ×3) + энергия."""
    w = {"Одновременная смена ≥3 признаков": 3, "Смена гармонии / тонального центра": 3,
         "Ритмичность (ясность пульса)": 2}
    ts = []
    for name, lst in (events or {}).items():
        for e in lst:
            ts.append((e["t"], w.get(name, 1)))
    energy = norm01(F["rms"])
    best, best_s = 0.0, -1
    for s in np.arange(0, max(1.0, track_len - TAIL_GUARD - dur), 1.0):
        sc = sum(wt for t, wt in ts if s <= t < s + dur) + 5 * energy[int(s * FR):int((s + dur) * FR)].mean()
        if sc > best_s:
            best, best_s = s, sc
    bar = 4 * beat
    return beat0 + math.floor((best - beat0) / bar) * bar


# ============================================================ фото и элементы
def fit_photo(folder):
    meta = json.loads((folder / "photo.json").read_text(encoding="utf-8"))
    bg = np.array(Image.open(folder / "background.png").convert("RGB"))
    pw, ph = meta["size"]
    s = min(W / pw, H / ph)
    nw, nh = round(pw * s), round(ph * s)
    ox, oy = (W - nw) // 2, (H - nh) // 2
    canvas = cv2.resize(bg, (W, H), interpolation=cv2.INTER_AREA) if (nw, nh) == (W, H) else None
    if canvas is None:   # вертикальные фото: размытая подложка + фото по центру
        cover = s_c = max(W / pw, H / ph)
        cw, chh = round(pw * s_c), round(ph * s_c)
        big = cv2.resize(bg, (cw, chh))
        cx, cy = (cw - W) // 2, (chh - H) // 2
        canvas = (cv2.GaussianBlur(big[cy:cy + H, cx:cx + W], (0, 0), 25) * 0.45).astype(np.uint8)
        canvas[oy:oy + nh, ox:ox + nw] = cv2.resize(bg, (nw, nh), interpolation=cv2.INTER_AREA)
    els = []
    for e in meta["elements"]:
        rgba = np.array(Image.open(folder / e["file"]).convert("RGBA"))
        x, y, w, h = e["bbox"]
        w2, h2 = max(2, round(w * s)), max(2, round(h * s))
        rgba = cv2.resize(rgba, (w2, h2), interpolation=cv2.INTER_AREA)
        hx, hy = ox + round(x * s), oy + round(y * s)
        dists = {"left": hx, "right": W - (hx + w2), "top": hy, "bottom": H - (hy + h2)}
        edge = min(dists, key=dists.get)
        start = {"left": (-w2 - 10, hy), "right": (W + 10, hy), "top": (hx, -h2 - 10), "bottom": (hx, H + 10)}[edge]
        cx, cy = hx + w2 / 2 - W / 2, hy + h2 / 2 - H / 2
        nstrip = int(np.clip(round((h2 if e["polarity"] == "X" else w2) / 60), 2, 6))
        els.append(dict(
            id=e["id"], rgb=rgba[..., :3].astype(np.float32), a=rgba[..., 3:].astype(np.float32) / 255,
            home=(hx, hy), start=start, half=e["half"], pol=e["polarity"],
            central=abs(cx) < W * 0.25, angle=(math.degrees(math.atan2(cx, -cy)) + 360) % 360,
            nstrip=nstrip, f=RNG.uniform(*STRIP_F, nstrip), d=RNG.choice([-1, 1], nstrip),
            off=np.zeros(nstrip), shake=(0.0, 0.0, 0.0, -9.0), bounce=-9.0, blink=-9.0,
            t_in=None, t_out=None, hidden_from=None, reenter=None, flicker=None,
            u_fin=RNG.random(),                              # появление мерцанием (SPEC §2.5), фиксировано
            news_from=None, news_len=0.0, news_tilt=0.0, paper=None))   # газетная вырезка (SPEC §4.6)
    return dict(name=meta["source"], bg=canvas.astype(np.float32), els=els,
                axis=meta.get("bg_axis_hint", "horizontal"))


# ============================================================ расписание (мастер-клок)
def schedule(photos, tr, T, P, dur):
    beat = tr.beat
    log = []
    rev, pointer = 0, 0
    solo = min(SOLO_BARS * 4 * beat, 0.3 * T)            # «моно-показ» master
    entry = ENTRY_BEATS * beat
    for k, ph in enumerate(photos):
        # --- цикл master (k-1): [0, P] past + master → [P, P+solo] только master →
        #     [P+solo, T) последовательно въезжают элементы future (photo k), по ритму
        if k == 0:
            for e in ph["els"]:
                e["t_in"] = -1.0
        else:
            a = (k - 1) * T + P + solo
            b = max(k * T - entry, a + beat)               # к смене фона все стоят на местах
            els = sorted(ph["els"], key=lambda e: e["angle"])
            n = len(els)
            # до 32 элементов (SPEC §3.1): не укладываются по одному в долю — по 1/2 или 1/4 доли
            st = beat if n * beat <= (b - a) else (beat / 2 if n * beat / 2 <= (b - a) else beat / 4)
            snap = lambda x: tr.beat0 + math.ceil((x - tr.beat0) / st - 1e-6) * st
            last = a - st
            for i, e in enumerate(els):
                slot = a + (i + 0.5) / n * (b - a)
                src = tr.kicks if e["half"] == "bottom" else tr.himid_on + tr.accents
                cand = [t - tr.t0 for t, _ in src if last + st <= t - tr.t0 <= slot]
                t_in = snap(tr.t0 + min(cand)) - tr.t0 if cand else snap(tr.t0 + max(slot, last + st)) - tr.t0
                e["t_in"] = min(t_in, b)
                last = e["t_in"]
        # --- уход past (photo k-1) в окне [kT, kT + P]: круговая замена + крайний срок
        if k >= 1:
            past = sorted(photos[k - 1]["els"], key=lambda e: e["angle"])   # по часовой
            a, b = k * T, k * T + P
            step, ti, queue = 0, tr.snap(tr.t0 + a) - tr.t0, list(past)
            per_step = max(1, math.ceil(len(past) / max(1.0, P / beat - 1)))   # до 32 — несколько за шаг
            while queue and ti < b:
                swing = beat / 3 if step % 2 else 0.0           # чётные шаги опаздывают
                ks = tr.ks(tr.t0 + ti)
                if step % ks == 0:
                    for _ in range(min(per_step, len(queue))):
                        e = queue.pop(0)
                        e["t_out"] = ti + swing
                        pointer += 1
                        if pointer % max(1, len(past)) == 0:
                            rev += 1
                # №9 суббас / №19 громкость: дополнительная замена нижнего / верхнего
                for num, half in ((9, "bottom"), (19, "top")):
                    if tr.rising(num, tr.t0 + ti, beat) and queue:
                        cand = [e for e in queue if e["half"] == half]
                        if cand:
                            queue.remove(cand[0])
                            cand[0]["t_out"] = ti + 0.25 * beat
                step += 1
                ti += beat
            for e in queue:                                     # крайний срок мастер-клока
                e["t_out"] = b
            log.append((k, rev))
    return log


# ============================================================ рендер
def ease_out(u):
    return 1 - (1 - u) ** 3


def element_frame(e, t, tr, ta, dt, stepped, pal):
    """Смещает полосы содержимого и считает позицию/угол элемента."""
    L = lambda k: tr.level(k, ta)
    ks = pal["ks"]
    if e["pol"] == "Y":
        drive = L(10)                                     # №10 верх → содержимое по Y
    else:
        drive = L(11) if e["central"] else 0.5 * L(17)    # №11 низкая середина → по X (центр)
    speed = (8 + 90 * drive) * (0.5 + 1.2 * L(17)) / ks    # №17 скорость / ks (мягче)
    if e["id"] % 2 == 0:                                   # №16 пульс паттерна некоторых элементов
        speed *= 1 + 0.8 * L(16) * max(0.0, math.cos(2 * math.pi * pal["phase"])) ** 4
    if not stepped or pal["step_tick"]:
        e["off"] += speed * e["f"] * e["d"] * (dt if not stepped else pal["step_dt"])
    # позиция самого элемента
    hx, hy = e["home"]
    dx = dy = ang = 0.0
    if e["half"] == "bottom":
        dx += W * 0.012 * (pal["bass_s"] - 0.5) * 2       # №2 бас → X
    else:
        dx += W * 0.010 * (pal["side_s"] - 0.5) * 2       # №5 стерео → X
        ang = -6.0 * max(0.0, pal["cent_s"] - 0.45) / 0.55  # №3 яркость → поворот по часовой
        if t - e["bounce"] < 0.4:                          # №18 отскок
            dy -= 14 * math.exp(-(t - e["bounce"]) / 0.12)
        if L(13) > 0.85:                                   # №13 дрожь верхних
            dx += RNG.uniform(-2, 2); dy += RNG.uniform(-2, 2)
    a0, sx, sy, amp = e["shake"]                           # №4 встряска
    if t - a0 < 0.4:
        k = amp * math.exp(-(t - a0) / 0.1) * math.sin(2 * math.pi * 16 * (t - a0))
        dx += sx * k; dy += sy * k
    # въезд / выезд по лучу
    x, y = hx + dx, hy + dy
    sx0, sy0 = e["start"]
    entry = ENTRY_BEATS * tr.beat
    fin = e["u_fin"] < FLICKER_IN                                      # появление мерцанием — без въезда
    if e["t_in"] is not None and t < e["t_in"] + entry and not fin:   # медленный въезд по лучу
        u = 0.0 if t < e["t_in"] else (t - e["t_in"]) / entry
        if stepped:
            u = math.floor(u * 8) / 8
        u = ease_out(min(1.0, u))
        x, y = sx0 + (x - sx0) * u, sy0 + (y - sy0) * u
    if e["t_out"] is not None and t > e["t_out"]:
        u = min(1.0, (t - e["t_out"]) / tr.beat) ** 2
        x, y = x + (sx0 - x) * u, y + (sy0 - y) * u
    if e["reenter"] is not None and e["reenter"] <= t < e["reenter"] + entry / 2 and not fin:   # после №1
        u = ease_out((t - e["reenter"]) / (entry / 2))
        x, y = sx0 + (x - sx0) * u, sy0 + (y - sy0) * u
    return x, y, ang


def element_pixels(e, vib):
    """RGB элемента со сдвигом полос содержимого + альфа (силуэт стоит)."""
    rgb, a = e["rgb"], e["a"]
    h, w = a.shape[:2]
    if e["nstrip"] > 1:                                    # полосы содержимого вдоль полярности
        rgb = rgb.copy()
        bands = np.linspace(0, h if e["pol"] == "X" else w, e["nstrip"] + 1).astype(int)
        for j in range(e["nstrip"]):
            o = int(e["off"][j] + (RNG.uniform(-vib, vib) if vib else 0))
            s0, s1 = bands[j], bands[j + 1]
            n = w if e["pol"] == "X" else h
            idx = (np.arange(n) - o) % (2 * n)             # зеркальное повторение — без шва на краю
            idx = np.where(idx < n, idx, 2 * n - 1 - idx)
            if e["pol"] == "X":
                rgb[s0:s1] = rgb[s0:s1][:, idx]
            else:
                rgb[:, s0:s1] = rgb[:, s0:s1][idx]
    return rgb, a


def draw_element(canvas, e, x, y, ang, vib):
    rgb, a = element_pixels(e, vib)
    paste(canvas, rgb, a, x, y, ang)


def paste(canvas, rgb, a, x, y, ang):
    h, w = a.shape[:2]
    if abs(ang) > 0.2:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        rgb = cv2.warpAffine(rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        a = cv2.warpAffine(a, M, (w, h))
        a = a[..., None] if a.ndim == 2 else a
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    rs = rgb[y0 - y:y1 - y, x0 - x:x1 - x]
    al = a[y0 - y:y1 - y, x0 - x:x1 - x]
    canvas[y0:y1, x0:x1] = canvas[y0:y1, x0:x1] * (1 - al) + rs * al


def news_paper(e):
    """Бумага газетной вырезки (SPEC §4.6): кайма с неровным краем «как от ножниц» + размытая копия для тени."""
    if e["paper"] is None:
        a = (e["a"][..., 0] > 0.5).astype(np.uint8)
        h, w = a.shape
        r = int(np.clip(round(0.035 * min(w, h)), 3, 14))
        r2 = int(r * 1.8)
        M = r2 + r + 2
        A = np.pad(a, M)
        small = cv2.dilate(A, np.ones((2 * r + 1, 2 * r + 1), np.uint8))
        big = cv2.dilate(A, np.ones((2 * r2 + 1, 2 * r2 + 1), np.uint8))
        H2, W2 = A.shape
        g = RNG.random((H2 // 6 + 2, W2 // 6 + 2))
        noise = np.kron(g, np.ones((6, 6)))[:H2, :W2] > 0.55
        p = ((small > 0) | ((big > 0) & noise)).astype(np.float32)
        blur = cv2.GaussianBlur(p, (0, 0), max(1.0, r / 2))
        sh = np.zeros_like(blur)
        dx, dy = int(0.35 * M), int(0.45 * M)                # тень вниз-вправо
        sh[dy:, dx:] = blur[:H2 - dy, :W2 - dx]
        e["paper"] = (M, p, sh)
    return e["paper"]


def draw_news(canvas, e, x, y, ang, vib, k):
    """Элемент как газетная вырезка: тень → светлая бумага без желтизны → элемент, лёгкое обесцвечивание."""
    rgb, a = element_pixels(e, vib)
    M, p, sh = news_paper(e)
    lum = (rgb * np.array([0.299, 0.587, 0.114], np.float32)).sum(2, keepdims=True)
    rgb = rgb * (1 - 0.22 * k) + lum * (0.22 * k)
    rgbP = np.pad(rgb, ((M, M), (M, M), (0, 0)), mode="edge")
    aP = np.pad(a, ((M, M), (M, M), (0, 0)))
    pa = (p * k)[..., None]
    sa = (sh * 0.45 * k)[..., None]
    col = np.zeros_like(rgbP) * (1 - pa) + np.float32(0.935 * 255) * pa
    alpha = sa + pa * (1 - sa)
    col = col * (1 - aP) + rgbP * aP
    alpha = alpha + aP * (1 - alpha)
    paste(canvas, col, alpha, x - M, y - M, ang)




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("cache")
    ap.add_argument("out")
    ap.add_argument("--bpm", default="auto", help="число или auto")
    ap.add_argument("--dur", type=float, default=60.0)
    ap.add_argument("--start", default="auto")
    ap.add_argument("--events", default=None)
    ap.add_argument("--track-id", default="2")
    ap.add_argument("--photos", default=None, help="через запятую: 06,08,10 (по умолчанию все)")
    ap.add_argument("--normal", action="store_true", help="нормальная скорость: T = 16 тактов, dur = фото × T")
    ap.add_argument("--tbars", type=float, default=None, help="T в тактах при заданной --dur (берутся первые фото)")
    ap.add_argument("--skip", type=float, default=0.0, help="первые N секунд моделировать, но не записывать")
    ap.add_argument("--flicker-in", type=float, default=0.15, help="доля появлений мерцанием на месте (SPEC §2.5)")
    ap.add_argument("--news", type=float, default=12, help="газетные вырезки: в среднем раз в N тактов; 0 — выкл (§4.6)")
    a = ap.parse_args()
    global FLICKER_IN
    FLICKER_IN = a.flicker_in
    dirs = [d for d in sorted(Path(a.cache).iterdir()) if (d / "photo.json").exists()]
    if a.photos:
        want = a.photos.split(",")
        dirs = [d for d in dirs if d.name in want]
    print("звук и признаки…", flush=True)
    audio = load_audio(a.track)
    F = features(audio)
    track_len = len(audio) / SR
    a.bpm = estimate_bpm(F) if a.bpm == "auto" else float(a.bpm)
    print(f"темп: {a.bpm} BPM", flush=True)
    if a.normal:
        a.dur = len(dirs) * 64 * 60 / a.bpm
    if a.tbars:
        need = math.ceil(a.dur / (a.tbars * 4 * 60 / a.bpm) - 1e-6)
        dirs = dirs[:need]
    beat0, beat = beat_grid(F, a.bpm, track_len)
    if a.events:
        events = {k: v.get(a.track_id, []) for k, v in json.loads(Path(a.events).read_text(encoding="utf-8"))["results"].items()}
    else:
        events = detect_events(F, 60 / a.bpm)
        print(f"события по звуку: смен части {len(events['Одновременная смена ≥3 признаков'])}, "
              f"смен гармонии {len(events['Смена гармонии / тонального центра'])}", flush=True)
    t0 = choose_start(events, F, a.dur, beat0, beat, track_len) if a.start == "auto" else float(a.start)
    tr = Triggers(F, events, t0, a.dur, beat0, beat)

    photos = [fit_photo(d) for d in dirs]
    N = len(photos)
    T = a.tbars * 4 * beat if a.tbars else a.dur / N
    P = 0.3 * T
    print(f"фрагмент {int(t0 // 60)}:{t0 % 60:04.1f}–{int((t0 + a.dur) // 60)}:{(t0 + a.dur) % 60:04.1f}, "
          f"{N} фото, T = {T:.2f} с ({T / (64 * beat):.2f} от 16 тактов), P = {P:.2f} с, доля {beat:.3f} с", flush=True)
    schedule(photos, tr, T, P, a.dur)

    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    font_b = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
    outs = {}
    for tag in ("", "_hud"):
        path = Path(a.out).with_name(Path(a.out).stem + tag + ".mp4")
        outs[tag] = subprocess.Popen(
            [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "-", "-ss", f"{t0 + a.skip:.3f}", "-t", f"{a.dur - a.skip:.3f}", "-i", str(a.track),
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", str(path)], stdin=subprocess.PIPE)

    dt = 1 / FPS
    bass_s = side_s = cent_s = 0.5
    labels = []                 # (до какого времени, текст)
    sec_seen, harm_seen = set(), set()
    prev_step = -1
    nframes = int(a.dur * FPS)
    ks_hist = []
    next_news = a.news * 4 * beat * RNG.uniform(0.67, 1.33) if a.news > 0 else 1e9
    news_draw = []
    for fi in range(nframes):
        t = fi * dt
        ta = t0 + t
        k = min(int(t // T), N - 1)
        master, past = photos[k], photos[k - 1] if k >= 1 else None
        future = photos[k + 1] if k + 1 < N else None
        phase = tr.phase(ta)
        stepped = tr.level(6, ta) > 0.55                     # №6 почерк
        step_idx = int((ta - beat0) / (beat / 4))
        step_tick = step_idx != prev_step
        prev_step = step_idx
        bass_s += (tr.level(2, ta) - bass_s) * dt / 0.6
        side_s += (tr.level(5, ta) - side_s) * dt / 1.5
        cent_s += (tr.level(3, ta) - cent_s) * dt / 0.8
        ks = tr.ks(ta)
        ks_hist.append(ks)
        pal = dict(ks=ks, phase=phase, stepped=stepped, step_tick=step_tick, step_dt=beat / 4,
                   bass_s=bass_s, side_s=side_s, cent_s=cent_s)
        live = [e for ph in (past, master, future) if ph for e in ph["els"]]

        # --- импульсы
        for tz, z in tr.recent(tr.accents, ta, dt):            # №4 встряска
            sub = live if z > 12 else [e for e in live if RNG.random() < 0.5]
            for e in sub:
                ang = RNG.uniform(0, 2 * math.pi)
                e["shake"] = (t, math.cos(ang), math.sin(ang), 4 + min(10.0, z - 6))
            labels.append((t + 0.5, f"#4 акцент → встряска ({'все' if z > 12 else 'часть'})"))
        if tr.recent(tr.himid_on, ta, dt):                     # №18 отскок верхних
            for e in live:
                if e["half"] == "top":
                    e["bounce"] = t
        if tr.rising(7, ta, dt) and master["els"]:             # №7 мигание
            RNG.choice(master["els"])["blink"] = t
            labels.append((t + 0.6, "#7 тональность → мигание"))
        if tr.rising(13, ta, dt):                              # №13 смена паттерна по Y
            for e in live:
                if e["pol"] == "Y":
                    e["f"] = RNG.uniform(*STRIP_F, e["nstrip"]); e["d"] = RNG.choice([-1, 1], e["nstrip"])
            labels.append((t + 0.6, "#13 хэты → смена паттерна по Y"))
        fl = FLICKER_BEATS * beat
        for ts in tr.section:                                   # №1 смена части: мерцание → фон master → возврат
            if ts not in sec_seen and t0 <= ts <= ta:
                sec_seen.add(ts)
                for ph in (past, master, future):
                    if not ph:
                        continue
                    for e in ph["els"]:
                        e["flicker"] = t
                        if ph is master:
                            e["reenter"] = t + fl + beat         # 1 доля — только фон master
                        elif ph is past:
                            e["hidden_from"] = t + fl if e["hidden_from"] is None else e["hidden_from"]
                        elif e["t_in"] is not None and e["t_in"] <= t:
                            e["t_in"] = t + fl + 2 * beat        # future въедет заново
                labels.append((t + 1.5, "#1 смена части → мерцание и сброс до фона master"))
        for ts in tr.harmony:                                   # №12 гармония: past и future мерцают и исчезают
            if ts not in harm_seen and t0 <= ts <= ta:
                harm_seen.add(ts)
                for ph in (past, future):
                    if ph:
                        for e in ph["els"]:
                            e["flicker"] = t
                            if ph is past:
                                e["hidden_from"] = t + fl
                            elif e["t_in"] is not None and e["t_in"] <= t:
                                e["t_in"] = t + fl + 2 * beat     # future въедет заново
                labels.append((t + 1.5, "#12 гармония → past и future мерцают и исчезают"))
        pwm = tr.dropout(ta)                                    # №15 обрыв → PWM для past
        if pwm:
            labels.append((t + dt, "#15 обрыв → PWM past"))
        if a.news > 0 and t >= next_news:                       # газетные вырезки — редко, случайно (§4.6)
            bar = 4 * beat
            start = beat0 + math.ceil((ta - beat0) / bar - 1e-6) * bar - t0
            cand = [e for ph in (master, future) if ph for e in ph["els"]
                    if e["t_in"] is not None and e["t_in"] <= t and e["hidden_from"] is None
                    and (e["news_from"] is None or t > e["news_from"] + e["news_len"])]
            if cand:
                kn = min(len(cand), int(RNG.choice([1, 1, 1, 2, 2, 3])))
                cand.sort(key=lambda e: -e["a"].size * RNG.uniform(0.3, 1.0))
                length = float(RNG.choice([4, 8])) * beat
                for e in cand[:kn]:
                    e["news_from"], e["news_len"] = start, length
                    e["news_tilt"] = float(RNG.choice([-1, 1]) * RNG.uniform(3, 6))
                labels.append((start + length, f"газетные вырезки: {kn} элем."))
            next_news = t + a.news * 4 * beat * RNG.uniform(0.67, 1.33)

        # --- фон: мгновенная смена на долю (граница цикла kT стоит на сильной доле)
        canvas = master["bg"].copy()

        # --- элементы: сначала past, потом master, потом future
        for ph in (past, master, future):
            if ph is None:
                continue
            for e in ph["els"]:
                if ph is future and (e["t_in"] is None or t < e["t_in"]):
                    continue
                if ph is past and ((e["t_out"] is not None and t > e["t_out"] + beat)
                                   or (e["hidden_from"] is not None and t >= e["hidden_from"])):
                    continue
                if ph is past and pwm and phase < 0.5:
                    continue
                if e["flicker"] is not None and e["flicker"] <= t < e["flicker"] + fl:   # мерцание
                    if int((t - e["flicker"]) / (beat / 8)) % 2 == 1:
                        continue
                elif ph is master and e["reenter"] is not None and t < e["reenter"]:
                    continue
                if t - e["blink"] < beat / 2 and int((t - e["blink"]) / (beat / 8)) % 2 == 0:
                    continue
                if e["u_fin"] < FLICKER_IN:                       # появление мерцанием на месте (§2.5)
                    t_app = e["reenter"] if e["reenter"] is not None and e["reenter"] <= t else e["t_in"]
                    if t_app is not None and t_app <= t < t_app + beat \
                            and int((t - t_app) / (beat / 8)) % 2 == 1:
                        continue
                x, y, ang = element_frame(e, t, tr, ta, dt, stepped, pal)
                vib = 3 * tr.level(8, ta) if e["half"] == "bottom" else 0.0   # №8 вибрация низа
                nf = e["news_from"]
                if nf is not None and nf <= t < nf + e["news_len"]:   # газетная вырезка — поверх остальных
                    r = (t - nf) / beat
                    kk = min(1.0, r / 0.25, (e["news_len"] / beat - r) / 0.25)
                    news_draw.append((e, x, y, ang + e["news_tilt"] * kk, vib, kk))
                    continue
                draw_element(canvas, e, x, y, ang, vib)
        for e, x, y, ang, vib, kk in news_draw:
            draw_news(canvas, e, x, y, ang, vib, kk)
        news_draw.clear()
        if t < a.skip:                                     # начало цикла — только моделируем
            continue
        if t - a.skip < 0.5:
            canvas *= (t - a.skip) / 0.5
        if t > a.dur - 0.5:
            canvas *= max(0.0, (a.dur - t) / 0.5)
        img = np.clip(canvas, 0, 255).astype(np.uint8)
        outs[""].stdin.write(img.tobytes())

        # --- версия с подписями
        hud = Image.fromarray(img)
        d = ImageDraw.Draw(hud, "RGBA")
        d.rectangle([0, H - 92, W, H], fill=(0, 0, 0, 170))
        nact = tr.n_active(ta)
        act = [n for n in LEVELS if tr.is_active(n, ta)]
        d.text((14, H - 86), f"SMENA · {Path(a.track).stem[:40]} {int(ta // 60)}:{ta % 60:04.1f} · T={T:.1f} с{'' if (a.normal or a.tbars) else ' (ускорено)'}", font=font_b, fill="white")
        roles = f"past {past['name'] if past else '—'}   ·   MASTER {master['name']}   ·   future {future['name'] if future else '—'}"
        d.text((14, H - 58), roles, font=font, fill=(255, 210, 120))
        d.text((14, H - 32), f"ks={ks} (активных {nact}): " + ", ".join(f"#{n} {NAMES[n]}" for n in act)[:120],
               font=font, fill=(150, 230, 190))
        bx = W - 150
        for i in range(4):
            on = int((ta - beat0) / beat) % 4 == i
            d.rectangle([bx + i * 34, 14, bx + i * 34 + 26, 40], fill=(255, 106, 61) if on else (60, 60, 60))
        labels = [lb for lb in labels if lb[0] > t]
        for j, (_, txt) in enumerate(labels[-4:]):
            d.text((14, 14 + j * 28), txt, font=font_b, fill=(255, 230, 0))
        outs["_hud"].stdin.write(np.array(hud).tobytes())
        if fi % 150 == 0:
            print(f"  кадр {fi}/{nframes}", flush=True)

    for p in outs.values():
        p.stdin.close()
        p.wait()
    u, c = np.unique(ks_hist, return_counts=True)
    print("ks по кадрам:", {int(x): f"{y / len(ks_hist) * 100:.0f}%" for x, y in zip(u, c)})
    print("готово:", ", ".join(str(Path(a.out).with_name(Path(a.out).stem + tag + ".mp4")) for tag in outs))


if __name__ == "__main__":
    main()
