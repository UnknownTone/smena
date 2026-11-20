"""SMENA — автоматический отбор элементов из кандидатов (этап между candidates.py и build_elements.py).

Правила v2 (указания автора, 2026-10-16) — каждое само по себе причина взять кандидат:
  • явно горизонтальные и вертикальные элементы — вытянутые вдоль осей кадра (двери, окна, столбы, карнизы);
  • контрастные — яркость заметно отличается от окружения;
  • отдельные цветные — насыщенный цвет, другой оттенок, чем вокруг и в фото в целом;
  • отдельно стоящие в композиции — по всему кольцу вокруг элемента «другое» (фон, небо, стена).
Общая оценка v1 (рукотворность × детали) — пятое основание, чтобы хорошие находки v1 не терялись.
Сохранено из v1: не берём слои во весь кадр (касание ≥ 2 краёв, > 80% ширины/высоты, > 25% площади),
«целое или части», ≤ 7 элементов без больших перекрытий, бонус за детали внутри (есть что анимировать).
Отдельно стоящие и ярко-цветные берутся, даже если слабее лучшего на фото.
Крупные элементы (2026-10-16): пейзаж или меньше трёх мелких/средних элементов → длинные горизонтальные куски
из слоёв (35–60% ширины, от края слоя; в selection — {"n": кандидат, "box": [x0, y0, x1, y1]}) и крупные
компактные куски подходящей формы.

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\prep\\auto_select.py ПАПКА_ФОТО ПАПКА_КАНДИДАТОВ selection.json [--report]
"""
import argparse
import json
import math
import random
import zlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from torn import torn_piece   # noqa: E402

MAX_ELEMENTS = 32           # до 32 элементов на фото (SPEC §3.1, решение 2026-10-17)
MAX_SPAN = 0.8
MAX_AREA = 0.25
MIN_SCORE = 0.20           # ниже — не элемент (фото может остаться «паузой»)
REL_SCORE = 0.35            # обычный кандидат — не слабее этой доли лучшего
MUST = 0.7                  # обособленность или цвет выше — берём независимо от REL_SCORE
MAX_OVERLAP = 0.15
SIMILAR_K = 0.7             # множитель за каждый уже взятый похожий элемент сверх SIMILAR_FREE
SIMILAR_FREE = 2            # ряд из трёх одинаковых (столбы, окна) — без штрафа
LAYER_W = 0.55              # шире этой доли кадра и от края — слой
SMALL_MAX = 0.06            # мелкий/средний элемент — меньше этой доли кадра
BAND_W = 0.5                # слой для длинных кусков — не уже половины кадра
BIG_MIN = 0.06              # крупный кусок подходящей формы — от этой доли кадра
BAND_DETAIL = 0.004         # слой с меньшей долей краёв (Canny) — однородный (небо, туман)
PROMINENT_K = 1.25          # бонус объектам 1–10% кадра
WHOLE_K = 0.75              # целое заменяет взятую часть, если не слабее этой доли
MAX_SIDE = 1280
# веса критериев в «ИЛИ»: q = 1 − Π(1 − w·f)
W_BASE, W_ORIENT, W_CONTRAST, W_COLOR, W_ALONE = 0.8, 0.8, 0.65, 0.8, 0.8


def load(photos, cdir, stem):
    src = next(p for p in Path(photos).iterdir() if p.stem == stem)
    img = Image.open(src).convert("RGB")
    k = MAX_SIDE / max(img.size)
    if k < 1:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    z = np.load(cdir / "cands.npz")
    H, W = z["shape"]
    masks = np.unpackbits(z["masks"], axis=-1)[..., :W].astype(bool)
    meta = json.loads((cdir / "cands.json").read_text(encoding="utf-8"))
    return np.array(img), masks, meta["cands"]


def geometry(m):
    """Ориентация вдоль осей кадра, прямоугольность, прямые края."""
    mu = m.astype(np.uint8)
    cnts, _ = cv2.findContours(mu, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)
    area = max(cv2.contourArea(c), 1.0)
    (_, _), (rw, rh), ang = cv2.minAreaRect(c)
    long_, short = max(rw, rh), max(1.0, min(rw, rh))
    axis = abs(math.cos(2 * math.radians(ang)))        # 1 — стороны вдоль осей (не зависит от соглашения углов)
    elong = float(np.clip((long_ / short - 1.4) / 1.6, 0, 1))
    rect_fill = min(1.0, area / max(rw * rh, 1.0))
    per = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.01 * per, True)
    straight = float(np.clip(1.0 - (len(approx) - 4) / 40.0, 0, 1))
    orient = axis ** 2 * elong * (0.5 + 0.5 * rect_fill)
    return dict(orient=orient, axis=axis, ratio=long_ / short, short=short, rect_fill=rect_fill, straight=straight)


