"""Темп и фаза доли: авто (автокорреляция атак) / tap / ×2 / ÷2 / ручной, сдвиг синхронизации,
сильная доля (начало такта). Треки без устойчивой сетки — условные 120 BPM (SPEC §2.1).

Логика оценки перенесена из app/audio_analyzer.py.
"""
import math
import threading
from collections import deque

import numpy as np

BPM_MIN, BPM_MAX = 70.0, 180.0
BPM_CENTER = 125.0        # куда тянуть при октавной неоднозначности (х2 / х0.5)
FALLBACK_BPM = 120.0      # условная сетка, пока темп не найден
TEMPO_WINDOW_S = 8.0      # сколько секунд истории для автокорреляции
TEMPO_EVERY_S = 0.5       # как часто пересчитывать темп
BEATS_PER_BAR = 4


class BeatTracker:
    def __init__(self, fps):
        self.fps = fps
        n_hist = int(TEMPO_WINDOW_S * fps)
        self.onset_env = deque([0.0] * n_hist, maxlen=n_hist)   # для темпа
        self.bass_env = deque([0.0] * n_hist, maxlen=n_hist)    # для фазы (бочка)
        self.every = max(1, int(TEMPO_EVERY_S * fps))
        self.hops = 0
        self._pending_bpm = None
        self._pending_n = 0
        self._taps = []
        self._lock = threading.Lock()

        self.bpm = 0.0             # найденный темп, 0 — не определён
        self.manual_bpm = 0.0      # >0 — зафиксирован вручную (tap / ×2 / ÷2 / число)
        self.confidence = 0.0
        self.beat_ref = 0.0        # время одной из долей (perf_counter)
        self.bar_offset = 0        # какая доля считается первой в такте
        self.sync_ms = 0.0         # сдвиг синхронизации (компенсация задержки)
        self._fallback_ref = 0.0

    # ---------------------------------------------------------------- вход
    def push(self, flux, bass_flux, now):
        self.onset_env.append(flux)
        self.bass_env.append(bass_flux)
        self.hops += 1
        if self.hops % self.every == 0:
            with self._lock:
                self._estimate_tempo(now)

    # ------------------------------------------------------ ручное управление
    def tap(self, now):
        """После 4 нажатий фиксирует темп и ставит долю на последний тап."""
        with self._lock:
            if self._taps and now - self._taps[-1] > 2.0:
                self._taps = []
            self._taps = (self._taps + [now])[-8:]
            if len(self._taps) >= 4:
                self.manual_bpm = 60.0 * (len(self._taps) - 1) / (self._taps[-1] - self._taps[0])
                self.bpm = self.manual_bpm
                self.beat_ref = now
            return len(self._taps)

    def scale(self, k):
        with self._lock:
            if self.bpm > 0:
                self.manual_bpm = self.bpm = min(max(self.bpm * k, 40.0), 300.0)

    def set_manual(self, bpm):
        with self._lock:
            self.manual_bpm = self.bpm = float(bpm)
            if self.beat_ref == 0.0:
                self.beat_ref = self._fallback_ref

    def set_auto(self):
        with self._lock:
            self.manual_bpm = 0.0
            self._taps = []

    def align_downbeat(self, now):
        """«Сильная доля»: ближайшая к нажатию доля становится первой в такте."""
        b = self.position(now)
        self.bar_offset = int(round(b["beat_f"])) % BEATS_PER_BAR

    # ----------------------------------------------------------------- выход
    @property
    def grid_bpm(self):
        return self.bpm if self.bpm > 0 else FALLBACK_BPM

    @property
    def conditional(self):
        """True — сетка условная (темп не найден)."""
        return self.bpm <= 0

    def position(self, t):
        """Положение на сетке в момент t: сквозная доля (дробная), фаза доли, доля в такте, такт."""
        bpm = self.grid_bpm
        ref = self.beat_ref
        if self.bpm <= 0 or ref == 0.0:
            if self._fallback_ref == 0.0:
                self._fallback_ref = t
            ref = self._fallback_ref
        x = (t + self.sync_ms / 1000.0 - ref) * bpm / 60.0
        beat = math.floor(x)
        rel = beat - self.bar_offset
        return {
            "beat_f": x,
            "phase": x - beat,
            "beat": beat,
            "in_bar": rel % BEATS_PER_BAR,
            "bar": rel // BEATS_PER_BAR,
            "period": 60.0 / bpm,
        }

    # ----------------------------------------------------------------- оценка
    def _estimate_tempo(self, now):
        env = np.asarray(self.onset_env, np.float64)
        if env.max() <= 0:
            self.bpm = self.manual_bpm
            self.confidence = 0.0
            return
        fps = self.fps
        # убираем медленную составляющую, оставляем только «щелчки»
        k = int(fps * 0.3)
        env = np.maximum(env - np.convolve(env, np.ones(k) / k, mode="same"), 0.0)
        env /= env.std() + 1e-9

        n = len(env)
        f = np.fft.rfft(env, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        ac /= ac[0] + 1e-9

        lag_lo = int(fps * 60 / BPM_MAX)
        lag_hi = int(fps * 60 / BPM_MIN) + 1
        lags = np.arange(lag_lo, lag_hi)
        score = ac[lags].copy()
        dbl = 2 * lags
        score[dbl < n] += 0.5 * ac[dbl[dbl < n]]       # гармоника (такт из 2 долей)
        bpms = fps * 60 / lags
        score *= np.exp(-0.5 * (np.log2(bpms / BPM_CENTER) / 0.9) ** 2)

        i = int(np.argmax(score))
        lag = float(lags[i])
        if 0 < i < len(score) - 1:                     # параболическое уточнение
            a, b, c = score[i - 1], score[i], score[i + 1]
            den = a - 2 * b + c
            if den != 0:
                lag += 0.5 * (a - c) / den
        conf = float(ac[lags[i]])
        new_bpm = fps * 60 / lag
        self.confidence = conf

        bass = np.asarray(self.bass_env, np.float64)
        if self.manual_bpm > 0:                         # темп задан вручную — только фаза
            self.bpm = self.manual_bpm
            if (not self._taps or now - self._taps[-1] > 4.0) and bass.max() > 0:
                self._estimate_phase(bass / (bass.std() + 1e-9), now)
            return

        if conf < 0.1:
            self.bpm = 0.0
            return

        # сглаживание: мелкие уточнения сразу, смена темпа — только если держится
        if self.bpm == 0.0:
            self.bpm = new_bpm
        elif abs(new_bpm - self.bpm) / self.bpm < 0.04:
            self.bpm = 0.8 * self.bpm + 0.2 * new_bpm
            self._pending_n = 0
        else:
            if self._pending_bpm and abs(new_bpm - self._pending_bpm) / self._pending_bpm < 0.04:
                self._pending_n += 1
            else:
                self._pending_bpm, self._pending_n = new_bpm, 1
            if self._pending_n >= 3:
                self.bpm, self._pending_n = new_bpm, 0
                self.beat_ref = 0.0   # фазу ищем заново

        # фаза — по бочке; если баса нет (брейк), то по общей огибающей
        self._estimate_phase(bass / (bass.std() + 1e-9) if bass.max() > 0 else env, now)

    def _estimate_phase(self, env, now):
        """Гребёнка с шагом в период: где огибающая лучше всего «ложится» на доли."""
        period = self.fps * 60 / self.bpm
        n = len(env)
        best_o, best_s = 0, -1.0
        for o in range(int(period)):
            idx = (n - 1 - o - np.arange(0, 16) * period).round().astype(int)
            idx = idx[idx >= 0]
            s = env[idx].sum()
            if s > best_s:
                best_o, best_s = o, s
        est = now - best_o / self.fps
        period_s = 60.0 / self.bpm
        if self.beat_ref == 0.0:
            self.beat_ref = est
            return
        # мягкая подстройка фазы, без скачков
        d = ((est - self.beat_ref) / period_s + 0.5) % 1.0 - 0.5
        self.beat_ref += 0.35 * d * period_s
