"""SMENA — порядок фото под альбом: фото раскладываются по трекам и слотам (T = 16 тактов на фото).

Правила автора (2026-10-16):
  • все ч/б фото — под трек 2;
  • трек 1 — начало, спокойные фото; трек 4 — накал, самые динамичные; трек 3 — середина;
  • красивое взаимное перетекание: соседние фото близки по свету и цвету (и на стыках треков).
Внутри трека фото повторяют кривую энергии трека: слоты с бóльшей энергией/событиями — более динамичные фото.

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\analysis\\photo_order.py ПАПКА_ТРЕКОВ ПАПКА_ФОТО КЕШ data\\photo_order.json
        [--sheet лист.jpg]
"""
import argparse
import json
import math
import random
import re
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SR, NFFT, HOP = 22050, 2048, 512
BPM = {1: 120.0, 2: 139.6, 3: 120.2, 4: 120.0}       # треки 1 и 4 без сетки — условные 120 (SPEC §2.1)
EXTS = {".jpg", ".jpeg", ".png"}
W_RANK, W_FLOW = 1.0, 1.6                            # стоимость: несоответствие энергии слота / скачок цвета
# поправки динамичности по просмотру (метрика не видит смысла кадра)
DYN_FIX = {"68": +1.6}                               # концерт, лучи света — тёмный кадр, но динамичный


def natural_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


# ================================================================ треки
def load(path):
    p = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "quiet", "-i", str(path), "-f", "f32le", "-ac", "1",
                        "-ar", str(SR), "-"], capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32)


def track_curve(x):
    """Покадровые признаки → энергия: громкость, атаки, яркость, доля верха."""
    n = (len(x) - NFFT) // HOP
    win = np.hanning(NFFT).astype(np.float32)
    fr = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP][:n] * win
    S = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    rms = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    lg = np.log1p(S * 100)
    flux = np.maximum(np.diff(lg, axis=0, prepend=lg[:1]), 0).sum(1)
    cent = np.log2((S * f).sum(1) / S.sum(1) + 1)
    high = 10 * np.log10((S[:, f > 4000] ** 2).sum(1) + 1e-9)
    return dict(rms=rms, flux=flux, cent=cent, high=high, fps=SR / HOP)


def slots(track_no, cur, events, n_slots):
    """Энергия каждого слота трека: атаки + громкость + яркость + события (смены, акценты, обрывы)."""
    fps = cur["fps"]
    dur = len(cur["rms"]) / fps
    edges = np.linspace(0, dur, n_slots + 1)
    ev_t = []
    for name, w in (("Акцент: удар выше локального фона", 0.15), ("Одновременная смена ≥3 признаков", 1.0),
                    ("Смена гармонии / тонального центра", 1.0), ("Провал / пауза (−6 дБ, ≥0.25 с)", 0.4),
                    ("Ритмичность (ясность пульса)", 0.6)):
        ev_t += [(e["t"], w) for e in events.get(name, {}).get(str(track_no), [])]
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        i, j = int(a * fps), max(int(b * fps), int(a * fps) + 1)
        ev = sum(w for t, w in ev_t if a <= t < b)
        out.append(dict(t0=float(a), t1=float(b), flux=float(cur["flux"][i:j].mean()), rms=float(cur["rms"][i:j].mean()),
                        cent=float(cur["cent"][i:j].mean()), high=float(cur["high"][i:j].mean()), ev=ev))
    return out


def zs(v):
    v = np.asarray(v, float)
    return (v - v.mean()) / (v.std() + 1e-9)


# ================================================================ фото
def photo_features(path, cache_dir):
    img = Image.open(path).convert("RGB")
    img.thumbnail((640, 640))
    a = np.asarray(img)
    lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
    L, A, B = lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.hypot(A, B)
    gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 150) > 0
    rg = a[..., 0].astype(float) - a[..., 1]
    yb = 0.5 * (a[..., 0].astype(float) + a[..., 1]) - a[..., 2]
    colorful = math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean())   # Hasler–Süsstrunk
    n_el = 0
    pj = Path(cache_dir) / path.stem / "photo.json"
    if pj.exists():
        n_el = len(json.loads(pj.read_text(encoding="utf-8")).get("elements", []))
    # ч/б — без цветности вовсе (приглушённые цветные, например ba-03, остаются цветными)
    bw = float(np.percentile(chroma, 95)) < 3
    return dict(name=path.stem, file=path.name, bw=bool(bw), L=float(L.mean()), A=float(A.mean()), B=float(B.mean()),
                contrast=float(L.std()), edge=float(edges.mean()), colorful=float(colorful),
                chroma=float(chroma.mean()), n_el=n_el)


