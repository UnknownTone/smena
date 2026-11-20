r"""Заставка SMENA (≈9 с, 1920×1080): в тёмной комнате мигая включается лампа, на столе — закрытая бирюзовая
жестяная коробка SMENA; камера наезжает, крышка откидывается, внутри светится интерфейс; камера ныряет в него —
и на весь кадр остаётся интерфейс программы.

Простая 3D-сцена: коробка, стол и стена — плоские грани с текстурами, перспектива (cv2.warpPerspective),
порядок рисования — от дальнего к ближнему. Окружение .venv-prep (numpy, OpenCV, PIL).
Запуск: .venv-prep\Scripts\python.exe tools\render\intro_box.py <снимок интерфейса.png> <выход.mp4>
"""
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "smena" / "ui" / "theme" / "smena_pipboy" / "textures"
W, H, FPS, DUR = 1920, 1080, 30, 10.5
T0 = 1.5                      # первые секунды — в темноте еле виден глаз
rng = np.random.default_rng(7)

# коробка, см: ширина X, глубина Z, высота Y (пропорции крышки ≈ интерфейсу)
BW, BD, BH = 44.0, 24.0, 8.0


def imread(p):
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_UNCHANGED)


def rgba(a):
    if a.shape[2] == 3:
        a = np.dstack([a, np.full(a.shape[:2], 255, np.uint8)])
    return a


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


