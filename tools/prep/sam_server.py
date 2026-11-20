"""SMENA — SAM-сервер для редактора элементов (06_LABELING_TOOL.yaml, решение 5).

Фоновый процесс окружения .venv-prep: SAM 2 загружен один раз и держится в памяти; программа SMENA (без PyTorch)
шлёт команды строками JSON в stdin и читает ответы строками JSON из stdout (служебный вывод библиотек — в stderr).

Команды ({"id": …, "cmd": …}):
  ping                                     → {"ok": true}
  image     {"path"}                       → фото как у кандидатов (длинная сторона ≤ 1280), эмбеддинг SAM; {"w", "h"}
  predict   {"points": [[x, y, 1|0], …]}   → маска по точкам (1 — плюс, 0 — минус); {"rle", "w", "h", "score", "bbox"}
  features  {"photos", "cdir", "stem"}     → признаки всех кандидатов фото → <cdir>/features.json; {"n"}
  mask_features {"rle", "w", "h", "score"} → признаки одной маски на текущем фото; {"features"}
  quit
rle — base64 от np.packbits(маска, axis=-1).

Запуск: .venv-prep\\Scripts\\python.exe -u tools\\prep\\sam_server.py
"""
import base64
import json
import sys
import traceback
from pathlib import Path

import numpy as np

OUT = sys.stdout
sys.stdout = sys.stderr                # print() библиотек — в stderr, stdout только для протокола

sys.path.insert(0, str(Path(__file__).resolve().parent))
import torch   # noqa: E402
from PIL import Image   # noqa: E402

from auto_select import mask_features, write_features   # noqa: E402
from prepare_photos import MAX_SIDE, SAM_CFG, SAM_CKPT, pick_device   # noqa: E402


def send(obj):
    OUT.write(json.dumps(obj, ensure_ascii=False) + "\n")
    OUT.flush()


def pack(m):
    return base64.b64encode(np.packbits(m.astype(bool), axis=-1).tobytes()).decode("ascii")


def unpack(rle, w, h):
    b = np.frombuffer(base64.b64decode(rle), np.uint8)
    return np.unpackbits(b.reshape(h, -1), axis=-1)[:, :w].astype(bool)


def load_photo(path):
    img = Image.open(path).convert("RGB")
    k = MAX_SIDE / max(img.size)
    if k < 1:
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    return np.array(img)


def main():
    dev = pick_device()
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    pred = SAM2ImagePredictor(build_sam2(SAM_CFG, str(SAM_CKPT), device=dev))
    cur = {"img": None, "path": None}
    send({"ready": True, "device": dev})
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        rid, cmd = req.get("id"), req.get("cmd")
        try:
            if cmd == "ping":
                send({"id": rid, "ok": True})
            elif cmd == "image":
                if req["path"] != cur["path"]:
                    img = load_photo(req["path"])
                    with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
                        pred.set_image(img)
                    cur.update(img=img, path=req["path"])
                h, w = cur["img"].shape[:2]
                send({"id": rid, "w": w, "h": h})
            elif cmd == "predict":
                pts = np.array([[p[0], p[1]] for p in req["points"]], np.float32)
                lab = np.array([int(p[2]) for p in req["points"]], np.int32)
                with torch.inference_mode(), torch.autocast(dev, dtype=torch.bfloat16, enabled=dev == "cuda"):
                    masks, scores, _ = pred.predict(point_coords=pts, point_labels=lab, multimask_output=False)
                m = masks[0] > 0.5
                ys, xs = np.nonzero(m)
                bbox = [int(xs.min()), int(ys.min()), int(np.ptp(xs) + 1), int(np.ptp(ys) + 1)] if len(xs) else [0, 0, 0, 0]
                h, w = m.shape
                send({"id": rid, "rle": pack(m), "w": w, "h": h, "score": float(scores[0]), "bbox": bbox})
            elif cmd == "features":
                feats = write_features(req["photos"], Path(req["cdir"]), req["stem"])
                send({"id": rid, "n": len(feats)})
            elif cmd == "mask_features":
                m = unpack(req["rle"], req["w"], req["h"])
                send({"id": rid, "features": mask_features(cur["img"], m, req.get("score", 0.5))})
            elif cmd == "quit":
                send({"id": rid, "ok": True})
                break
            else:
                send({"id": rid, "error": f"неизвестная команда {cmd}"})
        except Exception as e:
            traceback.print_exc()
            send({"id": rid, "error": repr(e)})


if __name__ == "__main__":
    main()
