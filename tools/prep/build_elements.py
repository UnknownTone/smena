"""SMENA — этап 2 качественной подготовки: элементы из выбранных кандидатов → LaMa → кеш для рендера.

selection.json:
    {"<имя фото без расширения>": {"els": [[3], [5, 6], [9], {"n": 4, "box": [0, 300, 640, 420]}],
                                   # элемент = объединение кандидатов или кандидат, обрезанный рамкой
                                   "rect": [2],                  # номера элементов (с 1) — прямоугольником
                                   "note": "..."}, ...}
    "els": [] — фото без элементов («пауза»).
    Ключи ручного выбора (редактор элементов, 06_LABELING_TOOL.yaml): "extra": ["extra_1.png"] — маски SAM по кликам
    (PNG в папке кандидатов фото), "half": {"1": "top"}, "polarity": {"2": "X"}, "line_y": 0.62, "pause": true.
    Номера элементов — по порядку: els, затем extra.

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\prep\\build_elements.py ПАПКА_ФОТО ПАПКА_КАНДИДАТОВ selection.json ПАПКА_КЕША
        [--only имя …]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_photos import pick_device, LAMA_CKPT, MAX_SIDE, composition_line, describe, save_preview   # noqa: E402
from torn import torn_piece   # noqa: E402


def load_lama(dev):
    """Только LaMa (без SAM 2): сборка из редактора идёт рядом с SAM-сервером — VRAM 4 ГБ на двоих."""
    import io
    from simple_lama_inpainting import SimpleLama
    lama = SimpleLama.__new__(SimpleLama)        # torch.jit.load не открывает пути с кириллицей
    with open(LAMA_CKPT, "rb") as f:
        lama.model = torch.jit.load(io.BytesIO(f.read()), map_location=dev)
    lama.model.eval()
    lama.model.to(dev)
    lama.device = torch.device(dev)
    return lama


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photos")
    ap.add_argument("cands")
    ap.add_argument("selection")
    ap.add_argument("cache")
    ap.add_argument("--only", nargs="*", default=None, help="имена фото без расширения — только они")
    a = ap.parse_args()
    sel = json.loads(Path(a.selection).read_text(encoding="utf-8"))
    if a.only is not None:
        sel = {k: v for k, v in sel.items() if k in set(a.only)}
    dev = pick_device(lama=True)
    lama = load_lama(dev)
    t0 = time.time()
    for i, (stem, s) in enumerate(sel.items(), 1):
        src = next(p for p in Path(a.photos).iterdir() if p.stem == stem)
        cd = Path(a.cands) / stem
        z = np.load(cd / "cands.npz")
        Hh, Ww = z["shape"]
        masks = np.unpackbits(z["masks"], axis=-1)[..., :Ww].astype(bool)
        img = Image.open(src).convert("RGB")
        k = MAX_SIDE / max(img.size)
        if k < 1:
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
        arr = np.array(img)
        H, W = arr.shape[:2]
        picked = []
        groups = [] if s.get("pause") else s["els"]       # пауза — фото без элементов
        for group in groups:
            m = np.zeros((H, W), bool)
            if isinstance(group, dict):          # крупный кусок: кандидат, обрезанный рамкой
                if "torn" in group:              # с «рваным краем» (SPEC §3.1) — та же маска, что в отборе
                    m = torn_piece(masks[group["n"] - 1], group["box"], group["torn"])
                else:
                    x0, y0, x1, y1 = group["box"]
                    m[y0:y1, x0:x1] = masks[group["n"] - 1][y0:y1, x0:x1]
            else:
                for n in group:
                    m |= masks[n - 1]
            picked.append((1.0, m, m.sum() / (H * W)))
        sources = list(groups)
        for name in ([] if s.get("pause") else s.get("extra", [])):   # маски SAM по кликам редактора
            em = np.array(Image.open(cd / name).convert("L").resize((W, H), Image.NEAREST)) > 127
            picked.append((1.0, em, em.sum() / (H * W)))
            sources.append(name)
        line, method, strength = composition_line(arr, picked)
        if s.get("line_y") is not None:                    # линия, поправленная вручную
            line, method = float(s["line_y"]), "manual"
        out = Path(a.cache) / stem
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("el_*.png"):
            old.unlink()
        els, union = [], np.zeros((H, W), bool)
        for j, (_, m, _) in enumerate(picked, 1):
            d = describe(m, line, W, H)
            if j in s.get("rect", []):
                d["shape"] = "rect"
            if str(j) in s.get("half", {}):                # ручные переопределения редактора
                d["half"] = s["half"][str(j)]
            if str(j) in s.get("polarity", {}):
                d["polarity"] = s["polarity"][str(j)]
            x, y, w, h = d["bbox"]
            if d["shape"] == "rect":
                alpha = np.full((h, w), 255, np.uint8)
                union[y:y + h, x:x + w] = True
            else:
                mm = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8))
                alpha = (cv2.GaussianBlur(mm.astype(np.float32), (0, 0), 1.2) * 255).clip(0, 255).astype(np.uint8)[y:y + h, x:x + w]
                union |= mm > 0
            Image.fromarray(np.dstack([arr[y:y + h, x:x + w], alpha]), "RGBA").save(out / f"el_{j}.png")
            els.append({"id": j, "file": f"el_{j}.png", "from": sources[j - 1], **d})
        if els:
            hole = cv2.dilate(union.astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
            bg = lama(img, Image.fromarray(hole)).crop((0, 0, W, H))
        else:
            bg = img
        bg.save(out / "background.png")
        meta = {"source": src.name, "order": stem, "size": [W, H],
                "composition_line": {"y": round(line, 4), "method": method, "strength": round(strength, 2)},
                "bg_axis_hint": "horizontal" if method == "horizon" or W >= H else "vertical",
                "note": s.get("note", ""), "elements": els}
        (out / "photo.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        save_preview(arr, np.array(bg), picked, els, line, out / "preview.jpg")
        top = sum(e["half"] == "top" for e in els)
        print(f"[{i}/{len(sel)}] {stem}: {len(els)} элем. (верх {top}, низ {len(els) - top})", flush=True)
    print(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