def appearance(m, lab, lab_mean, edges_img, gray, diag):
    """Контраст, цвет и обособленность по кольцу вокруг элемента; детали внутри."""
    mu = m.astype(np.uint8)
    r = max(7, int(0.015 * diag))
    ring = (cv2.dilate(mu, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0) & ~m
    inner = cv2.erode(mu, np.ones((5, 5), np.uint8)) > 0
    core = inner if inner.sum() > 30 else m
    if ring.sum() < 20:
        return dict(contrast=0.0, color=0.0, alone=0.0, detail=0.0, L=0.0, ab=np.zeros(2))
    px_in = lab[core] * (0.6, 1, 1)            # яркость весит меньше цвета
    px_ring = lab[ring] * (0.6, 1, 1)
    mu_in, mu_ring = px_in.mean(0), px_ring.mean(0)
    L_in, ab_in = lab[core][:, 0].mean(), lab[core][:, 1:].mean(0)
    contrast = float(np.clip(abs(L_in - lab[ring][:, 0].mean()) / 255.0 * 3.5, 0, 1))
    chroma = float(np.hypot(*ab_in))
    dab = max(np.linalg.norm(ab_in - mu_ring[1:]), np.linalg.norm(ab_in - lab_mean[1:]))
    color = float(np.clip(chroma / 40.0, 0, 1) * np.clip(dab / 25.0, 0, 1))
    # отдельно стоящий: элемент и всё кольцо вокруг — разные «материалы» (разделимость средних с учётом разброса)
    spread = 0.5 * (np.sqrt(px_in.var(0).sum()) + np.sqrt(px_ring.var(0).sum())) + 4.0
    alone = float(np.clip((np.linalg.norm(mu_in - mu_ring) / spread - 0.6) / 1.2, 0, 1))
    detail = edges_img[core].mean()
    tex = gray[core].std() / 64.0
    return dict(contrast=contrast, color=color, alone=alone, detail=float(min(1.0, 4 * detail + 0.5 * tex)),
                L=float(L_in), ab=ab_in)


def similar(r, p):
    """Похожие элементы (ряд одинаковых окон): близки размер, пропорции и цвет."""
    return (max(r["area"], p["area"]) / max(min(r["area"], p["area"]), 1e-9) < 1.8
            and abs(math.log(r["ratio"] / p["ratio"])) < 0.4
            and np.linalg.norm(r["ab"] - p["ab"]) < 12 and abs(r["L"] - p["L"]) < 30)


def select(img, masks, cands):
    H, W = img.shape[:2]
    diag = math.hypot(W, H)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 1:] -= 128.0
    lab_mean = lab.reshape(-1, 3).mean(0)
    edges_img = (cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 150) > 0).astype(np.float32)
    rows = []
    for c in cands:
        m = masks[c["n"] - 1]
        x, y, w, h = c["bbox"]
        # касание краёв — и по маске, и по рамке с запасом 1% (углы земли/неба)
        mx, my = 0.01 * W, 0.01 * H
        box_edges = (x <= mx) + (y <= my) + (x + w >= W - mx) + (y + h >= H - my)
        edges = max(c["edges"], box_edges)
        if edges >= 2 or w > MAX_SPAN * W or h > MAX_SPAN * H or c["area"] > MAX_AREA:
            continue
        if w > LAYER_W * W and edges >= 1:            # полоса берега/поля от края — слой, не элемент
            continue
        g = geometry(m)
        # провода, кромки, наклонные полосы — не элементы; ровные карнизы и столбы — да
        if g["short"] < 8 or g["ratio"] > 12 or (g["ratio"] > 7 and g["axis"] < 0.85):
            continue
        if edges >= 1 and g["ratio"] > 3 and w > 0.3 * W:   # широкая полоса от края — берег, отражение
            continue
        if edges >= 1 and c["area"] > 0.08:           # большой кусок, срезанный краем кадра, — фон
            continue
        a = appearance(m, lab, lab_mean, edges_img, gray.astype(np.float32), diag)
        if g["ratio"] > 4.5 and g["rect_fill"] < 0.6 and a["alone"] < 0.5:   # клин берега (не силуэт острова)
            continue
        if edges == 1 and a["alone"] < 0.5 and a["color"] < 0.5:          # кусок у края без явной причины
            continue
        made = 0.6 * g["rect_fill"] + 0.4 * g["straight"]
        # общая оценка v1 (рукотворность × детали × обособленность SAM) — тоже основание взять
        base = float(np.clip(c["score"] * (0.5 + 0.7 * made) * (0.35 + 0.9 * a["detail"]) / 0.8, 0, 1))
        q = 1 - ((1 - W_BASE * base) * (1 - W_ORIENT * g["orient"]) * (1 - W_CONTRAST * a["contrast"])
                 * (1 - W_COLOR * a["color"]) * (1 - W_ALONE * a["alone"]))
        s = math.sqrt(max(c["score"], 0.0)) * q * (0.7 + 0.3 * a["detail"])
        if edges == 1:                                 # у края — чаще кусок фона, чем элемент
            s *= 0.5 if c["area"] > 0.02 else 0.75
        s *= 0.75 if c["area"] > 0.15 else (0.85 if c["area"] < 0.003 else 1.0)
        if 0.01 <= c["area"] <= 0.1:                   # заметный по размеру объект важнее мелких кусочков
            s *= PROMINENT_K
        rows.append(dict(n=c["n"], m=m, area=c["area"], s=float(s), **g, **a, made=made, base=base))
    # целое или части: части, если 2–4 сильных кандидата внутри покрывают ≥ 60% крупного целого
    for r in rows:
        if r["area"] < 0.04:
            continue
        kids = [q for q in rows if q is not r and q["area"] < 0.6 * r["area"]
                and (q["m"] & r["m"]).sum() > 0.85 * q["m"].sum()]
        kids = sorted(kids, key=lambda q: -q["s"])[:4]
        cover = np.zeros_like(r["m"])
        for q in kids:
            cover |= q["m"]
        if 2 <= len(kids) and (cover & r["m"]).sum() > 0.6 * r["m"].sum() \
                and np.mean([q["s"] for q in kids]) > 0.7 * r["s"]:
            r["s"] *= 0.5                       # целое уступает частям
            for q in kids:
                q["s"] *= 1.15
    rows.sort(key=lambda r: -r["s"])
    if not rows or rows[0]["s"] < MIN_SCORE:
        return [], rows
    best = rows[0]["s"]
    # жадно: на каждом шаге — лучший с поправкой на похожесть к уже взятым (разнообразие элементов)
    pool = [r for r in rows if r["s"] >= MIN_SCORE
            and (r["s"] >= REL_SCORE * best or r["alone"] > MUST or r["color"] > MUST)]
    picked = []
    while pool and len(picked) < MAX_ELEMENTS:
        for r in pool:
            r["adj"] = r["s"] * SIMILAR_K ** max(0, sum(similar(r, p) for p in picked) - SIMILAR_FREE)
        r = max(pool, key=lambda q: q["adj"])
        pool.remove(r)
        if r["adj"] < MIN_SCORE:
            break
        clash = [p for p in picked if (r["m"] & p["m"]).sum() / min(r["m"].sum(), p["m"].sum()) >= MAX_OVERLAP]
        if not clash:
            picked.append(r)
        elif (len(clash) == 1 and r["area"] < 0.1 and r["s"] > WHOLE_K * clash[0]["s"]
              and (r["m"] & clash[0]["m"]).sum() > 0.85 * clash[0]["m"].sum()):
            picked[picked.index(clash[0])] = r       # целое (верх маяка) вместо своей части (окна)
    return picked, rows


