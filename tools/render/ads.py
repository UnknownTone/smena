r"""10 вертикальных роликов для рекламы (1080×1920, 20 с, без текста) из записи SMENA — разные сюжеты и композиции.
Звук — трек с самого начала; склейки и акценты — по сетке долей трека.

Запуск: .venv-prep\Scripts\python.exe tools\render\ads.py <запись.mp4> <трек> <папка> [номер ...]
"""
import math
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intro_box as B                                               # noqa: E402

W, H, FPS, DUR = 1080, 1920, 30, 20.0
N = int(DUR * FPS)
BPM, BEAT0 = 121.6, 0.081                                           # «Вознесение» (render_demo.estimate_bpm)
BEAT = 60.0 / BPM
BAR = 4 * BEAT
# сюжеты записи: (начало, с)
SC = dict(green=2, islands=32, rocks=62, sky=80, wall=91, snow=101, cranes=122, white=162, ice=196,
          pyramids=262, valley=292, ground=335, monolith=372, house=425)
REC = None
EYE = B.THEME / "eye.png"


class Reader:
    """Кадры записи с момента start, размер (w, h), BGR uint8."""

    def __init__(self, start, w=1920, h=1080, speed=1.0):
        self.w, self.h = w, h
        vf = f"scale={w}:{h}" + (f",setpts={1 / speed}*PTS" if speed != 1.0 else "")
        self.p = subprocess.Popen([B.ffmpeg(), "-v", "error", "-ss", f"{start:.3f}", "-i", REC, "-vf", vf,
                                   "-r", str(FPS), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                                  stdout=subprocess.PIPE, bufsize=w * h * 3 * 2)
        self.last = np.zeros((h, w, 3), np.uint8)

    def next(self):
        raw = self.p.stdout.read(self.w * self.h * 3)
        if len(raw) == self.w * self.h * 3:
            self.last = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3)
        return self.last

    def close(self):
        self.p.kill()


def beat_at(t):
    return (t - BEAT0) / BEAT


