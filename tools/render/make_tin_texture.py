r"""Текстура корпуса SMENA: старая жестяная коробка, крашенная бирюзой — краска в сетке трещин (кракелюр),
сколы до серого металла, ржавые пятна с тёмным ободком, грязь. Бесшовная плитка 768×768 →
smena/ui/theme/smena_pipboy/textures/tin.png.
Запуск: .venv-prep\Scripts\python.exe tools\render\make_tin_texture.py"""
from pathlib import Path

import numpy as np
from PIL import Image

N = 768
rng = np.random.default_rng(1957)
yy, xx = np.mgrid[0:N, 0:N]


def noise(scale, power=2.0):
    """Бесшовный шум: белый шум, отфильтрованный в спектре; scale — характерный размер пятен, пиксели."""
    f = np.sqrt(np.fft.fftfreq(N)[:, None] ** 2 + np.fft.fftfreq(N)[None, :] ** 2) * scale
    x = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((N, N))) / (1.0 + f ** power)))
    return (x - x.mean()) / (x.std() + 1e-9)


def blur(a, r):
    """Размытие по кругу (бесшовно) через БПФ."""
    f = np.sqrt(np.fft.fftfreq(N)[:, None] ** 2 + np.fft.fftfreq(N)[None, :] ** 2)
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(-(f * r * 2.5) ** 2)))


# краска: бирюза, неровный тон, мелкое зерно
paint = np.array([118, 176, 166], np.float32)
img = np.ones((N, N, 3), np.float32) * paint
img += noise(160)[..., None] * np.array([7, 9, 9]) + noise(30)[..., None] * 4 + rng.standard_normal((N, N, 1)) * 2.5

# кракелюр: границы ячеек Вороного (бесшовно — точки с копиями по краям)
pts = rng.uniform(0, N, (260, 2))
tiles = np.concatenate([pts + [dx, dy] for dx in (-N, 0, N) for dy in (-N, 0, N)])
d1 = np.full((N, N), 1e9, np.float32)
d2 = np.full((N, N), 1e9, np.float32)
for px, py in tiles:
    if not (-80 < px < N + 80 and -80 < py < N + 80):
        continue
    d = np.hypot(xx - px, yy - py).astype(np.float32)
    d2 = np.minimum(d2, np.maximum(d1, d))
    d1 = np.minimum(d1, d)
crack = np.clip(1.0 - (d2 - d1) / 1.6, 0, 1) * np.clip(noise(50) * 0.6 + 0.7, 0, 1)
img *= (1 - 0.2 * crack)[..., None]

# сколы краски: под ними металл, по краю скола — ржавчина
chip = noise(38) + noise(10) * 0.35
chip_m = np.clip((chip - 1.75) * 3.0, 0, 1)
rim = np.clip(blur(chip_m, 3) * 2.2 - chip_m, 0, 1)
metal = np.array([150, 148, 140], np.float32) * (0.8 + 0.2 * noise(5)[..., None])
rust = np.array([122, 62, 26], np.float32) * (0.75 + 0.3 * noise(4)[..., None])
inner = np.clip(noise(8) * 0.5 + 0.55, 0, 1)                    # внутри скола — металл или ржавчина
under = metal * (1 - inner[..., None]) + rust * inner[..., None]
img = img * (1 - chip_m[..., None]) + under * chip_m[..., None]
img = img * (1 - 0.8 * rim[..., None]) + np.array([92, 48, 22], np.float32) * (0.8 * rim[..., None])

# ржавые крапины с тёмным ободком
spots = (rng.random((N, N)) > 0.99975).astype(np.float32)
sp = np.clip(blur(spots, 2.5) * 30, 0, 1)
sp_rim = np.clip(blur(spots, 5) * 18 - sp, 0, 1)
img = img * (1 - sp[..., None]) + rust * sp[..., None]
img *= (1 - 0.45 * sp_rim)[..., None]

# потёки и грязь
streak = np.clip(blur(np.clip(noise(25), 0, None) * (np.sin(xx / N * 2 * np.pi * 3) > 0.6), 6), 0, 1)
img *= (1 - 0.18 * streak)[..., None]
dirt = np.clip(noise(90) * 0.5, 0, 1)
img = img * (1 - 0.25 * dirt[..., None]) + np.array([70, 60, 45], np.float32) * (0.25 * dirt[..., None])

out = np.clip(img * 0.92, 0, 255).astype(np.uint8)
dst = Path(__file__).resolve().parents[2] / "smena" / "ui" / "theme" / "smena_pipboy" / "textures" / "tin.png"
Image.fromarray(out).save(dst)
print(dst, out.mean(axis=(0, 1)))
