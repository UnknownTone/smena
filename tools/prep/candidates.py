"""SMENA — этап 1 качественной подготовки: кандидаты элементов для ручного/экспертного отбора.

Для каждого фото: SAM 2 (с дополнительным проходом по фрагментам — мелкие детали) → до 24 разных кандидатов,
отсортированных по обособленности → кеш масок + картинка с пронумерованными контурами.

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\prep\\candidates.py ПАПКА_ФОТО ПАПКА_КАНДИДАТОВ [--only имя.jpg …]

Результат: ПАПКА/<имя>/cands.npz (маски), cands.json (метрики), cands.jpg (контуры с номерами).
Дальше: выбор номеров в selection.json → tools/prep/build_elements.py.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_photos import pick_device, SAM_CFG, SAM_CKPT, EXTS, MAX_SIDE, edges_touched, score_mask   # noqa: E402

MIN_AREA, MAX_AREA = 0.002, 0.6
MAX_CANDS = 48                     # до 32 элементов на фото (SPEC §3.1) — кандидатов с запасом
DEDUP_IOU = 0.75
COLORS = [(255, 80, 80), (80, 220, 120), (90, 160, 255), (255, 200, 60), (230, 90, 255), (60, 230, 230),
          (255, 140, 40), (180, 255, 90), (255, 110, 180), (140, 120, 255), (255, 255, 255), (120, 200, 160)]


def load_gen(dev):
    from sam2.build_sam import build_sam2
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    sam = build_sam2(SAM_CFG, str(SAM_CKPT), device=dev)
    return SAM2AutomaticMaskGenerator(sam, points_per_side=32, points_per_batch=32, pred_iou_thresh=0.78,
                                      stability_score_thresh=0.9, crop_n_layers=1, crop_n_points_downscale_factor=2,
                                      min_mask_region_area=150)


def candidates(masks, img):
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    rows = []
    for mk in masks:
        m = mk["segmentation"]
        a = m.sum() / (H * W)
        if not (MIN_AREA <= a <= MAX_AREA):
            continue
        x, y, w, h = mk["bbox"]
        s = score_mask(m, gray, grad, mk["predicted_iou"])
        rows.append(dict(m=m, area=float(a), score=float(s), edges=edges_touched(m),
                         fill=float(m.sum() / max(1.0, w * h)), bbox=[int(x), int(y), int(w), int(h)]))
    rows.sort(key=lambda r: -r["score"])
    kept = []
    for r in rows:
        if all((r["m"] & k["m"]).sum() / (r["m"] | k["m"]).sum() < DEDUP_IOU for k in kept):
            kept.append(r)
        if len(kept) == MAX_CANDS:
            break
    kept.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))    # номера — сверху вниз, слева направо
    return kept


def draw(img, cands, path):
    H, W = img.shape[:2]
    base = (img * 0.55).astype(np.uint8)
    over = base.copy()
    for i, c in enumerate(cands):
        col = COLORS[i % len(COLORS)]
        over[c["m"]] = (0.55 * over[c["m"]] + 0.45 * np.array(col)).astype(np.uint8)
    for i, c in enumerate(cands):
        col = COLORS[i % len(COLORS)]
        cnts, _ = cv2.findContours(c["m"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(over, cnts, -1, col, 2)
    im = Image.fromarray(np.concatenate([img, over], 1))
    d = ImageDraw.Draw(im)
    font = None
    for f in ("C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(f, 26)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    for i, c in enumerate(cands):
        ys, xs = np.nonzero(c["m"])
        cx, cy = W + int(np.median(xs)), int(np.median(ys))
        d.text((cx, cy), str(i + 1), font=font, fill=COLORS[i % len(COLORS)], stroke_width=3,
               stroke_fill=(0, 0, 0), anchor="mm")
    im.thumbnail((2400, 2400))
    im.save(path, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos")
    ap.add_argument("out")
    ap.add_argument("--only", nargs="*", default=None, help="имена файлов (с расширением) — только они")
    a = ap.parse_args()
    dev = pick_device()
    files = sorted(p for p in Path(a.photos).iterdir()
                   if p.suffix.lower() in EXTS and not p.name.startswith("._"))   # «._*» — файлы macOS
    if a.only is not None:
        files = [p for p in files if p.name in set(a.only)]
    t0 = time.time()
    gen = load_gen(dev)
    for i, p in enumerate(files, 1):
        out = Path(a.out) / p.stem
        if (out / "cands.json").exists():
            print(f"[{i}/{len(files)}] {p.name}: уже готово"); continue
        t = time.time()
        img = Image.open(p).convert("RGB")
        k = MAX_SIDE / max(img.size)
        if k < 1:
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
        arr = np.array(img)
        with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
            masks = gen.generate(arr)
        cands = candidates(masks, arr)
        out.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out / "cands.npz", masks=np.packbits(np.stack([c["m"] for c in cands]) if cands
                                                                 else np.zeros((0, *arr.shape[:2]), bool), axis=-1),
                            shape=np.array(arr.shape[:2]))
        meta = {"source": p.name, "size": [arr.shape[1], arr.shape[0]],
                "cands": [{k_: v for k_, v in c.items() if k_ != "m"} | {"n": j + 1} for j, c in enumerate(cands)]}
        (out / "cands.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        draw(arr, cands, out / "cands.jpg")
        print(f"[{i}/{len(files)}] {p.name}: {len(masks)} масок → {len(cands)} кандидатов, {time.time() - t:.1f} с", flush=True)
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