FEATURES_VERSION = 1


def _prep_maps(img):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 1:] -= 128.0
    edges_img = (cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 150) > 0).astype(np.float32)
    return gray, lab, lab.reshape(-1, 3).mean(0), edges_img


def mask_features(img, m, score, maps=None):
    """Признаки одной маски — те же, что видят правила отбора (для разметки и обучения модели)."""
    H, W = img.shape[:2]
    gray, lab, lab_mean, edges_img = maps or _prep_maps(img)
    ys, xs = np.nonzero(m)
    if len(xs) < 10:
        return None
    x, y, w, h = int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    mx, my = 0.01 * W, 0.01 * H
    box_edges = (x <= mx) + (y <= my) + (x + w >= W - mx) + (y + h >= H - my)
    g = geometry(m)
    a = appearance(m, lab, lab_mean, edges_img, gray.astype(np.float32), math.hypot(W, H))
    made = 0.6 * g["rect_fill"] + 0.4 * g["straight"]
    base = float(np.clip(score * (0.5 + 0.7 * made) * (0.35 + 0.9 * a["detail"]) / 0.8, 0, 1))
    return {"score": float(score), "area": float(m.mean()), "edges": int(box_edges), "fill": float(m.sum() / (w * h)),
            "made": float(made), "detail": a["detail"], "orient": float(g["orient"]), "axis": float(g["axis"]),
            "log_ratio": float(math.log(max(g["ratio"], 1.0))), "rect_fill": float(g["rect_fill"]),
            "straight": float(g["straight"]), "contrast": a["contrast"], "color": a["color"], "alone": a["alone"],
            "base": base, "cx": float((xs.mean() / W) - 0.5), "cy": float(ys.mean() / H),
            "w_rel": float(w / W), "h_rel": float(h / H)}


