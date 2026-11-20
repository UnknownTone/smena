"""Простой эквалайзер выхода (вкладка ЗВУК): НИЗ 100 Гц / СЕР 1 кГц / ВЕРХ 8 кГц ±12 дБ, ГРОМКОСТЬ, БЕЗЗВУЧНО.

Действует на звук, который играет сама SMENA (режим «файл»), и на звук записи REC. Анализ (триггеры) слушает
звук до эквалайзера — иначе подкрутка EQ сбивала бы пороги.
Фильтр — КИХ с линейной фазой (1025 отводов, задержка ≈ 10 мс), свёртка через БПФ с перекрытием (overlap-save):
без scipy и без цикла по сэмплам. Пока все полосы на 0 дБ — фильтр не работает (только громкость).
"""
import threading

import numpy as np

TAPS = 1025
DELAY = (TAPS - 1) // 2


class Eq:
    def __init__(self, sr):
        self.sr = sr
        self.gains = (0.0, 0.0, 0.0)
        self.volume = 1.0
        self.mute = False
        self.h = None                       # КИХ; None — полосы на нуле
        self._hist = {}                     # хвост прошлого блока по числу каналов
        self._lock = threading.Lock()

    def set(self, lo, mid, hi, volume, mute):
        g = (float(lo), float(mid), float(hi))
        with self._lock:
            self.volume, self.mute = max(0.0, float(volume)), bool(mute)
            if g != self.gains:
                self.gains = g
                self.h = None if not any(g) else self._design(*g)

    def _design(self, lo, mid, hi):
        n = 4096
        f = np.fft.rfftfreq(n, 1.0 / self.sr)
        lf = np.log2(np.maximum(f, 1.0))
        shelf = lambda f0, up: 1.0 / (1.0 + np.exp(-(lf - np.log2(f0)) * 3.0 * (1 if up else -1)))
        db = lo * shelf(100.0, False) + mid * np.exp(-0.5 * ((lf - np.log2(1000.0)) / 0.8) ** 2) + hi * shelf(8000.0, True)
        H = 10 ** (db / 20.0)
        h = np.fft.irfft(H, n)
        h = np.roll(h, DELAY)[:TAPS] * np.hanning(TAPS)
        return h.astype(np.float32)

    def process(self, x):
        """x — (n, каналы) float32 → то же, после фильтра и громкости (новый массив)."""
        with self._lock:
            h, vol = self.h, 0.0 if self.mute else self.volume
        if h is None:
            self._hist.clear()
            return x * vol
        n, ch = x.shape
        hist = self._hist.get(ch)
        if hist is None:
            hist = np.zeros((TAPS - 1, ch), np.float32)
        buf = np.concatenate([hist, x], axis=0)
        self._hist[ch] = buf[-(TAPS - 1):]
        L = 1 << int(np.ceil(np.log2(len(buf))))
        Y = np.fft.rfft(buf, L, axis=0) * np.fft.rfft(h, L)[:, None]
        y = np.fft.irfft(Y, L, axis=0)[TAPS - 1:TAPS - 1 + n]
        return (y * vol).astype(np.float32)
