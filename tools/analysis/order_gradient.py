"""SMENA — порядок фото по градиенту светлоты (от самых светлых к самым тёмным).

Правила автора (2026-10-16, набор London):
  • основной ряд — по светлоте, от светлых к тёмным;
  • фото с повторами сюжета (серии одного кадра) не стоят друг за другом: в ряду по градиенту остаётся одно
    фото серии, остальные раскидываются случайно по всему ряду, независимо от градиента,
    и никогда не встают рядом с фото своей серии.
Повтор сюжета — похожи уменьшенный кадр и гистограмма цвета, или один и тот же предмет с другого места
(совпадение особых точек ORB, проверенное гомографией RANSAC).

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\analysis\\order_gradient.py ПАПКА_ФОТО ПЛАН.json [--sheet лист.jpg]
        [--sim 0.80] [--seed 7]
План совместим с tools/prep/rename_photos.py («NNN - имя.jpg»).
"""
import argparse
import json
import math
import random
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EXTS = {".jpg", ".jpeg", ".png"}
ORB = cv2.ORB_create(1500)
MATCHER = cv2.BFMatcher(cv2.NORM_HAMMING)
INLIERS = 25                 # столько согласованных точек — тот же предмет (повтор сюжета)
MIN_GAP = 4                  # фото одной серии — не ближе стольких позиций друг к другу


def natural_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def features(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((512, 512))
    a = np.asarray(im)
    lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB)
    L = float(lab[..., 0].mean()) * 100 / 255
    g = cv2.resize(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), (32, 22), interpolation=cv2.INTER_AREA).astype(np.float32)
    g = (g - g.mean()) / (g.std() + 1e-6)
    hsv = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
    h /= h.sum() + 1e-9
    # особые точки — узнать тот же предмет при другом кадрировании
    kp, des = ORB.detectAndCompute(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), None)
    pts = np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32)
    return dict(L=L, g=g.ravel(), h=h, pts=pts, des=des)


def same_object(a, b):
    """Число геометрически согласованных совпадений особых точек (RANSAC, гомография)."""
    if a["des"] is None or b["des"] is None or len(a["des"]) < 10 or len(b["des"]) < 10:
        return 0
    m = MATCHER.knnMatch(a["des"], b["des"], k=2)
    good = [p[0] for p in m if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 12:
        return 0
    src = a["pts"][[g.queryIdx for g in good]]
    dst = b["pts"][[g.trainIdx for g in good]]
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
    return int(mask.sum()) if mask is not None else 0


def similarity(a, b):
    corr = float(np.dot(a["g"], b["g"]) / len(a["g"]))
    inter = float(np.minimum(a["h"], b["h"]).sum())
    return 0.6 * corr + 0.4 * inter


def clusters(feats, thr, inliers=INLIERS):
    """Серии: связные компоненты — похож кадр целиком или совпадает предмет (особые точки)."""
    n = len(feats)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    sims = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            s = similarity(feats[i], feats[j])
            sims[i, j] = sims[j, i] = s
            if s >= thr or same_object(feats[i], feats[j]) >= inliers:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values()), sims


def arrange(names, Ls, groups, seed):
    """Ряд по светлоте из представителей серий + остальные члены серий случайно по ряду, не рядом со своими."""
    rng = random.Random(seed)
    gid = {i: k for k, g in enumerate(groups) for i in g}
    reps, extras = [], []
    for g in groups:
        g = sorted(g, key=lambda i: Ls[i])
        rep = g[len(g) // 2]                      # представитель серии — средний по светлоте
        reps.append(rep)
        extras += [i for i in g if i != rep]
    row = sorted(reps, key=lambda i: -Ls[i])      # от светлых к тёмным
    rng.shuffle(extras)
    for i in extras:
        for gap in range(MIN_GAP, 0, -1):         # не ближе MIN_GAP позиций к фото своей серии (если можно)
            ok = [p for p in range(len(row) + 1)
                  if all(gid[row[q]] != gid[i] for q in range(max(0, p - gap), min(len(row), p + gap)))]
            if ok:
                break
        row.insert(rng.choice(ok) if ok else rng.randrange(len(row) + 1), i)
    # страховка: никаких соседей из одной серии
    for _ in range(1000):
        bad = [p for p in range(len(row) - 1) if gid[row[p]] == gid[row[p + 1]]]
        if not bad:
            break
        p = bad[0] + 1
        i = row.pop(p)
        ok = [q for q in range(len(row) + 1)
              if (q == 0 or gid[row[q - 1]] != gid[i]) and (q == len(row) or gid[row[q]] != gid[i])]
        row.insert(rng.choice(ok), i)
    return row, gid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos")
    ap.add_argument("out")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--sim", type=float, default=0.80)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    files = sorted((p for p in Path(a.photos).iterdir() if p.suffix.lower() in EXTS and not p.name.startswith("._")),
                   key=lambda p: natural_key(p.stem))           # «._*» — служебные файлы macOS
    feats = [features(p) for p in files]
    Ls = [f["L"] for f in feats]
    groups, sims = clusters(feats, a.sim)
    series = [g for g in groups if len(g) > 1]
    print(f"фото {len(files)}, серий с повторами {len(series)} (в них {sum(len(g) for g in series)} фото)")
    for g in sorted(series, key=len, reverse=True):
        print("  серия:", ", ".join(files[i].stem for i in g))
    row, gid = arrange([f.stem for f in files], Ls, groups, a.seed)
    width = max(3, len(str(len(row))))
    plan = []
    for k, i in enumerate(row, 1):
        stem = re.sub(r"^\d{2,3} - ", "", files[i].stem)
        plan.append(dict(track=1, seq=k, name=files[i].stem, file=files[i].name, new=f"{k:0{width}d} - {stem}",
                         L=round(Ls[i], 1), series=gid[i] if len(groups[gid[i]]) > 1 else None))
    Path(a.out).write_text(json.dumps({"rules": "светлые → тёмные; повторы сюжета — случайно по ряду, не рядом",
                                       "sim": a.sim, "seed": a.seed, "plan": plan}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print("план:", a.out)
    if a.sheet:
        sheet(files, row, Ls, gid, groups, a.sheet)


def sheet(files, row, Ls, gid, groups, path):
    tw, th, cols = 200, 150, 15
    rows = math.ceil(len(row) / cols)
    im = Image.new("RGB", (cols * tw, rows * (th + 18)), "black")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
    palette = [(255, 80, 80), (80, 220, 120), (90, 160, 255), (255, 200, 60), (230, 90, 255), (60, 230, 230),
               (255, 140, 40), (180, 255, 90), (255, 110, 180), (140, 120, 255)]
    for k, i in enumerate(row):
        x, y = (k % cols) * tw, (k // cols) * (th + 18)
        t = Image.open(files[i]).convert("RGB")
        t.thumbnail((tw - 4, th - 4))
        im.paste(t, (x + 2, y + 2))
        ser = len(groups[gid[i]]) > 1
        col = palette[gid[i] % len(palette)] if ser else (200, 200, 200)
        if ser:
            d.rectangle([x + 1, y + 1, x + tw - 2, y + th - 2], outline=col, width=3)
        d.text((x + 3, y + th + 1), f"{k + 1:03d} L{Ls[i]:.0f} {files[i].stem[-10:]}", font=font, fill=col)
    im.save(path, quality=85)
    print("лист:", path)


if __name__ == "__main__":
    main()