def cand_features(img, masks, cands):
    """{номер кандидата: признаки} для всех кандидатов фото (без фильтров правил)."""
    maps = _prep_maps(img)
    out = {}
    for c in cands:
        f = mask_features(img, masks[c["n"] - 1], c["score"], maps)
        if f:
            out[str(c["n"])] = f
    return out


def write_features(photos, cdir, stem):
    """features.json рядом с кандидатами (кеш признаков для редактора и обучения)."""
    img, masks, cands = load(photos, cdir, stem)
    feats = cand_features(img, masks, cands)
    (cdir / "features.json").write_text(json.dumps({"version": FEATURES_VERSION, "cands": feats}, ensure_ascii=False),
                                        encoding="utf-8")
    return feats


def big_pieces(img, masks, cands, picked, name):
    """Крупные элементы для пейзажей и фото без мелких/средних элементов (как в первом ч/б рендере):
    длинные горизонтальные куски из слоёв (берег, волнолом, вода, поле) — 35–60% ширины от края, которого
    касается слой, — и крупные компактные куски подходящей формы. Возвращает (picked, добавленные)."""
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    edges_img = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 150) > 0
    small = sum(p["area"] < SMALL_MAX for p in picked)
    bands, bigs = [], []
    for c in cands:
        x, y, w, h = c["bbox"]
        if c["area"] > 0.6:
            continue
        m = masks[c["n"] - 1]
        detail = float(edges_img[m].mean()) if m.any() else 0.0
        if w >= BAND_W * W and h <= 0.45 * H and w / max(h, 1) >= 2.0:
            if y <= 0.01 * H or detail < BAND_DETAIL:    # небо и однородные слои — нечего двигать
                continue
            bands.append((c, m, detail))
        elif BIG_MIN <= c["area"] <= 0.3 and w < 0.8 * W and h < 0.8 * H and c["edges"] < 2:
            bigs.append((c, m, detail))
    landscape = len(bands) >= 2 or sum(b[0]["area"] for b in bands) >= 0.35
    if not (landscape or small < 3):
        return picked, []
    want = 3 if small < 3 else 2
    rng = random.Random(zlib.crc32(name.encode("utf-8")))
    taken = np.zeros((H, W), bool)
    for p in picked:
        taken |= p["m"]
    out = []
    left_first = rng.random() < 0.5
    for c, m, detail in sorted(bands, key=lambda b: -(b[2] + 0.02) * b[0]["score"]):
        if len(out) >= want:
            break
        x, y, w, h = c["bbox"]
        at_l, at_r = x <= 0.01 * W, x + w >= 0.99 * W
        pw = min(rng.uniform(0.35, 0.6) * W, w)
        if at_l and at_r:
            anchor = "l" if left_first else "r"
            left_first = not left_first
        else:
            anchor = "l" if at_l else ("r" if at_r else "mid")
        x0 = x if anchor == "l" else (x + w - pw if anchor == "r" else x + rng.uniform(0, max(w - pw, 0)))
        box = [int(x0), int(y), int(x0 + pw), int(y + h)]
        seed = (zlib.crc32(name.encode("utf-8")) + c["n"]) & 0xFFFFFFFF
        piece = torn_piece(m, box, seed)                # не ровный кусок — «рваный край» (SPEC §3.1)
        area = float(piece.mean())
        if area < 0.012 or piece.any(1).sum() < 0.04 * H or (piece & taken).sum() > 0.15 * piece.sum():
            continue
        out.append(dict(n=c["n"], box=box, torn=seed, m=piece, area=area, s=float(c["score"]), big=True, made=0.0))
        taken |= piece
    if small < 3:                                       # крупные куски подходящей формы
        for c, m, detail in sorted(bigs, key=lambda b: -(b[2] + 0.02) * b[0]["score"]):
            if len(out) >= want:
                break
            if (m & taken).sum() > 0.15 * m.sum():
                continue
            out.append(dict(n=c["n"], box=None, m=m, area=float(c["area"]), s=float(c["score"]), big=True, made=0.0))
            taken |= m
    room = MAX_ELEMENTS - len(out)                      # места для крупных — за счёт самых слабых мелких
    picked = sorted(picked, key=lambda p: -p["s"])[:max(room, 0)]
    return picked, out


