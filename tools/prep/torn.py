"""«Рваный край» крупных горизонтальных элементов (SPEC §3.1, решение 2026-10-17).

Кусок слоя = маска кандидата между двумя неровными линиями среза (вместо прямых краёв рамки):
  • боковые срезы — зигзаг, как разорванная бумага, отклонение ~2–5% ширины кадра
    (у края кадра срез не нужен — там кусок обрезан самой рамкой);
  • верх и низ — лёгкая неровность вдоль контура (подъедается 0…~1.2% высоты, кусок не дырявится).
Форма случайная, но воспроизводимая: зависит только от семени (пишется в selection: {"n", "box", "torn"}).
Общая функция для auto_select.py и build_elements.py.
"""
import numpy as np

SIDE_AMP = 0.035          # амплитуда бокового среза — доля ширины кадра
EDGE_AMP = 0.012          # подъедание верха/низа — доля высоты кадра


def _tear_line(rng, n, amp):
    """Смещения вдоль линии: плавные волны + блуждание + мелкие зубцы бумаги; |x| ≤ amp."""
    t = np.arange(n, dtype=np.float64)
    waves = sum(rng.uniform(0.4, 1.0) * np.sin(2 * np.pi * t / rng.uniform(0.15, 0.9) / max(n, 1)
                                                + rng.uniform(0, 2 * np.pi)) for _ in range(3))
    walk = np.cumsum(rng.normal(0, 1, n))
    walk -= np.linspace(walk[0], walk[-1], n)
    walk /= np.abs(walk).max() + 1e-9
    teeth = rng.uniform(-1, 1, n)
    line = 0.45 * waves / 3 + 0.4 * walk + 0.15 * teeth
    return line / (np.abs(line).max() + 1e-9) * amp


def torn_piece(mask, box, seed):
    """Маска куска: mask ∩ (неровные боковые срезы по рамке box) с подъеденными верхом и низом."""
    H, W = mask.shape
    x0, y0, x1, y1 = (int(v) for v in box)
    y0, y1 = max(0, y0), min(H, y1)
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    n = y1 - y0
    amp = SIDE_AMP * W
    left = np.full(n, float(x0)) + (_tear_line(rng, n, amp) if x0 > 0.01 * W else 0.0)
    right = np.full(n, float(x1)) + (_tear_line(rng, n, amp) if x1 < 0.99 * W else 0.0)
    cols = np.arange(W)[None, :]
    piece = np.zeros((H, W), bool)
    piece[y0:y1] = mask[y0:y1] & (cols >= left[:, None]) & (cols < right[:, None])
    # верх и низ: по столбцам подъедаем 0…a пикселей неровной линией
    a = max(2.0, EDGE_AMP * H)
    top = np.abs(_tear_line(rng, W, a)).astype(int)
    bot = np.abs(_tear_line(rng, W, a)).astype(int)
    c = np.cumsum(piece, axis=0)
    total = c[-1]
    keep = (c > top[None, :]) & (c <= (total - bot)[None, :])
    return piece & keep