def crop916(img, cx=0.5, zoom=1.0):
    """Вырез 9:16 из кадра 16:9 (центр cx — доля ширины), zoom ≥ 1 — крупнее."""
    h, w = img.shape[:2]
    ch = h / zoom
    cw = ch * 9 / 16
    x0 = min(max(cx * w - cw / 2, 0), w - cw)
    y0 = (h - ch) / 2
    c = img[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
    return cv2.resize(c, (W, H), interpolation=cv2.INTER_CUBIC)


def grain(f, t, amt=6.0, vign=0.35):
    rng = np.random.default_rng(int(t * 1000))
    f = f.astype(np.float32) + rng.standard_normal((H // 2, W // 2, 1)).astype(np.float32).repeat(2, 0).repeat(2, 1) * amt
    if vign:
        f *= VIGN ** vign
    return f


yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
VIGN = (1 - 0.6 * (((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.75)) ** 2)).clip(0.2, 1)[..., None]


def fade(f, t):
    """Вход из чёрного 0.4 с, уход в чёрное последние 1.2 с."""
    k = min(1.0, t / 0.4) * min(1.0, (DUR - t) / 1.2)
    return f * max(0.0, k)


# ----------------------------------------------------------------------------------- сюжеты
def v01_okno(t, st):
    """Окно: один долгий план — сумерки над островами, медленная панорама и наезд."""
    r = st.setdefault("r", Reader(SC["islands"]))
    u = t / DUR
    return grain(crop916(r.next(), 0.22 + 0.56 * u, 1.0 + 0.18 * u), t)


def v02_ritm(t, st):
    """Ритм: склейка каждые 2 доли по всем сюжетам, удар-наезд и вспышка на склейке."""
    keys = ["islands", "cranes", "ice", "pyramids", "snow", "valley", "monolith", "white", "rocks", "house",
            "ground", "green", "wall", "sky"]
    k = max(0, int(beat_at(t) // 2))
    if st.get("k") != k:
        if "r" in st:
            st["r"].close()
        st["k"] = k
        st["r"] = Reader(SC[keys[k % len(keys)]] + 3 + (k // len(keys)) * 6)
        st["t0"] = t
    dt = t - st["t0"]
    zoom = 1.0 + 0.12 * math.exp(-dt / 0.18)
    f = crop916(st["r"].next(), 0.5, zoom).astype(np.float32)
    f += 120 * math.exp(-dt / 0.06)
    return grain(f, t, 7)


def v03_triptih(t, st):
    """Триптих: три горизонтальные полосы — три разных сюжета; каждые 2 такта одна полоса меняется."""
    groups = [("cranes", "valley", "ice"), ("monolith", "pyramids", "islands"), ("house", "snow", "rocks"),
              ("white", "ground", "sky")]
    if "rs" not in st:
        st["rs"] = [Reader(SC[n], 1080, 608) for n in groups[0]]
        st["g"] = 0
    g = int(max(0, beat_at(t)) // 8)
    if g != st["g"]:
        st["g"] = g
        i = g % 3
        st["rs"][i].close()
        st["rs"][i] = Reader(SC[groups[g % len(groups)][i]] + 4, 1080, 608)
    f = np.zeros((H, W, 3), np.float32)
    gap = (H - 3 * 608) // 4
    for i, r in enumerate(st["rs"]):
        y = gap + i * (608 + gap)
        f[y:y + 608] = r.next()
    return grain(f, t, 5, 0.2)


def v04_zerkalo(t, st):
    """Зеркало: пейзаж, отражённый по горизонтали посередине — небо сверху и снизу, земля в центре."""
    r = st.setdefault("r", Reader(SC["pyramids"] if t < 10 else SC["valley"]))
    if t >= 10 and not st.get("sw"):
        st["sw"] = True
        r.close()
        r = st["r"] = Reader(SC["valley"] + 6)
    c = crop916(r.next(), 0.35 + 0.3 * math.sin(t / DUR * math.pi), 1.15)
    band = c[int(H * 0.30):int(H * 0.72)]                             # горизонт с землёй — у линии отражения
    top = cv2.resize(band, (W, H // 2), interpolation=cv2.INTER_CUBIC)
    f = np.vstack([top, top[::-1]]).astype(np.float32)
    return grain(f, t, 5)


def v05_zum(t, st):
    """Из ленты в кадр: 16:9 в окне на размытом фоне медленно разрастается до полного вертикального кадра."""
    r = st.setdefault("r", Reader(SC["monolith"]))
    img = r.next()
    u = B.smooth(t / (DUR * 0.85))
    bg = cv2.GaussianBlur(crop916(img, 0.5, 1.0), (0, 0), 28).astype(np.float32) * 0.45
    full = crop916(img, 0.5, 1.0).astype(np.float32)
    s = W / 1920 * (1 - u) + (H / 1080) * u                          # масштаб: по ширине → по высоте
    w2, h2 = int(1920 * s), int(1080 * s)
    big = cv2.resize(img, (w2, h2), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    x0, y0 = (W - w2) // 2, (H - h2) // 2
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    cw, chh = min(W - dx0, w2 - sx0), min(H - dy0, h2 - sy0)
    f = bg.copy()
    f[dy0:dy0 + chh, dx0:dx0 + cw] = big[sy0:sy0 + chh, sx0:sx0 + cw]
    del full
    return grain(f, t, 5)


def v06_slit(t, st):
    """Щелевая развёртка: каждая строка кадра — из своего момента времени (низ отстаёт на секунду)."""
    r = st.setdefault("r", Reader(SC["ice"], 607, 1080))
    buf = st.setdefault("buf", [])
    fr = cv2.resize(r.next(), (W, H), interpolation=cv2.INTER_CUBIC)
    buf.append(fr)
    D = 30
    if len(buf) > D:
        buf.pop(0)
    f = np.empty((H, W, 3), np.uint8)
    band = H // D
    for i in range(D):
        src = buf[max(0, len(buf) - 1 - i)]
        f[i * band:(i + 1) * band] = src[i * band:(i + 1) * band]
    f[D * band:] = buf[0][D * band:]
    return grain(f, t, 5)


def v07_mozaika(t, st):
    """Мозаика 2×3: шесть сюжетов сразу; на каждый такт одна плитка сменяется."""
    names = ["cranes", "ice", "valley", "monolith", "islands", "snow", "pyramids", "house", "white", "rocks", "ground"]
    tw, th = 540, 640
    if "rs" not in st:
        st["rs"] = [Reader(SC[n], 1138, 640) for n in names[:6]]
        st["bar"] = 0
        st["next"] = 6
    bar = int(max(0, beat_at(t)) // 4)
    if bar != st["bar"]:
        st["bar"] = bar
        i = (bar * 5) % 6
        st["rs"][i].close()
        st["rs"][i] = Reader(SC[names[st["next"] % len(names)]] + 5, 1138, 640)
        st["next"] += 1
        st["flash"] = (i, t)
    f = np.zeros((H, W, 3), np.float32)
    for i, r in enumerate(st["rs"]):
        img = r.next()
        x0 = (1138 - tw) // 2
        tile = img[:, x0:x0 + tw].astype(np.float32)
        fl = st.get("flash")
        if fl and fl[0] == i:
            tile = tile + 140 * math.exp(-(t - fl[1]) / 0.08)
        cx, cy = (i % 2) * tw, (i // 2) * th
        f[cy:cy + th, cx:cx + tw] = tile
    f[:, tw - 2:tw + 2] = 0
    f[th - 2:th + 2] = 0
    f[2 * th - 2:2 * th + 2] = 0
    return grain(f, t, 5, 0.25)


def v08_glaz(t, st):
    """Глаз: в темноте разгорается глаз SMENA, затем зрачок раскрывается кругом — в нём пейзаж."""
    if "eye" not in st:
        e = B.rgba(B.imread(EYE))
        ew = int(W * 0.7)
        st["eye"] = cv2.resize(e, (ew, int(ew * e.shape[0] / e.shape[1])), interpolation=cv2.INTER_AREA)
        st["r"] = Reader(SC["snow"])
    img = crop916(st["r"].next(), 0.5, 1.0).astype(np.float32)
    f = np.zeros((H, W, 3), np.float32)
    t_open = 4 * BAR / 2 + BEAT0                                       # раскрытие на 2-м такте
    rad = 0.0 if t < t_open else (max(W, H) * 0.75) * B.smooth((t - t_open) / (3 * BEAT))
    if rad > 0:
        m = (np.sqrt((xx - W / 2) ** 2 + (yy - H / 2) ** 2) < rad).astype(np.float32)
        m = cv2.GaussianBlur(m, (0, 0), 12)[..., None]
        f = img * m
    e = st["eye"]
    eh, ew = e.shape[:2]
    x0, y0 = (W - ew) // 2, (H - eh) // 2
    a = e[..., 3:4].astype(np.float32) / 255.0
    glow = min(1.0, t / 1.8) * (0.8 + 0.2 * math.sin(t * 4)) * (1 - B.smooth((t - t_open) / (2 * BEAT)))
    roi = f[y0:y0 + eh, x0:x0 + ew]
    f[y0:y0 + eh, x0:x0 + ew] = roi * (1 - a * glow) + e[..., :3].astype(np.float32) * a * glow
    return grain(f, t, 6)


def v09_plyonka(t, st):
    """Плёнка: вертикальная киноплёнка с перфорацией едет вверх, в каждом кадре — свой живой сюжет."""
    names = ["islands", "cranes", "ice", "valley", "monolith", "house", "pyramids", "snow"]
    fw, fh = 900, 506
    pitch = fh + 70
    if "rs" not in st:
        st["rs"] = {}
    off = t * 160.0                                                    # скорость протяжки, пикс/с
    f = np.full((H, W, 3), 14, np.float32)
    x0 = (W - fw) // 2
    f[:, x0 - 70:x0 + fw + 70] = 22
    k0 = int(off // pitch)
    used = set()
    for k in range(k0 - 1, k0 + 5):
        y = int(k * pitch - off + 60)
        if y > H or y + fh < 0:
            continue
        used.add(k)
        if k not in st["rs"]:
            st["rs"][k] = Reader(SC[names[k % len(names)]] + 3, fw, fh)
        img = st["rs"][k].next().astype(np.float32) * 0.92
        ya, yb = max(0, y), min(H, y + fh)
        f[ya:yb, x0:x0 + fw] = img[ya - y:yb - y]
    for k in [k for k in st["rs"] if k not in used]:
        st["rs"].pop(k).close()
    for y in range(int(-off % 64) - 64, H, 64):                         # перфорация
        for xh in (x0 - 50, x0 + fw + 22):
            cv2.rectangle(f, (xh, y), (xh + 28, y + 36), (2, 2, 2), -1)
    f *= np.array([0.9, 0.97, 1.08], np.float32)                       # тёплая плёнка
    return grain(f, t, 9, 0.5)


def v10_vspyshki(t, st):
    """Вспышки: два сюжета чередуются на каждую долю, стробоскоп нарастает к середине, затем отпускает."""
    if "a" not in st:
        st["a"], st["b"] = Reader(SC["house"]), Reader(SC["ground"] + 8)
    fa, fb = st["a"].next(), st["b"].next()
    b = beat_at(t)
    k = int(max(0, b))
    ph = b - math.floor(b)
    img = fa if k % 2 == 0 else fb
    zoom = 1.0 + 0.08 * math.exp(-ph * BEAT / 0.12)
    f = crop916(img, 0.5 if k % 2 == 0 else 0.42, zoom).astype(np.float32)
    inten = math.sin(math.pi * min(1.0, t / DUR)) ** 1.5
    f += 200 * inten * math.exp(-ph * BEAT / 0.05)
    if k % 4 == 3 and ph > 0.5:                                         # редкий негатив на последнюю долю такта
        f = 255 - f * 0.9
    return grain(f, t, 7)


ADS = [v01_okno, v02_ritm, v03_triptih, v04_zerkalo, v05_zum, v06_slit, v07_mozaika, v08_glaz, v09_plyonka,
       v10_vspyshki]


def render(i, track, out_dir):
    fn = ADS[i]
    out = Path(out_dir) / f"SMENA_ad_{i + 1:02d}_{fn.__name__.split('_', 1)[1]}.mp4"
    proc = subprocess.Popen(
        [B.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-ss", "0", "-t", f"{DUR}", "-i", track,
         "-af", f"afade=t=in:st=0:d=0.1,afade=t=out:st={DUR - 1.5}:d=1.5", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "14M", "-bufsize", "28M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest",
         "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    st = {}
    for k in range(N):
        t = k / FPS
        f = fade(fn(t, st), t)
        proc.stdin.write(np.clip(f, 0, 255).astype(np.uint8).tobytes())
    for v in st.values():
        if isinstance(v, Reader):
            v.close()
        elif isinstance(v, list):
            [r.close() for r in v if isinstance(r, Reader)]
        elif isinstance(v, dict):
            [r.close() for r in v.values() if isinstance(r, Reader)]
    proc.stdin.close()
    proc.wait()
    print("готово:", out.name, flush=True)


if __name__ == "__main__":
    REC, track, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    which = [int(x) - 1 for x in sys.argv[4:]] or range(len(ADS))
    for i in which:
        render(i, track, out_dir)
