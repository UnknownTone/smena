"""SMENA — подготовка фотографий (офлайн, один раз на набор).

Для каждого фото: SAM 2 → кандидаты масок → отбор 0–7 обособленных элементов →
композиционная линия → верх/низ, полярность, луч → LaMa (чистый фон) → кеш.

Запуск (в окружении .venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\prep\\prepare_photos.py ПАПКА_ФОТО ПАПКА_КЕША [--only 05.jpg] [--force]

Результат: КЕШ/<имя>/photo.json, background.png, el_1.png … (RGBA, вырез по bbox), preview.jpg.
"""
import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")     # macOS: недостающее в Metal — на процессоре
import torch  # noqa: E402
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MODELS = Path(os.environ.get("SMENA_MODELS") or ROOT / "models")    # в сборке — models внутри приложения
SAM_CKPT = MODELS / "sam2" / "sam2.1_hiera_base_plus.pt"
SAM_CFG = "configs/sam2.1/sam2.1_hiera_b+.yaml"
LAMA_CKPT = MODELS / "torch" / "hub" / "checkpoints" / "big-lama.pt"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_SIDE = 1280

# --- правила отбора элементов (подбираются по визуализатору) ---
MIN_AREA, MAX_AREA = 0.004, 0.35     # доля кадра
MAX_EDGES = 1                        # касается не более одного края кадра
MAX_ELEMENTS = 7
MAX_OVERLAP = 0.3                    # пересечение / меньшая площадь
REL_SCORE = 0.35                     # не хуже 35% от лучшего кандидата
ABS_SCORE = 0.05
MAX_SPAN = 0.8                       # рамка шире/выше 80% кадра — фон
EDGE_PENALTY = 0.6                   # касание края кадра — менее обособлен
BIG_AREA, BIG_PENALTY = 0.15, 0.5    # очень большие области — скорее фон


def pick_device(lama=False):
    """NVIDIA (CUDA) → Apple Silicon (Metal, только SAM: LaMa-TorchScript на Metal ненадёжна) → процессор."""
    if torch.cuda.is_available():
        return "cuda"
    if not lama and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_models(dev):
    from sam2.build_sam import build_sam2
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    from simple_lama_inpainting import SimpleLama
    sam = build_sam2(SAM_CFG, str(SAM_CKPT), device=dev)
    gen = SAM2AutomaticMaskGenerator(sam, points_per_side=32, points_per_batch=32, pred_iou_thresh=0.8,
                                     stability_score_thresh=0.92, min_mask_region_area=200)
    lama = SimpleLama.__new__(SimpleLama)        # torch.jit.load не открывает пути с кириллицей
    with open(LAMA_CKPT, "rb") as f:
        lama.model = torch.jit.load(io.BytesIO(f.read()), map_location=dev)
    lama.model.eval()
    lama.model.to(dev)
    lama.device = torch.device(dev)
    return gen, lama


def edges_touched(m, pad=3):
    return int(m[:pad].any()) + int(m[-pad:].any()) + int(m[:, :pad].any()) + int(m[:, -pad:].any())


def score_mask(m, gray, grad, pred_iou):
    """Обособленность: контраст внутри/снаружи границы + сила градиента на контуре."""
    k = np.ones((7, 7), np.uint8)
    mu = m.astype(np.uint8)
    ring = (cv2.dilate(mu, k) > 0) & ~m
    inner = m & ~(cv2.erode(mu, k) > 0)
    if ring.sum() < 20 or inner.sum() < 20:
        return 0.0
    contrast = abs(gray[inner].mean() - gray[ring].mean()) / 255.0
    edge = grad[inner | ring].mean() / (grad.mean() + 1e-6)
    return float(pred_iou * (0.6 * min(contrast * 4, 1.0) + 0.4 * min(edge / 3, 1.0)))


def pick_elements(masks, img):
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    cands = []
    for mk in masks:
        m = mk["segmentation"]
        a = m.sum() / (H * W)
        touched = edges_touched(m)
        x, y, w, h = mk["bbox"]
        if not (MIN_AREA <= a <= MAX_AREA) or touched > MAX_EDGES:
            continue
        if w > MAX_SPAN * W or h > MAX_SPAN * H:          # полосы во весь кадр — это фон
            continue
        s = score_mask(m, gray, grad, mk["predicted_iou"])
        s *= EDGE_PENALTY if touched else 1.0
        s *= BIG_PENALTY if a > BIG_AREA else 1.0
        cands.append((s, m, a))
    cands.sort(key=lambda c: -c[0])
    if not cands:
        return []
    best = cands[0][0]
    picked = []
    for s, m, a in cands:
        if s < ABS_SCORE or s < REL_SCORE * best:
            break
        if all((m & p).sum() / min(m.sum(), p.sum()) < MAX_OVERLAP for _, p, _ in picked):
            picked.append((s, m, a))
        if len(picked) == MAX_ELEMENTS:
            break
    return picked


def composition_line(img, elements):
    """Горизонт (сильная длинная горизонтальная граница) или центр масс элементов, иначе середина."""
    H = img.shape[0]
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 3)
    prof = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5)).mean(1)
    prof = np.convolve(prof, np.ones(9) / 9, "same")
    lo, hi = int(H * 0.2), int(H * 0.8)
    r = lo + int(np.argmax(prof[lo:hi]))
    strength = prof[r] / (np.median(prof[lo:hi]) + 1e-6)
    if strength > 2.5:
        return r / H, "horizon", float(strength)
    if elements:
        ys = [np.nonzero(m)[0].mean() / H for _, m, _ in elements]
        ws = [a for _, _, a in elements]
        return float(np.average(ys, weights=ws)), "mass", float(strength)
    return 0.5, "middle", float(strength)


