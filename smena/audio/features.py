"""Потоковые признаки звука по блокам 512 сэмплов.

Для индикаторов: шесть полос (sub / bass / lowmid / mid / himid / high) 0..1, RMS, центроид, поток атак для темпа.
Для триггеров (`raw`): полосы и RMS в дБ, центроид, плоскостность, стерео S/M, доля ударного (упрощённый HPSS),
хрома и тональность, атаки по полосам, пульсация яркости/баса — как `render_demo.features`, но по одному блоку.
"""
import math

import numpy as np

HOP = 512
NFFT = 2048

# полосы — как в таблице триггеров (05_TRIGGERS_FADERS.md)
BANDS = {
    "sub": (20, 60),
    "bass": (60, 150),
    "lowmid": (150, 500),
    "mid": (500, 2000),
    "himid": (2000, 6000),
    "high": (6000, 16000),
}
SILENCE_RMS = 2e-4
HPSS_FRAMES = 31          # гармоническая часть — медиана по ~0.33 с
LFO_WINDOW_S = 1.7        # окно пульсации внутри такта (render_demo: FR·1.7)


class AutoGain:
    """Нормализация к 0..1 по скользящему пику, который медленно затухает."""

    def __init__(self, fps, half_life_s, floor):
        self.decay = 0.5 ** (1.0 / (half_life_s * fps))
        self.peak = floor
        self.floor = floor

    def __call__(self, v):
        self.peak = max(v, self.peak * self.decay, self.floor)
        return min(v / self.peak, 1.0)


class Ema:
    def __init__(self, fps, tau_s):
        self.a = 1.0 - math.exp(-1.0 / (tau_s * fps))
        self.v = 0.0

    def __call__(self, x):
        self.v += self.a * (x - self.v)
        return self.v


