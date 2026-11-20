r"""Заставка SMENA в стиле старой VHS (≈18.5 с, 1920×1080).

  0.0–1.6   темнота, еле виден глаз
  1.6–3.0   мигая включается лампа: на столе в чёрной объёмной вате — закрытая бирюзовая коробка
  3.0–6.8   камера подъезжает, крышка чуть приоткрывается — изнутри пробивается зелёный свет
  7.0–11.2  сцена приглушается: логотип «Восход», затем VOSKHOD AND UNKNOWN TONE PRESENTS (шрифт афиши, с тенью)
 11.2–14.4  крышка откидывается, камера ныряет в интерфейс
 13.0–18.5  интерфейс вживую: банки открываются и закрываются, провода LFO перетыкаются (кадры записаны из программы)

Сцена — tools/render/intro_box.py (коробка, перспектива); здесь — вата, титры, монтаж и VHS-плёнка.
Запуск: .venv-prep\Scripts\python.exe tools\render\intro_vhs.py <папка кадров интерфейса> <выход.mp4> [preview]
"""
import glob
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intro_box as B                                               # noqa: E402

ROOT = B.ROOT
W, H, FPS = B.W, B.H, B.FPS
VERT = False


def configure(vertical):
    """Вертикальный кадр 1080×1920 (Reels) или горизонтальный 1920×1080."""
    global W, H, VERT
    VERT = vertical
    W, H = (1080, 1920) if vertical else (1920, 1080)
    B.W, B.H = W, H


def ui_view(img, tt):
    """Кадр интерфейса (1920×1080) в кадр видео: горизонталь — как есть; вертикаль — крупно, с панорамой
    к правой части (LFO и провода)."""
    if not VERT:
        return cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32)
    sc = H * 0.66 / img.shape[0]
    big = cv2.resize(img, (int(img.shape[1] * sc), int(img.shape[0] * sc)), interpolation=cv2.INTER_AREA)
    u = B.smooth(max(0.0, tt - UI_START + 0.3) / 2.2)
    ox = int((0.18 + 0.82 * u) * (big.shape[1] - W))
    bg = cv2.GaussianBlur(cv2.resize(img, (int(img.shape[1] * H / img.shape[0]), H)), (0, 0), 30)
    bx = (bg.shape[1] - W) // 2
    frame = bg[:, bx:bx + W].astype(np.float32) * 0.35
    y0 = (H - big.shape[0]) // 2
    frame[y0:y0 + big.shape[0]] = big[:, ox:ox + W]
    return frame
FONT = ROOT / "assets" / "fonts" / "PoiretOne-Regular.ttf"
VOSKHOD = ROOT / "assets" / "poster" / "w.png"
rng = np.random.default_rng(11)
T0 = 1.6                     # до лампы — темнота с глазом
UI_START = 13.0              # с этого момента — живой интерфейс
DUR = UI_START + 5.5


# ----------------------------------------------------------------------------------- вата
def blur_noise(h, w, scale):
    g = rng.standard_normal((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)


def cotton_texture():
    """Чёрная вата: клубы разного размера, волокна, свет лампы пятном; стола не видно."""
    w, h = 2400, 1600
    clouds = blur_noise(h, w, 90) * 0.5 + blur_noise(h, w, 30) * 0.35 + blur_noise(h, w, 9) * 0.2
    fibers = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 0.8)
    fibers = cv2.filter2D(fibers, -1, cv2.getGaussianKernel(9, 3) @ np.ones((1, 1)) / 1.0)
    v = 18 + 14 * np.clip(clouds, -1.5, 2) + 6 * fibers
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = np.exp(-(((xx - w / 2) / (w * 0.30)) ** 2 + ((yy - h * 0.62) / (h * 0.40)) ** 2))
    v *= 0.25 + 1.25 * light
    img = np.dstack([v * 0.95, v * 0.97, v]).clip(0, 255).astype(np.uint8)          # чуть холодный чёрный
    sh = np.zeros((h, w), np.float32)                                              # контактная тень коробки
    sx, sz = w / 300.0, h / 200.0
    cx, cy = w / 2, h * 0.62
    cv2.rectangle(sh, (int(cx - B.BW / 2 * sx), int(cy - B.BD / 2 * sz)),
                  (int(cx + B.BW / 2 * sx + 20), int(cy + B.BD / 2 * sz + 26)), 1.0, -1)
    sh = cv2.GaussianBlur(sh, (0, 0), 26)
    img = (img * (1 - 0.85 * sh[..., None])).astype(np.uint8)
    return np.dstack([img, np.full((h, w), 255, np.uint8)])