def describe(m, line, W, H):
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    w, h = x1 - x0, y1 - y0
    above = (ys < line * H).mean()
    dists = {"left": x0, "right": W - x1, "top": y0, "bottom": H - y1}
    fill = m.sum() / (w * h)
    return {
        "bbox": [x0, y0, w, h],
        "centroid": [float(xs.mean() / W), float(ys.mean() / H)],
        "area": float(m.sum() / (W * H)),
        "half": "top" if above > 0.5 else "bottom",
        "polarity": "Y" if h > w else "X",
        "ray_edge": min(dists, key=dists.get),
        "shape": "rect" if fill > 0.85 else "mask",
    }


def process(path, out, gen, lama, dev):
    img = Image.open(path).convert("RGB")
    k = MAX_SIDE / max(img.size)
    if k < 1:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    arr = np.array(img)
    H, W = arr.shape[:2]
    with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
        masks = gen.generate(arr)
    picked = pick_elements(masks, arr)
    line, method, strength = composition_line(arr, picked)
    out.mkdir(parents=True, exist_ok=True)

    els, union = [], np.zeros((H, W), bool)
    for i, (s, m, a) in enumerate(sorted(picked, key=lambda p: -p[2]), 1):
        d = describe(m, line, W, H)
        x, y, w, h = d["bbox"]
        if d["shape"] == "rect":
            alpha = np.full((h, w), 255, np.uint8)
            union[y:y + h, x:x + w] = True
        else:
            mm = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8))
            alpha = (cv2.GaussianBlur(mm.astype(np.float32), (0, 0), 1.2) * 255).clip(0, 255).astype(np.uint8)[y:y + h, x:x + w]
            union |= mm > 0
        rgba = np.dstack([arr[y:y + h, x:x + w], alpha])
        Image.fromarray(rgba, "RGBA").save(out / f"el_{i}.png")
        els.append({"id": i, "file": f"el_{i}.png", "score": round(s, 3), **d})

    if els:
        hole = cv2.dilate(union.astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
        bg = lama(img, Image.fromarray(hole)).crop((0, 0, W, H))
    else:
        bg = img
    bg.save(out / "background.png")

    meta = {"source": path.name, "order": path.stem, "size": [W, H],
            "composition_line": {"y": round(line, 4), "method": method, "strength": round(strength, 2)},
            "bg_axis_hint": "horizontal" if method == "horizon" or W >= H else "vertical",
            "candidates": len(masks), "elements": els}
    (out / "photo.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    save_preview(arr, np.array(bg), picked, els, line, out / "preview.jpg")
    return meta


def save_preview(arr, bg, picked, els, line, path):
    """Оригинал с элементами (оранжевый — верх, голубой — низ), линией и лучами | чистый фон."""
    H, W = arr.shape[:2]
    vis = (arr * 0.45).astype(np.uint8)
    for (_, m, _), e in zip(sorted(picked, key=lambda p: -p[2]), els):
        col = np.array([255, 140, 40] if e["half"] == "top" else [60, 200, 255], np.uint8)
        vis[m] = (arr[m] * 0.5 + col * 0.5).astype(np.uint8)
        x, y, w, h = e["bbox"]
        cv2.rectangle(vis, (x, y), (x + w, y + h), col.tolist(), 2)
        cx, cy = x + w // 2, y + h // 2
        end = {"left": (0, cy), "right": (W - 1, cy), "top": (cx, 0), "bottom": (cx, H - 1)}[e["ray_edge"]]
        cv2.arrowedLine(vis, end, (cx, cy), (255, 255, 255), 2, tipLength=0.04)
        axis = ((cx, y + 4), (cx, y + h - 4)) if e["polarity"] == "Y" else ((x + 4, cy), (x + w - 4, cy))
        cv2.line(vis, axis[0], axis[1], (255, 255, 0), 1)
        cv2.putText(vis, f"{e['id']}{'T' if e['half'] == 'top' else 'B'}{e['polarity']}", (x + 4, y + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    ly = int(line * H)
    cv2.line(vis, (0, ly), (W, ly), (255, 60, 60), 2)
    Image.fromarray(np.concatenate([vis, bg], 1)).save(path, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos")
    ap.add_argument("cache")
    ap.add_argument("--only", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    dev = pick_device(lama=True)
    files = sorted(p for p in Path(a.photos).iterdir() if p.suffix.lower() in EXTS)
    if a.only:
        files = [p for p in files if p.name == a.only]
    cache = Path(a.cache)
    t0 = time.time()
    gen, lama = load_models(dev)
    print(f"модели загружены за {time.time() - t0:.1f} с ({dev})", flush=True)
    for i, p in enumerate(files, 1):
        out = cache / p.stem
        if (out / "photo.json").exists() and not a.force:
            print(f"[{i}/{len(files)}] {p.name}: уже готово")
            continue
        t = time.time()
        meta = process(p, out, gen, lama, dev)
        els = meta["elements"]
        top = sum(e["half"] == "top" for e in els)
        print(f"[{i}/{len(files)}] {p.name}: {len(els)} элем. (верх {top}, низ {len(els) - top}), "
              f"линия {meta['composition_line']['y']:.2f} ({meta['composition_line']['method']}), "
              f"{time.time() - t:.1f} с", flush=True)
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    sys.exit(main())
