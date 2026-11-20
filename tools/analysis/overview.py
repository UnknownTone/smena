import os, numpy as np
os.environ["SDL_VIDEODRIVER"] = "dummy"
import pygame
pygame.init(); font = pygame.font.SysFont("segoeui", 14)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
def smooth(x, s): k = max(1, int(s * FPS)); return np.convolve(x, np.ones(k) / k, "same")
def db(x): return 10 * np.log10(x + 1e-10)
rows = [("RMS дБ", lambda f: db(smooth(f["rms"]**2, .5))),
        ("Sub 20-60", lambda f: db(smooth(f["e_sub"], .5))), ("Bass 60-150", lambda f: db(smooth(f["e_bass"], .5))),
        ("LowMid", lambda f: db(smooth(f["e_lowmid"], .5))), ("Mid", lambda f: db(smooth(f["e_mid"], .5))),
        ("HiMid", lambda f: db(smooth(f["e_himid"], .5))), ("High 6k+", lambda f: db(smooth(f["e_high"], .5))),
        ("Центроид", lambda f: smooth(f["centroid"], 1)), ("Плоскостность", lambda f: smooth(f["flatness"], 1)),
        ("Ударные/тон", lambda f: smooth(f["perc_ratio"], 1)), ("Стерео ширина", lambda f: smooth(f["side_ratio"], 1)),
        ("Атаки (flux)", lambda f: smooth(f["flux"], .25)), ("Атаки баса", lambda f: smooth(f["flux_bass"], .25))]
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); loc = np.load(os.path.join(OUT, f"loc_{k}.npy"))
    n = len(f["rms"]); W, RH, LX = 1800, 52, 120
    img = pygame.Surface((W, RH * (len(rows) + 1) + 30)); img.fill((18, 18, 18))
    dur = n / FPS
    for m in range(0, int(dur) + 1, 30):
        x = LX + (W - LX - 10) * m / dur
        pygame.draw.line(img, (45, 45, 45), (x, 0), (x, img.get_height()))
        img.blit(font.render(f"{m//60}:{m%60:02d}", True, (120, 120, 120)), (x + 2, img.get_height() - 22))
    allrows = rows + [("Пульс (ясность)", None)]
    for r, (name, fn) in enumerate(allrows):
        y0 = r * RH + 4
        img.blit(font.render(name, True, (200, 200, 200)), (6, y0 + 14))
        if fn: v = fn(f); xs = np.linspace(LX, W - 10, n)
        else: v = loc[:, 2]; xs = LX + (W - LX - 10) * (loc[:, 0] + 8) / dur
        lo, hi = np.percentile(v, 1), np.percentile(v, 99.5)
        ys = y0 + RH - 6 - (np.clip((v - lo) / (hi - lo + 1e-12), 0, 1)) * (RH - 10)
        step = max(1, len(v) // 3000)
        pts = list(zip(xs[::step], ys[::step]))
        pygame.draw.lines(img, (61, 220, 151) if r % 2 else (255, 106, 61), False, pts, 1)
    pygame.image.save(img, os.path.join(OUT, f"overview_{k}.png")); print("ok", k)