def model_proba(feats, model):
    """Вероятность «элемент» по модели (логистическая регрессия, smena/editor/train.py)."""
    names, mean, std, w = model["features"], model["mean"], model["std"], model["weights"]
    x = [(feats.get(n, 0.0) - mu) / (sd or 1.0) for n, mu, sd in zip(names, mean, std)]
    z = model["bias"] + sum(wi * xi for wi, xi in zip(w, x))
    return 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))


def model_select(masks, cands, feats, model):
    """Отбор моделью: кандидаты с вероятностью ≥ порога, по убыванию, без больших перекрытий, ≤ MAX_ELEMENTS."""
    thr = model.get("threshold", 0.5)
    rows = []
    for c in cands:
        f = feats.get(str(c["n"]))
        if not f:
            continue
        p = model_proba(f, model)
        if p >= thr:
            rows.append(dict(n=c["n"], m=masks[c["n"] - 1], area=c["area"], s=p, made=f["made"], model=True))
    rows.sort(key=lambda r: -r["s"])
    picked = []
    for r in rows:
        if len(picked) >= MAX_ELEMENTS:
            break
        if all((r["m"] & q["m"]).sum() / min(r["m"].sum(), q["m"].sum()) < MAX_OVERLAP for q in picked):
            picked.append(r)
    return picked


def why(p):
    """Почему взят — для отчёта."""
    if p.get("model"):
        return f"модель p={p['s']:.2f}"
    if p.get("big"):
        return "крупный" + ("-кусок" if p.get("box") else "")
    tags = []
    if p["orient"] > 0.4:
        tags.append("гор/верт")
    if p["contrast"] > 0.5:
        tags.append("контраст")
    if p["color"] > 0.4:
        tags.append("цвет")
    if p["alone"] > 0.5:
        tags.append("отдельно")
    if p["base"] > 0.6:
        tags.append("v1")
    return "+".join(tags) or "общий"


COLORS = [(255, 140, 40), (60, 200, 255), (120, 255, 120), (255, 90, 200), (255, 230, 60), (160, 120, 255),
          (255, 255, 255)]


def draw(img, picked, path):
    vis = (img * 0.4).astype(np.uint8)
    for i, p in enumerate(picked):
        col = np.array(COLORS[i % 7], np.uint8)
        vis[p["m"]] = (img[p["m"]] * 0.6 + col * 0.4).astype(np.uint8)
        cnts, _ = cv2.findContours(p["m"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cnts, -1, col.tolist(), 2)
    Image.fromarray(vis).save(path, quality=82)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos")
    ap.add_argument("cands")
    ap.add_argument("selection")
    ap.add_argument("--vis-name", default="sel.jpg", help="имя картинки отбора в папке кандидатов")
    ap.add_argument("--features", action="store_true", help="заодно записать features.json (признаки кандидатов)")
    ap.add_argument("--model", default=None, help="модель отбора (data/labels/model.json) вместо правил")
    a = ap.parse_args()
    model = json.loads(Path(a.model).read_text(encoding="utf-8")) if a.model else None
    sel = {}
    for cdir in sorted(Path(a.cands).iterdir()):
        if not (cdir / "cands.json").exists():
            continue
        if not any(p.stem == cdir.name for p in Path(a.photos).iterdir()):
            print(f"{cdir.name}: фото нет в папке — пропуск")
            continue
        img, masks, cands = load(a.photos, cdir, cdir.name)
        feats = None
        if a.features or model:
            feats = cand_features(img, masks, cands)
            (cdir / "features.json").write_text(json.dumps({"version": FEATURES_VERSION, "cands": feats},
                                                           ensure_ascii=False), encoding="utf-8")
        if model:
            picked = model_select(masks, cands, feats, model)
        else:
            picked, rows = select(img, masks, cands)
        picked, big = big_pieces(img, masks, cands, picked, cdir.name)
        picked = picked + big
        sel[cdir.name] = {"els": [{"n": p["n"], "box": p["box"], "torn": p["torn"]} if p.get("box") else [p["n"]]
                                  for p in picked],
                          "rect": [i + 1 for i, p in enumerate(picked) if p["made"] > 0.85],
                          "note": "auto v2: " + ", ".join(f"#{p['n']} s={p['s']:.2f} {why(p)}" for p in picked)}
        print(f"{cdir.name}: {len(picked)} элем. " + " ".join(f"#{p['n']}({p['s']:.2f} {why(p)})" for p in picked))
        draw(img, picked, cdir / a.vis_name)
    Path(a.selection).write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    print("записано:", a.selection, len(sel), "фото")


if __name__ == "__main__":
    main()