def dynamics(ph):
    """Динамичность: детали/края, контраст, красочность, число элементов (+ поправки по просмотру)."""
    e, c, k, n = (zs([p[key] for p in ph]) for key in ("edge", "contrast", "colorful", "n_el"))
    for i, p in enumerate(ph):
        base = re.sub(r"^\d{2} - ", "", p["name"])          # имя без номера порядка
        p["dyn"] = float(0.35 * e[i] + 0.2 * c[i] + 0.25 * k[i] + 0.2 * n[i]) + DYN_FIX.get(base, 0.0)


def color_vec(p):
    return np.array([p["L"] / 12.0, p["A"] / 6.0, p["B"] / 6.0, p["contrast"] / 8.0])


# ================================================================ раскладка
def order_track(photos, slot_e, prev=None, nxt=None, seed=1):
    """Порядок фото в треке: ранг динамичности ↔ ранг энергии слота + плавность цвета (отжиг перестановками)."""
    n = len(photos)
    rank_e = np.argsort(np.argsort(slot_e)) / max(n - 1, 1)
    dyn = np.array([p["dyn"] for p in photos])
    rank_d = np.argsort(np.argsort(dyn)) / max(n - 1, 1)
    cv = [color_vec(p) for p in photos]
    order = list(np.argsort(dyn)[np.argsort(np.argsort(slot_e))])          # старт: ранг в ранг

    def cost(o):
        c = W_RANK * sum(abs(rank_d[o[s]] - rank_e[s]) for s in range(n))
        c += W_FLOW * sum(np.linalg.norm(cv[o[s]] - cv[o[s + 1]]) for s in range(n - 1)) / max(n - 1, 1) * 3
        if prev is not None:
            c += W_FLOW * np.linalg.norm(color_vec(prev) - cv[o[0]])
        if nxt is not None:
            c += W_FLOW * 0.5 * np.linalg.norm(cv[o[-1]] - color_vec(nxt))
        return c

    rng = random.Random(seed)
    best, best_c = order[:], cost(order)
    cur, cur_c = order[:], best_c
    temp = 1.0
    for it in range(20000):
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j:
            continue
        o = cur[:]
        o[i], o[j] = o[j], o[i]
        c = cost(o)
        if c < cur_c or rng.random() < math.exp((cur_c - c) / max(temp, 1e-4)):
            cur, cur_c = o, c
            if c < best_c:
                best, best_c = o[:], c
        temp *= 0.9995
    return [photos[k] for k in best]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tracks")
    ap.add_argument("photos")
    ap.add_argument("cache")
    ap.add_argument("out")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--events", default=str(Path(__file__).resolve().parents[2] / "data/analysis/events.json"))
    a = ap.parse_args()

    files = sorted((p for p in Path(a.photos).iterdir() if p.suffix.lower() in EXTS), key=lambda p: natural_key(p.stem))
    ph = [photo_features(p, a.cache) for p in files]
    dynamics(ph)
    bw = [p for p in ph if p["bw"]]
    col = sorted((p for p in ph if not p["bw"]), key=lambda p: p["dyn"])
    print(f"фото: {len(ph)}, ч/б: {len(bw)} — {', '.join(p['name'] for p in bw)}")

    tracks = sorted(Path(a.tracks).glob("*.flac"), key=lambda p: natural_key(p.name))
    events = json.loads(Path(a.events).read_text(encoding="utf-8"))["results"]
    curves, durs = {}, {}
    for i, t in enumerate(tracks, 1):
        curves[i] = track_curve(load(t))
        durs[i] = len(curves[i]["rms"]) / curves[i]["fps"]
        print(f"трек {i}: {t.name}, {durs[i] / 60:.2f} мин")
    # число фото на трек — по длительности (T = 16 тактов), ч/б целиком в трек 2
    T = {i: 64 * 60 / BPM[i] for i in durs}
    raw = {i: durs[i] / T[i] for i in durs}
    k = len(ph) / sum(raw.values())
    n = {i: max(1, round(raw[i] * k)) for i in raw}
    n[2] = max(n[2], len(bw))
    rest = len(ph) - n[2]
    others = [1, 3, 4]
    tot = sum(raw[i] for i in others)
    for i in others:
        n[i] = round(raw[i] / tot * rest)
    n[3] += len(ph) - sum(n.values())
    print("фото на трек:", n, "| T, с:", {i: round(T[i], 1) for i in T})

    # трек 1 — самые спокойные цветные, трек 4 — самые динамичные, середина — трек 3 (и недобор трека 2)
    n2_col = n[2] - len(bw)
    t1, t4 = col[:n[1]], col[len(col) - n[4]:]
    mid = col[n[1]:len(col) - n[4]]
    # в трек 2 — недостающие цветные, самые приглушённые по цвету из середины
    mid_sorted = sorted(mid, key=lambda p: p["chroma"])
    t2 = bw + mid_sorted[:n2_col]
    t3 = [p for p in mid if p not in t2]
    groups = {1: t1, 2: t2, 3: t3, 4: t4}

    plan, prev = [], None
    for i in (1, 2, 3, 4):
        sl = slots(i, curves[i], events, len(groups[i]))
        e = zs([s["flux"] for s in sl]) * 0.4 + zs([s["ev"] for s in sl]) * 0.3 + zs([s["cent"] for s in sl]) * 0.15 \
            + zs([s["rms"] for s in sl]) * 0.15
        nxt_group = groups.get(i + 1)
        nxt = min(nxt_group, key=lambda p: p["dyn"]) if nxt_group else None
        ordered = order_track(groups[i], e, prev=prev, nxt=nxt, seed=i)
        for j, (s, p) in enumerate(zip(sl, ordered)):
            plan.append(dict(track=i, t0=round(s["t0"], 1), t1=round(s["t1"], 1), energy=round(float(e[j]), 2), **p))
        prev = ordered[-1]

    for k_, p in enumerate(plan, 1):
        p["seq"] = k_
        p["new"] = f"{k_:02d} - {re.sub(r'^\d{2} - ', '', p['name'])}"
    out = {"rules": "ч/б → трек 2; трек 1 спокойные; трек 4 самые динамичные; плавные переходы по свету/цвету",
           "photos_per_track": n, "plan": plan}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in plan:
        print(f"{p['seq']:2d} трек {p['track']} {p['t0']:6.1f}–{p['t1']:6.1f} с  E={p['energy']:+.2f}  "
              f"дин={p['dyn']:+.2f} {'ч/б' if p['bw'] else '   '} L={p['L']:4.1f}  {p['name']}")
    if a.sheet:
        sheet(plan, files, a.sheet)


def sheet(plan, files, path):
    by = {f.stem: f for f in files}
    tw, th, cols = 240, 160, 16
    rows = []
    for t in (1, 2, 3, 4):
        rows.append([p for p in plan if p["track"] == t])
    H = sum(math.ceil(len(r) / cols) for r in rows) * (th + 22) + 30 * 4
    im = Image.new("RGB", (cols * tw, H), "black")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    fb = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
    y = 0
    for t, r in zip((1, 2, 3, 4), rows):
        d.text((6, y + 4), f"ТРЕК {t}", font=fb, fill=(255, 200, 0))
        y += 30
        for i, p in enumerate(r):
            x = (i % cols) * tw
            if i and i % cols == 0:
                y += th + 22
            th_im = Image.open(by[p["name"]]).convert("RGB")
            th_im.thumbnail((tw - 4, th - 4))
            im.paste(th_im, (x + 2, y + 2))
            d.text((x + 4, y + th + 2), f"{p['seq']:02d} E{p['energy']:+.1f} d{p['dyn']:+.1f} {p['name'][-14:]}",
                   font=font, fill="white")
        y += th + 22
    im.save(path, quality=85)
    print("лист:", path)


if __name__ == "__main__":
    main()