class Features:
    def __init__(self, sr):
        self.sr = sr
        self.fps = sr / HOP
        freqs = np.fft.rfftfreq(NFFT, 1.0 / sr)
        self.masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
        self.flux_mask = freqs < 8000
        self.bass_flux_mask = (freqs >= 30) & (freqs < 150)
        self.window = np.hanning(NFFT).astype(np.float32)
        self.buf = np.zeros(NFFT, np.float32)
        self.prev_log = np.zeros(len(freqs), np.float32)
        self.gain = {k: AutoGain(self.fps, 15.0, 1e-5) for k in BANDS}
        self.smooth = {k: Ema(self.fps, 0.06) for k in BANDS}
        self.rms_smooth = Ema(self.fps, 0.08)
        self.freqs = freqs
        # --- для признаков триггеров (M3), как render_demo.features, но по одному блоку ---
        self.mask_full = (freqs > 50) & (freqs < 16000)
        self.flux_masks = {"flux_bass": (freqs >= 40) & (freqs < 150), "flux_himid": (freqs >= 2000) & (freqs < 6000),
                           "flux_high": (freqs >= 6000) & (freqs < 16000), "flux": freqs < 16000}
        cm = (freqs >= 55) & (freqs < 4200)
        pc = np.round(69 + 12 * np.log2(freqs[cm] / 440)).astype(int) % 12
        self.chroma_idx = np.flatnonzero(cm)
        self.chroma_pc = pc
        edges = np.geomspace(30, 16000, 65)               # 64 лог-полосы для упрощённого HPSS
        self.hp_bins = np.digitize(freqs, edges) - 1
        self.hp_ok = (self.hp_bins >= 0) & (self.hp_bins < 64)
        self.hp_hist = np.zeros((HPSS_FRAMES, 64), np.float32)
        self.hp_i = 0
        self.sbuf = np.zeros(NFFT, np.float32)
        n_lfo = int(LFO_WINDOW_S * self.fps)
        self.lc_hist = np.zeros(n_lfo, np.float32)          # log2 центроида — для №17 LFO
        self.lb_hist = np.zeros(n_lfo, np.float32)          # дБ баса — для №20 wobble
        self.lfo_i = 0
        self.raw = {}                                       # «сырые» признаки блока (дБ, лог) → triggers.py
        self.chroma = np.zeros(12, np.float32)

        # --- результат последнего блока (читается без блокировок) ---
        self.level = {k: 0.0 for k in BANDS}   # 0..1, нормировано по своему пику
        self.rms = 0.0                         # линейный, сглаженный
        self.rms_db = -90.0
        self.centroid = 0.0                    # 0..1
        self.flux = 0.0                        # атаки (всё ниже 8 кГц)
        self.bass_flux = 0.0                   # атаки баса — для фазы доли
        self.silent = True

    def process(self, x, side=None):
        """x — моно-блок длиной HOP, side — (L−R)/2 того же блока (для стерео-ширины)."""
        self.buf = np.concatenate((self.buf[len(x):], x.astype(np.float32)))
        spec = np.abs(np.fft.rfft(self.buf * self.window))
        if side is not None:
            self.sbuf = np.concatenate((self.sbuf[len(side):], side.astype(np.float32)))
        self._raw(spec)

        rms = float(np.sqrt(np.mean(self.buf[-HOP * 2:] ** 2)))
        self.silent = rms < SILENCE_RMS
        self.rms = self.rms_smooth(rms)
        self.rms_db = 20.0 * math.log10(self.rms + 1e-9)

        for k, m in self.masks.items():
            v = self.gain[k](float(spec[m].mean()))
            self.level[k] = self.smooth[k](0.0 if self.silent else v)

        w = spec[self.flux_mask]
        c = float((w * np.arange(len(w))).sum() / (w.sum() + 1e-9) / len(w)) * 3.0
        self.centroid = min(c, 1.0)

        # спектральный поток: положительный прирост лог-спектра
        log = np.log1p(spec * 100.0).astype(np.float32)
        diff = np.maximum(log - self.prev_log, 0.0)
        self.prev_log = log
        self.flux = 0.0 if self.silent else float(diff[self.flux_mask].sum())
        self.bass_flux = 0.0 if self.silent else float(diff[self.bass_flux_mask].sum())
        for k, m in self.flux_masks.items():
            self.raw[k] = 0.0 if self.silent else float(diff[m].sum())

    def _raw(self, spec):
        """Признаки таблицы триггеров по текущему окну (масштаб как в render_demo.features)."""
        P = spec.astype(np.float64) ** 2 + 1e-12
        r = self.raw
        for k, m in self.masks.items():
            r[k] = 10 * math.log10(P[m].sum() + 1e-10)
        rms = float(np.sqrt(np.mean(self.buf ** 2)))
        r["rms"] = 20 * math.log10(rms + 1e-9)
        r["side"] = float(np.sqrt(np.mean(self.sbuf ** 2))) / (rms + 1e-6)
        r["centroid"] = math.log2(max((P * self.freqs).sum() / P.sum(), 1.0))
        Pm = P[self.mask_full]
        r["flat"] = math.log10(math.exp(np.log(Pm).mean()) / Pm.mean() + 1e-9)
        # хрома и тональная ясность (1 − нормированная энтропия)
        ch = np.bincount(self.chroma_pc, weights=P[self.chroma_idx], minlength=12)
        ch = ch / (ch.sum() + 1e-12)
        self.chroma = ch.astype(np.float32)
        r["tonal"] = float(1 - (-(ch * np.log(ch + 1e-12)).sum()) / math.log(12))
        # доля ударного: гармоническое — медиана во времени, ударное — медиана по частоте (упрощённый HPSS)
        lb = np.bincount(self.hp_bins[self.hp_ok], weights=P[self.hp_ok], minlength=64)[:64].astype(np.float32)
        self.hp_hist[self.hp_i % HPSS_FRAMES] = lb
        self.hp_i += 1
        harm = np.median(self.hp_hist, axis=0)
        pad = np.pad(lb, 4, mode="edge")
        perc = np.median(np.lib.stride_tricks.sliding_window_view(pad, 9), axis=-1)
        r["perc"] = float(perc.sum() / (perc.sum() + harm.sum() + 1e-12))
        # пульсация яркости (№17) и баса (№20) внутри такта — разброс за ~1 такт
        i = self.lfo_i % len(self.lc_hist)
        self.lc_hist[i] = r["centroid"]
        self.lb_hist[i] = r["bass"]
        self.lfo_i += 1
        r["lfo"] = float(self.lc_hist.std())
        r["wobble"] = float(self.lb_hist.std())
