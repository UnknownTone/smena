r"""Три демо-«фото» советского брутализма для пробного набора (вместо личных снимков) — рисуются процедурно,
поэтому свободны от чужих прав. Косоугольная проекция, бетон из шума, падающие тени, небо, деревья, фигурки.

Запуск: .venv-prep\Scripts\python.exe tools\build\make_demo_photos.py <папка> [seed]
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

W, H = 3840, 1280                       # панорама ~3:1, как у демо-набора
SS = 1                                  # без суперсэмплинга: сглаживание — финальным размытием на 0.6 px


def noise(rng, h, w, scales=((8, 0.5), (32, 0.3), (128, 0.2))):
    """Многомасштабный шум 0..1."""
    acc = np.zeros((h, w), np.float32)
    for s, a in scales:
        small = rng.random((max(2, h // s), max(2, w // s))).astype(np.float32)
        acc += cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC) * a
    acc -= acc.min()
    return acc / max(acc.max(), 1e-6)


class Scene:
    def __init__(self, rng, ground, sun, kx=0.55, ky=0.32):
        self.rng = rng
        self.ground = ground                            # экранная линия земли (y) для z=0
        self.kx, self.ky = kx, ky                       # наклон глубины: z уходит вправо-вверх
        self.sun = np.array(sun, np.float32)            # (dx, dy) смещение тени на экране
        self.img = np.zeros((H, W, 3), np.float32)
        self.solid = np.zeros((H, W), np.float32)       # что уже нарисовано (здания) — туда падают тени
        conc = noise(rng, H, W, ((3, 0.35), (12, 0.3), (60, 0.35)))
        streak = cv2.resize(rng.random((8, W // 6)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
        self.tex = (0.78 + 0.28 * conc) * (0.9 + 0.14 * streak)       # бетон: зерно + вертикальные потёки

    def P(self, x, y, z):
        return (x + z * self.kx, self.ground - y - z * self.ky)

    def poly(self, pts, color, mask_only=False, tex=True):
        """Заливка многоугольника; считается только в его рамке (окон сотни — иначе медленно)."""
        a = np.array(pts, np.float32)
        x0, y0 = np.clip(np.floor(a.min(0)).astype(int) - 2, 0, (W, H))
        x1, y1 = np.clip(np.ceil(a.max(0)).astype(int) + 2, 0, (W, H))
        out = np.zeros((H, W), np.float32)
        if x1 <= x0 or y1 <= y0:
            return out
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(m, [np.round((a - (x0, y0)) * 8).astype(np.int32)], 255, lineType=cv2.LINE_AA, shift=3)
        mf = m.astype(np.float32)[..., None] / 255
        if not mask_only:
            c = np.array(color, np.float32)[None, None, :]
            fill = c * (self.tex[y0:y1, x0:x1, None] if tex else 1.0)
            reg = self.img[y0:y1, x0:x1]
            self.img[y0:y1, x0:x1] = reg * (1 - mf) + fill * mf
        out[y0:y1, x0:x1] = mf[..., 0]
        return out

    def shadow(self, mask, strength=0.55, soft=9):
        """Тень силуэта на уже нарисованное (смещение по солнцу)."""
        dx, dy = self.sun
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        sh = cv2.warpAffine(mask, M, (W, H))
        sh = cv2.GaussianBlur(sh, (0, 0), soft) * self.solid * (1 - mask)
        self.img *= (1 - strength * sh)[..., None]

    def box(self, x, y, z, w, h, d, base, windows=None, light=(1.0, 0.72, 1.18)):
        """Короб: перед, бок (правый), верх. windows(face_pts, ...) — рисует фасад."""
        f = [self.P(x, y, z), self.P(x + w, y, z), self.P(x + w, y + h, z), self.P(x, y + h, z)]
        s = [self.P(x + w, y, z), self.P(x + w, y, z + d), self.P(x + w, y + h, z + d), self.P(x + w, y + h, z)]
        t = [self.P(x, y + h, z), self.P(x + w, y + h, z), self.P(x + w, y + h, z + d), self.P(x, y + h, z + d)]
        b = np.array(base, np.float32)
        sil = np.zeros((H, W), np.float32)
        for pts, k in ((s, light[1]), (t, light[2]), (f, light[0])):
            sil = np.maximum(sil, self.poly(pts, b * k, mask_only=True))
        self.shadow(sil)
        ms = self.poly(s, b * light[1])
        self.poly(t, b * light[2])
        mf = self.poly(f, b * light[0])
        # затемнение к земле (грязь) и тонкое ребро
        if windows:
            windows(x, y, z, w, h)
        self.solid = np.maximum(self.solid, sil)
        return sil

    def win_grid(self, x0, y0, z, w, h, cols, rows, fw=0.55, fh=0.45, col=(28, 32, 38), deep=True, jitter=0.25):
        cw, rh = w / cols, h / rows
        for r in range(rows):
            for c in range(cols):
                wx, wy = x0 + c * cw + cw * (1 - fw) / 2, y0 + r * rh + rh * (1 - fh) / 2
                k = 1 + (self.rng.random() - 0.5) * jitter
                lit = self.rng.random() < 0.07
                cc = (np.array((70, 150, 210)) if lit else np.array(col)) * k
                pts = [self.P(wx, wy, z), self.P(wx + cw * fw, wy, z), self.P(wx + cw * fw, wy + rh * fh, z),
                       self.P(wx, wy + rh * fh, z)]
                self.poly(pts, cc, tex=False)
                if deep:                                            # откос сверху — тень
                    sp = [self.P(wx, wy + rh * fh * 0.82, z), self.P(wx + cw * fw, wy + rh * fh * 0.82, z),
                          self.P(wx + cw * fw, wy + rh * fh, z), self.P(wx, wy + rh * fh, z)]
                    self.poly(sp, cc * 0.45, tex=False)


def sky(rng, top, bot, clouds=0.35, warm=None):
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    img = np.array(top, np.float32) * (1 - t) + np.array(bot, np.float32) * t
    img = np.repeat(img, W, axis=1)
    cl = noise(rng, H, W, ((40, 0.5), (160, 0.35), (480, 0.15)))
    cl = np.clip((cl - 0.45) * 2.2, 0, 1) * clouds
    cl *= np.clip(1.2 - t[..., 0] * 1.1, 0, 1)
    ccol = np.array(warm or (232, 232, 230), np.float32)
    return img * (1 - cl[..., None]) + ccol * cl[..., None]


def ground_fill(img, gy, col, rng, horizon_far=None):
    n = noise(rng, H - gy, W, ((4, 0.4), (30, 0.3), (200, 0.3)))
    g = np.array(col, np.float32)[None, None, :] * (0.75 + 0.4 * n[..., None])
    img[gy:] = g


def tree(sc, x, gy, h, rng, col=(38, 58, 44)):
    """Берёза/тополь: ствол + облако кроны из кругов."""
    cv2.line(sc.img, (int(x), int(gy)), (int(x), int(gy - h * 0.55)), (190, 200, 205), max(3, int(h * 0.025)),
             cv2.LINE_AA)
    for _ in range(26):
        r = h * (0.08 + 0.1 * rng.random())
        cx = x + (rng.random() - 0.5) * h * 0.45
        cy = gy - h * (0.5 + 0.45 * rng.random())
        k = 0.7 + 0.5 * rng.random()
        cv2.circle(sc.img, (int(cx), int(cy)), int(r), tuple(float(v * k) for v in col), -1, cv2.LINE_AA)


def person(sc, x, gy, h, col):
    hd = h * 0.13
    cv2.circle(sc.img, (int(x), int(gy - h + hd)), int(hd), (40, 45, 55), -1, cv2.LINE_AA)
    body = np.array([[x - h * 0.13, gy - h * 0.82], [x + h * 0.13, gy - h * 0.82], [x + h * 0.16, gy - h * 0.38],
                     [x - h * 0.16, gy - h * 0.38]], np.int32)
    cv2.fillPoly(sc.img, [body], col, cv2.LINE_AA)
    for dx in (-0.06, 0.06):
        cv2.line(sc.img, (int(x + h * dx), int(gy - h * 0.4)), (int(x + h * dx * 1.6), int(gy)), (30, 30, 36),
                 max(2, int(h * 0.07)), cv2.LINE_AA)
    cv2.ellipse(sc.img, (int(x + 25), int(gy)), (int(h * 0.3), int(h * 0.04)), 0, 0, 360, (0, 0, 0), -1)


def lamp(sc, x, gy, h):
    cv2.line(sc.img, (int(x), int(gy)), (int(x), int(gy - h)), (60, 62, 66), 7, cv2.LINE_AA)
    cv2.line(sc.img, (int(x), int(gy - h)), (int(x + h * 0.18), int(gy - h * 1.04)), (60, 62, 66), 6, cv2.LINE_AA)
    cv2.ellipse(sc.img, (int(x + h * 0.2), int(gy - h * 1.03)), (22, 9), 0, 0, 360, (90, 92, 96), -1, cv2.LINE_AA)


def finish(img, rng, tint=(1.0, 1.0, 1.0), grain=7.0, vign=0.35):
    img = img * np.array(tint, np.float32)[None, None, :]
    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    img *= (1 - vign * np.clip(r - 0.5, 0, 1) ** 1.5)[..., None]
    img += rng.normal(0, grain, img.shape[:2]).astype(np.float32)[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


# --- три сюжета (цвета BGR) ---------------------------------------------------------------------------

def dom_korabl(rng):
    """Длинный панельный «дом-корабль» с лоджиями, пасмурно, тополя, двое у фонаря."""
    gy = int(H * 0.80)
    sc = Scene(rng, gy, sun=(-14, 10))
    sc.img = sky(rng, (205, 196, 186), (222, 220, 216), clouds=0.55)
    ground_fill(sc.img, gy, (96, 104, 104), rng)
    sc.img[gy - 4:gy + 4] *= 0.8
    for x0, w, h in ((-120, 900, 520), (3200, 900, 460)):                     # дальние дома в дымке
        sc.box(x0, 0, 900, w, h, 160, (186, 186, 184), light=(1.0, 0.92, 1.05),
               windows=lambda x, y, z, w_, h_: sc.win_grid(x, y + 20, z, w_, h_ - 40, 14, 9, col=(150, 150, 152),
                                                          deep=False))
    def facade(x, y, z, w, h):
        sc.win_grid(x + 30, y + 40, z, w - 60, h - 70, 30, 12, fw=0.62, fh=0.5)
        for r in range(12):                                                    # горизонтальные пояса лоджий
            yy = y + 40 + r * (h - 70) / 12
            sc.poly([sc.P(x, yy, z - 14), sc.P(x + w, yy, z - 14), sc.P(x + w, yy + 18, z - 14),
                     sc.P(x, yy + 18, z - 14)], (196, 198, 200))
    sc.box(380, 0, 140, 2900, 760, 260, (176, 180, 182), windows=facade)
    for x0 in (540, 1600, 2700):                                               # лестничные «рёбра»
        sc.box(x0, 0, 110, 70, 800, 40, (164, 168, 170),
               windows=lambda x, y, z, w_, h_: sc.win_grid(x + 10, y + 60, z, w_ - 20, h_ - 120, 1, 12, fw=0.7,
                                                           fh=0.3))
    rng2 = np.random.default_rng(rng.integers(1 << 30))
    for x in (160, 330, 3420, 3610, 3760):
        tree(sc, x, gy + 30, 560 + rng2.random() * 160, rng2)
    lamp(sc, 2160, gy + 60, 330)
    person(sc, 2090, gy + 70, 120, (60, 40, 120))
    person(sc, 2240, gy + 74, 112, (110, 90, 40))
    return finish(sc.img, rng, tint=(1.02, 1.0, 0.97))


def institut(rng):
    """Институт из консолей: короба вразбег на опорах, низкое солнце, длинные тени."""
    gy = int(H * 0.86)
    sc = Scene(rng, gy, sun=(46, 34), kx=0.42, ky=0.24)
    sc.img = sky(rng, (190, 140, 96), (150, 200, 236), clouds=0.25, warm=(170, 210, 245))
    ground_fill(sc.img, gy, (74, 98, 110), rng)
    warm = (150, 178, 196)
    sc.box(1500, 0, 160, 260, 380, 260, warm)                                 # ствол-опора
    sc.box(2550, 0, 120, 200, 300, 220, warm)
    def ribbon(x, y, z, w, h):
        sc.win_grid(x + 20, y + 30, z, w - 40, h - 60, int(w // 70), 1, fw=0.92, fh=0.6, deep=True, jitter=0.1)
    sc.box(900, 360, 120, 1300, 230, 300, warm, windows=ribbon)               # нижняя консоль
    sc.box(1900, 300, 80, 1400, 210, 280, warm, windows=ribbon)
    sc.box(1250, 590, 60, 1150, 240, 320, warm, windows=ribbon)               # верхняя, поперёк
    sc.box(1700, 830, 140, 520, 170, 180, warm,
           windows=lambda x, y, z, w_, h_: sc.win_grid(x + 30, y + 30, z, w_ - 60, h_ - 60, 6, 1, fw=0.5, fh=0.55))
    sc.box(2440, 830, 140, 60, 180, 60, (130, 150, 160))                      # мачта
    lamp(sc, 700, gy + 40, 300)
    rng2 = np.random.default_rng(rng.integers(1 << 30))
    for x in (200, 420, 3500, 3700):
        tree(sc, x, gy + 40, 420 + rng2.random() * 140, rng2, col=(40, 80, 70))
    person(sc, 1180, gy + 50, 100, (50, 50, 160))
    return finish(sc.img, rng, tint=(0.94, 1.0, 1.07), vign=0.4)


def bashnya(rng):
    """Башня из поперечных брусьев (крест-накрест на стволах), туман, вечер."""
    gy = int(H * 0.88)
    sc = Scene(rng, gy, sun=(-30, 20), kx=0.6, ky=0.3)
    sc.img = sky(rng, (120, 110, 104), (176, 178, 184), clouds=0.4, warm=(196, 196, 200))
    ground_fill(sc.img, gy, (70, 76, 80), rng)
    base = (150, 156, 160)
    for xs in (1500, 2240):                                                    # два ствола
        sc.box(xs, 0, 200, 170, 1000, 170, base,
               windows=lambda x, y, z, w_, h_: sc.win_grid(x + 30, y + 80, z, w_ - 60, h_ - 160, 1, 16, fw=0.4,
                                                           fh=0.35))
    def strip(x, y, z, w, h):
        sc.win_grid(x + 20, y + 40, z, w - 40, h - 80, int(w // 80), 2, fw=0.8, fh=0.5, jitter=0.12)
    sc.box(1100, 160, 120, 1500, 190, 210, base, windows=strip)                # ярусы вразбег
    sc.box(1700, 380, 60, 1300, 180, 260, base, windows=strip)
    sc.box(1000, 600, 40, 1250, 180, 280, base, windows=strip)
    sc.box(1600, 820, 90, 1100, 170, 200, base, windows=strip)
    # туман у земли
    t = np.clip((np.arange(H, dtype=np.float32) - H * 0.55) / (H * 0.35), 0, 1)[:, None]
    fog = noise(rng, H, W, ((80, 0.6), (300, 0.4))) * 0.5 + 0.5
    k = (t * 0.45 * fog)[..., None]
    sc.img = sc.img * (1 - k) + np.array((190, 192, 196), np.float32) * k
    rng2 = np.random.default_rng(rng.integers(1 << 30))
    for x in (260, 3550):
        tree(sc, x, gy + 30, 520 + rng2.random() * 120, rng2, col=(48, 62, 56))
    lamp(sc, 3050, gy + 60, 340)
    person(sc, 900, gy + 60, 108, (40, 40, 44))
    return finish(sc.img, rng, tint=(1.04, 1.0, 0.96), grain=8, vign=0.45)


SCENES = (("01 - дом-корабль", dom_korabl), ("02 - институт", institut), ("03 - башня", bashnya))


def main():
    out = Path(sys.argv[1])
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1974
    out.mkdir(parents=True, exist_ok=True)
    for i, (name, fn) in enumerate(SCENES):
        img = fn(np.random.default_rng(seed + i))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        (out / f"{name}.jpg").write_bytes(buf.tobytes())                       # кириллица в пути — через байты
        print("готово:", out / f"{name}.jpg")


if __name__ == "__main__":
    main()
