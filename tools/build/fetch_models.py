r"""Скачать модели SAM 2.1 base+ и LaMa в models/ (для сборки с нейросетями и для новой машины разработки).
Уже скачанные с верной суммой пропускаются.

Запуск: python tools/build/fetch_models.py [папка models]
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = [
    ("sam2/sam2.1_hiera_base_plus.pt",
     "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt",
     "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5"),
    ("torch/hub/checkpoints/big-lama.pt",
     "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt",
     "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"),
]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "models"
    for rel, url, digest in MODELS:
        dst = out / rel
        if dst.is_file() and sha256(dst) == digest:
            print("есть:", rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        print("скачиваю:", url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "SMENA-build/1.0"})
        with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        if sha256(tmp) != digest:
            tmp.unlink()
            sys.exit(f"контрольная сумма не сошлась: {rel}")
        tmp.replace(dst)
        print("готово:", rel)


if __name__ == "__main__":
    main()