def fluff_sprite(seed):
    """Клок ваты (BGRA): мягкий пушистый край, волокна, чуть светлее сверху."""
    r = np.random.default_rng(seed)
    w, h = 260, 150
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.exp(-(((xx - w / 2) / (w * 0.40)) ** 2 + ((yy - h * 0.62) / (h * 0.42)) ** 2))
    n = cv2.resize(r.standard_normal((h // 18, w // 18)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    a = np.clip(base * 1.5 + 0.25 * n - 0.45, 0, 1) ** 0.8
    a = cv2.GaussianBlur(a, (0, 0), 4.0)                                       # мягкий пушистый край
    fib = cv2.GaussianBlur(r.standard_normal((h, w)).astype(np.float32), (0, 0), 1.2)
    top = np.clip(1 - yy / (h * 0.75), 0, 1) * base                              # верх клока ловит свет
    v = 20 + 5 * fib + 34 * top
    rgb = np.dstack([v * 0.95, v * 0.97, v]).clip(0, 255)
    return np.dstack([rgb, a * 255]).astype(np.uint8)


def paste_scaled(frame, spr, cx, cy, w, shade):
    if w < 4:
        return
    h = int(w * spr.shape[0] / spr.shape[1])
    s = cv2.resize(spr, (int(w), max(1, h)), interpolation=cv2.INTER_AREA)
    x0, y0 = int(cx - w / 2), int(cy - h * 0.62)
    x1, y1 = x0 + s.shape[1], y0 + s.shape[0]
    sx0, sy0 = max(0, -x0), max(0, -y0)
    x0c, y0c, x1c, y1c = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1c <= x0c or y1c <= y0c:
        return
    sub = s[sy0:sy0 + (y1c - y0c), sx0:sx0 + (x1c - x0c)].astype(np.float32)
    a = sub[..., 3:4] / 255.0
    roi = frame[y0c:y1c, x0c:x1c]
    frame[y0c:y1c, x0c:x1c] = roi * (1 - a) + sub[..., :3] * shade * a


# ----------------------------------------------------------------------------------- титры
def spaced(draw, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + spacing


def spaced_w(text, font, spacing):
    return sum(font.getlength(c) for c in text) + spacing * (len(text) - 1)


def title_layer(lines, px, spacing):
    """Текст афиши: PoiretOne, кремовый, с мягкой тенью — RGBA на весь кадр."""
    f = ImageFont.truetype(str(FONT), px)
    lh = int(px * 1.35)
    ink = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    top = H * (0.50 if VERT else 0.585)
    for i, t in enumerate(lines):
        x = (W - spaced_w(t, f, spacing)) / 2
        spaced(d, (x, top + i * lh), t, f, (236, 232, 224, 255), spacing)
    a = np.array(ink)[..., 3].astype(np.float32)
    sh = cv2.GaussianBlur(np.roll(np.roll(a, 5, 0), 4, 1), (0, 0), 6) * 0.85
    out = np.zeros((H, W, 4), np.float32)
    out[..., 3] = sh
    al = a[..., None] / 255.0
    out[..., :3] = np.array([224, 232, 236], np.float32) * al                         # BGR кремовый
    out[..., 3] = np.maximum(out[..., 3], a)
    return out


def logo_layer():
    lg = Image.open(VOSKHOD).convert("RGBA")
    a = np.array(lg)[..., 3]
    lw = int(W * (0.16 if VERT else 0.085))
    lg = lg.resize((lw, int(lw * lg.height / lg.width)), Image.LANCZOS)
    arr = np.array(lg).astype(np.float32)
    out = np.zeros((H, W, 4), np.float32)
    x0, y0 = (W - arr.shape[1]) // 2, int(H * (0.42 if VERT else 0.40) - arr.shape[0] / 2)
    sh = cv2.GaussianBlur(arr[..., 3], (0, 0), 6)
    out[y0 + 5:y0 + 5 + arr.shape[0], x0 + 4:x0 + 4 + arr.shape[1], 3] = sh * 0.85
    reg = out[y0:y0 + arr.shape[0], x0:x0 + arr.shape[1]]
    al = arr[..., 3:4] / 255.0
    reg[..., :3] = reg[..., :3] * (1 - al) + np.array([224, 232, 236], np.float32) * al
    reg[..., 3] = np.maximum(reg[..., 3], arr[..., 3])
    del a
    return out


def over(frame, layer, k):
    if k <= 0:
        return frame
    a = layer[..., 3:4] / 255.0 * k
    shadow = (layer[..., 3:4] > 0)
    return frame * (1 - a) + layer[..., :3] * a


# ----------------------------------------------------------------------------------- VHS
class VHS:
    def __init__(self):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.scan = (1 - 0.10 * ((yy.astype(int) // 2) % 2))[..., None]
        self.vign = (1 - 0.5 * (((xx - W / 2) / (W * 0.7)) ** 2 + ((yy - H / 2) / (H * 0.7)) ** 2)).clip(0.35, 1)[..., None]
        self.osd = ImageFont.truetype(str(ROOT / "smena/ui/theme/smena_pipboy/fonts/VT323-Regular.ttf"), 64)

    def __call__(self, img, tt):
        f = img.astype(np.float32)
        small = cv2.resize(f, (405, 720) if VERT else (720, 405), interpolation=cv2.INTER_AREA)   # мягкость
        f = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
        ycc = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2YCrCb).astype(np.float32)
        ycc[..., 1] = np.roll(cv2.blur(ycc[..., 1], (21, 1)), 6, axis=1)               # цвет «плывёт» вправо
        ycc[..., 2] = np.roll(cv2.blur(ycc[..., 2], (21, 1)), 3, axis=1)
        ycc[..., 1:] = 128 + (ycc[..., 1:] - 128) * 0.82                                 # выцветание
        f = cv2.cvtColor(np.clip(ycc, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR).astype(np.float32)
        # дрожание строк + полоса трекинга внизу
        r = np.random.default_rng(int(tt * 1000))
        shift = (np.sin(np.arange(H) / 37.0 + tt * 9) * 1.4 + r.standard_normal(H) * 0.6).astype(np.int32)
        band_y = int(H * (0.92 + 0.03 * math.sin(tt * 0.7)))
        shift[band_y:band_y + 26] += r.integers(-14, 14, 26)
        idx = (np.arange(W)[None, :] - shift[:, None]) % W
        f = np.take_along_axis(f, np.repeat(idx[..., None], 3, axis=2), axis=1)
        f[band_y:band_y + 26] = f[band_y:band_y + 26] * 0.6 + r.random((26, W, 1)) * 90
        if r.random() < 0.06:                                                           # редкий сбой-полоса
            y = r.integers(0, H - 8)
            f[y:y + 4] = f[y:y + 4] * 0.4 + 140
        f += r.standard_normal((H, W, 1)).astype(np.float32) * 7                        # снег
        f = 10 + f * 0.93                                                               # приподнятый чёрный
        f *= self.scan * self.vign
        f *= np.array([0.94, 1.0, 1.05], np.float32)                                     # тёплый тон
        out = np.clip(f, 0, 255).astype(np.uint8)
        if tt < 3.0 and int(tt * 2) % 2 == 0:                                            # OSD видака
            pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
            d = ImageDraw.Draw(pil)
            d.text((84, 60), "PLAY ►", font=self.osd, fill=(235, 235, 235))
            out = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        return out


# ----------------------------------------------------------------------------------- сцена
def scene(cap_dir, times):
    """Кадры заставки (до VHS, float BGR) в моменты times."""
    caps = sorted(glob.glob(str(Path(cap_dir) / "f*.png")))
    ui_raw = B.imread(caps[0])[:, :, :3]
    ui_tex = np.dstack([cv2.resize(ui_raw, (1920, 1080), interpolation=cv2.INTER_AREA),
                        np.full((1080, 1920), 255, np.uint8)])
    ui0 = ui_view(ui_raw, UI_START)

    lid, lid_under = B.lid_texture(), B.plain(1320, 720, (95, 100, 96), 8)
    front, sidet = B.side_texture(1320, 240, 0.78), B.side_texture(720, 240, 0.62)
    inner_s = B.plain(720, 240, (28, 30, 28), 5)
    cotton = cotton_texture()
    fluff = [fluff_sprite(s) for s in range(8)]
    logo = logo_layer()
    lines = ["VOSKHOD AND", "UNKNOWN TONE", "PRESENTS"] if VERT else ["VOSKHOD AND UNKNOWN TONE", "PRESENTS"]
    px = 92 if VERT else 74
    while px > 30 and max(spaced_w(t, ImageFont.truetype(str(FONT), px), 12) for t in lines) > W * 0.84:
        px -= 2
    text = title_layer(lines, px, 12)
    eye = B.rgba(B.imread(B.THEME / "eye.png"))
    ew = int(W * (0.55 if VERT else 0.30))
    eye = cv2.GaussianBlur(cv2.resize(eye, (ew, int(ew * eye.shape[0] / eye.shape[1])), interpolation=cv2.INTER_AREA),
                           (0, 0), 1.2)

    X0, X1, Z0, Z1, Y1 = -B.BW / 2, B.BW / 2, -B.BD / 2, B.BD / 2, B.BH
    floor_y = B.BH - 1.3
    keys = [(0.0, (0, 62, 150), (0, 4, 0)), (4.0, (0, 50, 84), (0, 3, -1)), (8.6, (0, 47, 66), (0, 3, -1)),
            (10.3, (0, 64, 30), (0, 1, -1)), (11.9, (0, floor_y + 43.0, 3.0), (0, floor_y, -0.2))]
    if VERT:                                                        # вертикаль: коробка ближе, сверху
        keys = [(0.0, (0, 70, 112), (0, 2, 0)), (4.0, (0, 60, 82), (0, 2, -1)), (8.6, (0, 58, 72), (0, 2, -1)),
                (10.3, (0, 74, 30), (0, 1, -1)), (11.9, (0, floor_y + 44.0, 1.5), (5.0, floor_y, -0.6))]

    def cam_at(t):
        for (t0, p0, c0), (t1, p1, c1) in zip(keys, keys[1:]):
            if t <= t1:
                u = B.smooth((t - t0) / (t1 - t0))
                return [a + (b - a) * u for a, b in zip(p0, p1)], [a + (b - a) * u for a, b in zip(c0, c1)]
        return list(keys[-1][1]), list(keys[-1][2])

    def light_at(t):
        flick = [(0.0, 0.05, 0.9), (0.05, 0.25, 0.05), (0.25, 0.32, 0.7), (0.32, 0.55, 0.1), (0.55, 0.61, 1.0),
                 (0.61, 0.70, 0.35)]
        for a, b, v in flick:
            if a <= t < b:
                return v
        return min(1.0, 0.85 + (t - 0.7) * 0.5)

    fluff_pts = []                                                  # клочья ваты по нижним рёбрам коробки
    for x in np.arange(X0 - 4, X1 + 4.1, 4.0):
        fluff_pts.append((x, -0.3, Z1 + 2.2 + rng.uniform(-0.5, 1.2), rng.integers(8), rng.uniform(5, 7.5)))
    for z in np.arange(Z0, Z1 + 0.1, 4.0):
        for xx in (X0 - 2.6, X1 + 2.6):
            fluff_pts.append((xx, -0.6, z, rng.integers(8), rng.uniform(3.8, 5)))
    far_pts = []
    for k in range(40):                                             # россыпь клубов по всей вате (до коробки)
        x, z = rng.uniform(-110, 110), rng.uniform(-60, 60)
        if abs(x) < B.BW / 2 + 6 and abs(z) < B.BD / 2 + 6:
            continue
        far_pts.append((x, -0.5, z, rng.integers(8), rng.uniform(12, 26)))
    warm = np.array([0.86, 0.96, 1.08], np.float32)
    n = int(DUR * FPS)
    first = True
    for tt in times:
        fi = int(round(tt * FPS))
        t = max(0.0, tt - T0)
        if tt >= UI_START + 0.25:                                   # живой интерфейс
            k = min(len(caps) - 1, int((tt - UI_START) * FPS))
            frame = ui_view(B.imread(caps[k])[:, :, :3], tt)
        else:
            p, c = cam_at(t)
            jit = 0.2 * (1 - B.smooth((t - 10.0) / 1.2))
            p = np.array(p) + jit * np.array([math.sin(tt * 1.3), math.sin(tt * 1.7 + 1), math.sin(tt * 0.9 + 2)])
            cam = B.Cam(p, c)
            L = light_at(t) if tt >= T0 else 0.0
            crack = 0.12 * B.smooth((t - 4.2) / 0.9)
            u = (t - 8.6) / 1.8
            open_u = max(crack, 0.0 if u <= 0 else B.smooth(u) + 0.04 * math.sin(min(u, 1.4) / 1.4 * 2 * math.pi) * (u > 0.7))
            ang = math.radians(108 * open_u)
            frame = np.zeros((H, W, 3), np.float32)
            B.draw_face(frame, cotton, [(-150, 0, -132), (150, 0, -132), (150, 0, 68), (-150, 0, 68)], cam)
            for x, y, z, si, size in sorted(far_pts, key=lambda q: -cam.depth([q[:3]])):
                pr, zd = cam.proj([(x, y, z)])
                if zd[0] >= 2:
                    paste_scaled(frame, fluff[si], pr[0, 0], pr[0, 1], cam.fpx * size / zd[0], 1.25)
            frame *= L * warm
            glow = 0.15 + 0.85 * B.smooth((open_u - 0.15) / 0.6)
            if open_u > 0:
                B.draw_face(frame, ui_tex, [(X0 + .3, floor_y, Z0 + .3), (X1 - .3, floor_y, Z0 + .3),
                                            (X1 - .3, floor_y, Z1 - .3), (X0 + .3, floor_y, Z1 - .3)], cam, glow)
                B.draw_face(frame, inner_s, [(X0, Y1, Z0), (X0, Y1, Z1), (X0, floor_y, Z1), (X0, floor_y, Z0)], cam, .45 * L)
                B.draw_face(frame, inner_s, [(X1, Y1, Z1), (X1, Y1, Z0), (X1, floor_y, Z0), (X1, floor_y, Z1)], cam, .45 * L)
            hz = Z0

            def lid_pt(x, zz):
                dz = zz - hz
                return (x, Y1 + dz * math.sin(ang), hz + dz * math.cos(ang))
            quad = [lid_pt(X0 - .4, Z0), lid_pt(X1 + .4, Z0), lid_pt(X1 + .4, Z1 + .4), lid_pt(X0 - .4, Z1 + .4)]
            nrm = np.array([0, math.cos(ang), -math.sin(ang)])
            if np.dot(cam.p - np.array(quad[0]), nrm) > 0:
                B.draw_face(frame, lid, quad, cam, L * (1.0 - 0.25 * open_u) + 0.15 * open_u)
                edge = [quad[3], quad[2], (quad[2][0], quad[2][1] - .6, quad[2][2]), (quad[3][0], quad[3][1] - .6, quad[3][2])]
                B.draw_face(frame, sidet, edge, cam, 0.5 * L)
            else:
                B.draw_face(frame, lid_under, [quad[3], quad[2], quad[1], quad[0]], cam, .35 * L + .55 * open_u,
                            add=np.array([10, 30, 20]) * open_u)
            B.draw_face(frame, front, [(X0, Y1, Z1), (X1, Y1, Z1), (X1, 0, Z1), (X0, 0, Z1)], cam, 0.85 * L)
            # вата поверх нижних рёбер — от дальних к ближним
            pts = sorted(fluff_pts, key=lambda q: -cam.depth([q[:3]]))
            for x, y, z, si, size in pts:
                pr, zd = cam.proj([(x, y, z)])
                if zd[0] < 2:
                    continue
                paste_scaled(frame, fluff[si], pr[0, 0], pr[0, 1], cam.fpx * size / zd[0], L * 1.25)
            # зелёный свет из щели / из коробки
            if open_u > 0:
                cpt, _ = cam.proj([(0, B.BH, 0)])
                if first or not hasattr(scene, "_g") or scene._g[0].shape != (H, W):
                    scene._g = np.mgrid[0:H, 0:W].astype(np.float32)
                yy, xx = scene._g
                g = np.exp(-(((xx - cpt[0, 0]) / (W * 0.30)) ** 2 + ((yy - cpt[0, 1]) / (H * 0.22)) ** 2))
                frame += (g * (80 * min(1.0, open_u / 0.12)) * (1 - B.smooth((t - 10.6) / 1.0)))[..., None] * \
                    np.array([0.5, 1.0, 0.7])
            # титры: сцена приглушается, логотип, затем надпись
            dim = B.smooth((tt - 6.8) / 0.6) * (1 - B.smooth((tt - 10.8) / 0.6))
            frame *= 1 - 0.7 * dim
            frame = over(frame, logo, B.smooth((tt - 7.1) / 0.7) * (1 - B.smooth((tt - 10.6) / 0.6)))
            frame = over(frame, text, B.smooth((tt - 8.0) / 0.8) * (1 - B.smooth((tt - 10.6) / 0.6)))
            # глаз в темноте
            e = 0.0 if tt > T0 + 1.0 else (0.09 * B.smooth(tt / 1.0) * (0.75 + 0.25 * math.sin(tt * 3.0))
                                             * (1 - B.smooth((tt - T0) / 1.0)))
            if e > 0:
                eh, ew2 = eye.shape[:2]
                x0, y0 = (W - ew2) // 2, (H - eh) // 2
                a = eye[..., 3:4].astype(np.float32) / 255.0 * e
                roi = frame[y0:y0 + eh, x0:x0 + ew2]
                frame[y0:y0 + eh, x0:x0 + ew2] = roi * (1 - a) + eye[..., :3].astype(np.float32) * a
            # переход в живой интерфейс
            k = B.smooth((tt - (UI_START - 0.45)) / 0.7)
            if k > 0:
                frame = frame * (1 - k) + ui0.astype(np.float32) * k
        first = False
        yield frame


def main():
    cap_dir, out = sys.argv[1], sys.argv[2]
    configure("--vertical" in sys.argv)
    preview = "preview" in sys.argv
    vhs = VHS()
    times = [0.8, 3.5, 6.5, 8.6, 11.8, 13.8, 16.5] if preview else [i / FPS for i in range(int(DUR * FPS))]
    proc = None if preview else subprocess.Popen(
        [B.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for tt, frame in zip(times, scene(cap_dir, times)):
        img = vhs(frame, tt)
        if preview:
            cv2.imencode(".png", img)[1].tofile(f"{out}_{tt:.1f}.png")
        else:
            proc.stdin.write(img.tobytes())
    if proc:
        proc.stdin.close()
        proc.wait()
    print("готово:", out)


if __name__ == "__main__":
    main()