# ----------------------------------------------------------------------------------- текстуры
def tile(tex, w, h):
    reps = (h // tex.shape[0] + 1, w // tex.shape[1] + 1, 1)
    return np.tile(tex, reps)[:h, :w]


def tin_base(w, h, dark=1.0):
    t = imread(THEME / "tin.png")[:, :, :3]
    t = tile(t, w, h).astype(np.float32) * dark
    return t


def rust_rim(img, width, strength=1.0):
    """Ржавчина и потёртость по краю жестяной грани."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
    n = cv2.resize(rng.standard_normal((h // 16 + 2, w // 16 + 2)).astype(np.float32), (w, h),
                   interpolation=cv2.INTER_CUBIC)
    k = np.clip((1 - d / width) * 1.3 + n * 0.35 - 0.2, 0, 1)[..., None] * strength
    rust = np.array([40, 70, 140], np.float32)                      # BGR рыжий
    out = img * (1 - k) + rust * (0.6 + 0.4 * np.clip(n[..., None], -1, 1)) * k
    edge = (d < 3)[..., None]
    return np.where(edge, out * 0.55, out)


def chrome_text(draw_size, text, font_path, px):
    """Хромированная рубленая надпись (RGBA, PIL)."""
    f = ImageFont.truetype(font_path, px)
    l, t, r, b = f.getbbox(text)
    tw, th = r - l + 20, b - t + 20
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).text((10 - l, 10 - t), text, font=f, fill=255)
    grad = np.zeros((th, tw, 3), np.float32)
    ys = np.linspace(0, 1, th)[:, None]
    g = np.interp(ys, [0, 0.3, 0.49, 0.51, 0.72, 1.0], [255, 210, 245, 45, 130, 235])
    grad[:] = g[..., None]
    a = np.array(mask, np.float32)
    shadow = cv2.GaussianBlur(a, (0, 0), 3)
    out = np.zeros((th + 8, tw + 8, 4), np.float32)
    out[6:th + 6, 6:tw + 6, 3] = shadow * 0.8                     # тень
    body = np.dstack([grad, a])
    sl = out[:th, :tw]
    al = body[..., 3:4] / 255.0
    sl[..., :3] = sl[..., :3] * (1 - al) + body[..., :3] * al
    sl[..., 3] = np.maximum(sl[..., 3], body[..., 3])
    return out.astype(np.uint8)


def paste(dst, src, x, y):
    h, w = src.shape[:2]
    a = src[..., 3:4].astype(np.float32) / 255.0
    roi = dst[y:y + h, x:x + w, :3].astype(np.float32)
    dst[y:y + h, x:x + w, :3] = roi * (1 - a) + src[..., :3].astype(np.float32) * a


def lid_texture():
    w, h = 1320, 720
    t = tin_base(w, h, 0.95)
    t = rust_rim(t, 46)
    t = cv2.rectangle(t, (40, 40), (w - 41, h - 41), (70, 110, 105), 3)          # штампованная рамка
    t = cv2.rectangle(t, (44, 44), (w - 45, h - 45), (190, 210, 205), 1)
    img = np.clip(t, 0, 255).astype(np.uint8)
    img = np.dstack([img, np.full((h, w), 255, np.uint8)])
    eye = rgba(imread(THEME / "eye.png"))
    eye = cv2.resize(eye, (330, int(330 * eye.shape[0] / eye.shape[1])), interpolation=cv2.INTER_AREA)
    paste(img, eye, 120, (h - eye.shape[0]) // 2 - 30)
    txt = chrome_text(None, "СМЕНА", "C:/Windows/Fonts/impact.ttf", 230)
    txt = cv2.cvtColor(txt, cv2.COLOR_RGBA2BGRA)
    paste(img, txt, 490, (h - txt.shape[0]) // 2 - 50)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
    d = ImageDraw.Draw(pil)
    f2 = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 44)
    d.text((500, h - 205), "ЛОМО · VJ", font=f2, fill=(242, 226, 28, 235))
    f3 = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", 30)
    d.text((500, h - 145), "powered by Unknown_Tone   0.1.2", font=f3, fill=(225, 225, 215, 200))
    for k in range(10):                                                           # «зебра» внизу
        x0 = 120 + k * 36
        d.polygon([(x0, h - 95), (x0 + 18, h - 95), (x0 + 36, h - 70), (x0 + 18, h - 70)], fill=(226, 194, 30, 220))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGBA2BGRA)


def side_texture(w, h, dark, label=None):
    t = rust_rim(tin_base(w, h, dark), 26)
    img = np.dstack([np.clip(t, 0, 255).astype(np.uint8), np.full((h, w), 255, np.uint8)])
    if label:
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
        d = ImageDraw.Draw(pil)
        f = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", int(h * 0.26))
        l, tt, r, b = f.getbbox(label)
        d.rectangle([w / 2 - (r - l) / 2 - 24, h * 0.33, w / 2 + (r - l) / 2 + 24, h * 0.72], fill=(14, 14, 10, 235),
                    outline=(226, 194, 30, 255), width=3)
        d.text((w / 2 - (r - l) / 2 - l, h * 0.36 - tt), label, font=f, fill=(242, 226, 28, 255))
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGBA2BGRA)
    return img


def plain(w, h, bgr, noise=6):
    a = np.ones((h, w, 3), np.float32) * np.array(bgr, np.float32)
    a += rng.standard_normal((h, w, 1)) * noise
    return np.dstack([np.clip(a, 0, 255).astype(np.uint8), np.full((h, w), 255, np.uint8)])


def table_texture():
    """Старый деревянный стол: волокна, свет лампы пятном в центре, мягкая тень коробки."""
    w, h = 2400, 1600
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    wob = cv2.resize(rng.standard_normal((8, 60)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    grain = (0.6 * np.sin(yy / 3.1 + 2.0 * wob + 0.8 * np.sin(xx / 400.0))
             + 0.4 * np.sin(yy / 11.0 + 3.0 * wob))                                 # волокна вдоль досок
    fine = cv2.resize(rng.standard_normal((h // 2, w // 40)).astype(np.float32), (w, h))
    base = np.array([28, 52, 84], np.float32)                                     # BGR тёмное дерево
    img = base * (1 + 0.14 * grain[..., None] + 0.08 * fine[..., None]) + rng.standard_normal((h, w, 1)) * 4
    for k in range(1, 8):                                                         # стыки досок (доски вдоль X)
        y = int(k * h / 8)
        img[y - 2:y + 2] *= 0.4
    # свет лампы: пятно вокруг коробки (центр текстуры — под коробкой)
    cx, cy = w / 2, h * 0.62
    light = np.exp(-(((xx - cx) / (w * 0.32)) ** 2 + ((yy - cy) / (h * 0.42)) ** 2))
    img *= (0.18 + 1.1 * light)[..., None]
    # тень коробки: размытый прямоугольник
    sh = np.zeros((h, w), np.float32)
    sx, sz = w / 300.0, h / 200.0                                                 # см → пиксели (стол 300×200 см)
    x0, x1 = cx - BW / 2 * sx, cx + BW / 2 * sx
    z0, z1 = cy - BD / 2 * sz, cy + BD / 2 * sz
    cv2.rectangle(sh, (int(x0 + 10), int(z0 + 14)), (int(x1 + 26), int(z1 + 30)), 1.0, -1)
    sh = cv2.GaussianBlur(sh, (0, 0), 22)
    img *= (1 - 0.8 * sh)[..., None]
    return np.dstack([np.clip(img, 0, 255).astype(np.uint8), np.full((h, w), 255, np.uint8)])


def wall_texture():
    w, h = 2400, 1200
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    n = cv2.resize(rng.standard_normal((60, 120)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    base = np.array([36, 40, 38], np.float32)
    img = base * (1 + 0.12 * n[..., None]) + rng.standard_normal((h, w, 1)) * 4
    light = np.exp(-(((xx - w / 2) / (w * 0.35)) ** 2 + ((yy - h * 0.9) / (h * 0.7)) ** 2))
    img *= (0.15 + 0.9 * light)[..., None]
    return np.dstack([np.clip(img, 0, 255).astype(np.uint8), np.full((h, w), 255, np.uint8)])


# ----------------------------------------------------------------------------------- камера
class Cam:
    def __init__(self, pos, target, fov=38.0):
        self.p = np.array(pos, np.float64)
        f = np.array(target, np.float64) - self.p
        self.f = f / np.linalg.norm(f)
        r = np.cross(self.f, [0, 1, 0])
        self.r = r / np.linalg.norm(r)
        self.u = np.cross(self.r, self.f)
        self.fpx = (W / 2) / math.tan(math.radians(fov) / 2)

    def proj(self, pts):
        d = np.asarray(pts, np.float64) - self.p
        x, y, z = d @ self.r, d @ self.u, d @ self.f
        z = np.maximum(z, 0.5)
        return np.stack([W / 2 + self.fpx * x / z, H / 2 - self.fpx * y / z], axis=1), z

    def depth(self, pts):
        return float(np.mean((np.asarray(pts) - self.p) @ self.f))


def draw_face(frame, tex, quad3, cam, shade=1.0, add=0.0):
    """Текстура tex (BGRA) на четырёхугольник quad3 (лево-верх, право-верх, право-низ, лево-низ текстуры)."""
    pts, z = cam.proj(quad3)
    if np.any(z <= 0.6):
        return
    h, w = tex.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, pts.astype(np.float32))
    x0, y0 = np.floor(pts.min(0)).astype(int)
    x1, y1 = np.ceil(pts.max(0)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 <= x0 or y1 <= y0:
        return
    T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64) @ M
    warped = cv2.warpPerspective(tex, T, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=(0, 0, 0, 0))
    a = warped[..., 3:4].astype(np.float32) / 255.0
    rgb = warped[..., :3].astype(np.float32) * shade + add
    roi = frame[y0:y1, x0:x1]
    frame[y0:y1, x0:x1] = roi * (1 - a) + rgb * a


# ----------------------------------------------------------------------------------- сцена
def main():
    ui_path, out = sys.argv[1], sys.argv[2]
    ui = rgba(imread(ui_path))[:, :, :4]
    ui = ui[:, :, :3]
    # интерфейс на дне коробки — кадр 16:9 «cover»
    uh, uw = ui.shape[:2]
    s = max(1920 / uw, 1080 / uh)
    ui_full = cv2.resize(ui, (int(uw * s + 0.5), int(uh * s + 0.5)), interpolation=cv2.INTER_AREA)
    oy = (ui_full.shape[0] - 1080) // 2
    ox = (ui_full.shape[1] - 1920) // 2
    ui_full = ui_full[oy:oy + 1080, ox:ox + 1920]
    ui_tex = np.dstack([ui_full, np.full((1080, 1920), 255, np.uint8)])

    lid = lid_texture()
    lid_under = plain(1320, 720, (95, 100, 96), 8)
    front = side_texture(1320, 240, 0.78)
    sidet = side_texture(720, 240, 0.62)
    inner = plain(1320, 240, (34, 36, 34), 5)
    inner_s = plain(720, 240, (28, 30, 28), 5)
    table = table_texture()
    wall = wall_texture()

    # углы (мировые, см), стол — y=0, коробка в центре стола
    X0, X1, Z0, Z1, Y1 = -BW / 2, BW / 2, -BD / 2, BD / 2, BH
    TX0, TX1, TZ0, TZ1 = -150, 150, -132, 68                      # стол 300×200 (центр текстуры — под коробкой)
    floor_y = BH - 1.3                                             # интерфейс почти у края — неглубокий лоток

    # ключи камеры: (время, позиция, цель)
    keys = [(0.0, (0, 62, 150), (0, 4, 0)),
            (4.6, (0, 48, 78), (0, 3, -1)),
            (6.4, (0, 64, 30), (0, 1, -1)),
            (8.3, (0, floor_y + 43.0, 3.0), (0, floor_y, -0.2))]

    def cam_at(t):
        for (t0, p0, c0), (t1, p1, c1) in zip(keys, keys[1:]):
            if t <= t1:
                u = smooth((t - t0) / (t1 - t0))
                p = [a + (b - a) * u for a, b in zip(p0, p1)]
                c = [a + (b - a) * u for a, b in zip(c0, c1)]
                return Cam(p, c)
        return Cam(keys[-1][1], keys[-1][2])

    def light_at(t):
        """Лампа: темно → мигает (люминесцентная) → горит."""
        if t < 0.7:
            return 0.0
        flick = [(0.70, 0.75, 0.9), (0.75, 0.95, 0.05), (0.95, 1.02, 0.7), (1.02, 1.25, 0.1), (1.25, 1.31, 1.0),
                 (1.31, 1.40, 0.35)]
        for a, b, v in flick:
            if a <= t < b:
                return v
        return min(1.0, 0.85 + (t - 1.4) * 0.5)

    n = int(DUR * FPS)
    preview = sys.argv[3:] == ["preview"]                         # только контрольные кадры в PNG
    proc = None if preview else subprocess.Popen([
        ffmpeg(), "-v", "error", "-y", "-f", "rawvideo",
        "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
        "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = (1 - 0.55 * (((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)).clip(0.25, 1)[..., None]
    frames = [int(x * FPS) for x in (0.8, 2.8, 4.5, 6.5, 7.6, 8.8)] if preview else range(n)
    eye_pm = rgba(imread(THEME / "eye.png"))
    ew = int(W * 0.30)
    eye_s = cv2.resize(eye_pm, (ew, int(ew * eye_pm.shape[0] / eye_pm.shape[1])), interpolation=cv2.INTER_AREA)
    eye_s = cv2.GaussianBlur(eye_s, (0, 0), 1.2)
    warm = np.array([0.86, 0.96, 1.08], np.float32)               # тёплая лампа (BGR)
    for fi in frames:
        tt = fi / FPS
        t = max(0.0, tt - T0)                                      # время сцены
        cam = cam_at(t)
        jit = 0.18 * (1 - smooth((t - 7.0) / 1.0))                 # камера в руках: лёгкое дыхание
        cam = Cam(cam.p + jit * np.array([math.sin(tt * 1.3), math.sin(tt * 1.7 + 1), math.sin(tt * 0.9 + 2)]),
                  cam.p + cam.f * 50 + jit * 0.5 * np.array([math.sin(tt * 1.1 + 3), math.sin(tt * 1.5), 0]))
        L = light_at(t) if tt >= T0 else 0.0
        u = (t - 4.2) / 2.2                                        # крышка: туго трогается, раскрывается, оседает
        open_u = 0.0 if u <= 0 else (smooth(u) + 0.05 * math.sin(min(u, 1.4) * math.pi / 1.4 * 2) * (u > 0.7))
        ang = math.radians(108 * open_u)
        frame = np.zeros((H, W, 3), np.float32)
        draw_face(frame, wall, [(-260, 190, -132), (260, 190, -132), (260, 0, -132), (-260, 0, -132)], cam)
        draw_face(frame, table, [(TX0, 0, TZ0), (TX1, 0, TZ0), (TX1, 0, TZ1), (TX0, 0, TZ1)], cam)
        frame *= L
        frame *= warm
        glow = 0.15 + 0.85 * smooth((open_u - 0.15) / 0.6)         # интерфейс светится сам, под крышкой — в тени
        if open_u > 0:
            draw_face(frame, inner, [(X0, Y1, Z0), (X1, Y1, Z0), (X1, floor_y, Z0), (X0, floor_y, Z0)], cam, 0.5 * L)
            draw_face(frame, ui_tex, [(X0 + .3, floor_y, Z0 + .3), (X1 - .3, floor_y, Z0 + .3),
                                      (X1 - .3, floor_y, Z1 - .3), (X0 + .3, floor_y, Z1 - .3)], cam, glow)
            draw_face(frame, inner_s, [(X0, Y1, Z0), (X0, Y1, Z1), (X0, floor_y, Z1), (X0, floor_y, Z0)], cam, 0.45 * L)
            draw_face(frame, inner_s, [(X1, Y1, Z1), (X1, Y1, Z0), (X1, floor_y, Z0), (X1, floor_y, Z1)], cam, 0.45 * L)
        # боковые грани коробки снаружи (видны, если камера сбоку) и передняя
        if cam.p[0] < X0:
            draw_face(frame, sidet, [(X0, Y1, Z0), (X0, Y1, Z1), (X0, 0, Z1), (X0, 0, Z0)], cam, 0.75 * L)
        if cam.p[0] > X1:
            draw_face(frame, sidet, [(X1, Y1, Z1), (X1, Y1, Z0), (X1, 0, Z0), (X1, 0, Z1)], cam, 0.75 * L)
        # крышка: на петлях по заднему краю, откидывается назад
        hy, hz = Y1, Z0
        lt = 0.6                                                   # толщина крышки (кромка)
        def lid_pt(x, zz):
            dz = zz - hz
            return (x, hy + dz * math.sin(ang) + 0.0, hz + dz * math.cos(ang))
        quad = [lid_pt(X0 - .4, Z0), lid_pt(X1 + .4, Z0), lid_pt(X1 + .4, Z1 + .4), lid_pt(X0 - .4, Z1 + .4)]
        # какая сторона крышки к камере: нормаль крышки
        nrm = np.array([0, math.cos(ang), -math.sin(ang)])
        if np.dot(cam.p - np.array(quad[0]), nrm) > 0:
            lid_shade = L * (1.0 - 0.25 * open_u) + 0.15 * open_u
            draw_face(frame, lid, quad, cam, lid_shade)
            # кромка крышки спереди
            edge = [quad[3], quad[2], (quad[2][0], quad[2][1] - lt, quad[2][2]), (quad[3][0], quad[3][1] - lt, quad[3][2])]
            draw_face(frame, sidet, edge, cam, 0.5 * L)
        else:
            draw_face(frame, lid_under, [quad[3], quad[2], quad[1], quad[0]], cam, 0.35 * L + 0.55 * open_u,
                      add=np.array([10, 30, 20]) * open_u)        # изнанка подсвечена интерфейсом
        draw_face(frame, front, [(X0, Y1, Z1), (X1, Y1, Z1), (X1, 0, Z1), (X0, 0, Z1)], cam, 0.85 * L)
        # свечение интерфейса из коробки
        if open_u > 0:
            c, _ = cam.proj([(0, BH, 0)])
            g = np.exp(-(((xx - c[0, 0]) / (W * 0.28)) ** 2 + ((yy - c[0, 1]) / (H * 0.3)) ** 2))
            frame += (g * 38 * open_u * (1 - smooth((t - 7.4) / 1.0)))[..., None] * np.array([0.5, 1.0, 0.75])
        if open_u > 0.3:                                           # мягкое свечение экрана (bloom)
            sm = cv2.resize(frame, (W // 8, H // 8), interpolation=cv2.INTER_AREA)
            sm = cv2.GaussianBlur(np.clip(sm - 120, 0, None), (0, 0), 6)
            frame += cv2.resize(sm, (W, H)) * 0.6 * smooth((open_u - 0.3) / 0.5)
        frame *= vign if t < 7.6 else vign + (1 - vign) * smooth((t - 7.6) / 0.8)
        # в темноте — еле видный глаз; гаснет, когда загорается лампа
        e = 0.0 if tt > T0 + 1.0 else (0.09 * smooth(tt / 1.0) * (0.75 + 0.25 * math.sin(tt * 3.0))
                                         * (1 - smooth((tt - T0) / 1.0)))
        if e > 0:
            eh, ew2 = eye_s.shape[:2]
            x0, y0 = (W - ew2) // 2, (H - eh) // 2
            a = eye_s[..., 3:4].astype(np.float32) / 255.0 * e
            roi = frame[y0:y0 + eh, x0:x0 + ew2]
            frame[y0:y0 + eh, x0:x0 + ew2] = roi * (1 - a) + eye_s[..., :3].astype(np.float32) * a
        # финал: интерфейс на весь кадр
        k = smooth((t - 7.7) / 0.7)
        if k > 0:
            frame = frame * (1 - k) + ui_full.astype(np.float32) * k
        frame += rng.standard_normal((H, W, 1)).astype(np.float32) * (3.0 * (1 - k))     # плёночное зерно
        if preview:
            cv2.imencode(".png", np.clip(frame, 0, 255).astype(np.uint8))[1].tofile(f"{out}_{tt:.1f}.png")
            continue
        proc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        if fi % 30 == 0:
            print(f"кадр {fi}/{n}", flush=True)
    if proc:
        proc.stdin.close()
        proc.wait()
    print("готово:", out)


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return str(ROOT / ".venv-smena" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries" /
                   "ffmpeg-win-x86_64-v7.1.exe")


if __name__ == "__main__":
    main()
