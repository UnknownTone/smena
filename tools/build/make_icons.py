r"""Иконки приложения из глаза темы: тёмная плашка (скруглённый квадрат, как у иконок macOS) + серая окантовка
+ глаз по центру. Пишет packaging/icons/smena.png (1024), smena.ico (Windows), smena.icns (macOS).

Запуск: python tools/build/make_icons.py   (нужен только Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
EYE = ROOT / "smena" / "ui" / "theme" / "smena_pipboy" / "textures" / "eye.png"
OUT = ROOT / "packaging" / "icons"
S = 1024


def plate():
    """Плашка 1024: поле 824×824 по сетке Apple, радиус ~22%, тень, градиент, двойная окантовка."""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    box, r = (100, 100, 924, 924), 186
    sh = Image.new("L", (S, S), 0)
    ImageDraw.Draw(sh).rounded_rectangle((100, 118, 924, 942), r, fill=150)
    im.putalpha(sh.filter(ImageFilter.GaussianBlur(18)))
    im = Image.composite(Image.new("RGBA", (S, S), (0, 0, 0, 255)), Image.new("RGBA", (S, S), (0, 0, 0, 0)),
                         im.getchannel("A"))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):                                    # сверху чуть светлее — как матовая жесть
        k = y / S
        c = int(38 - 22 * k)
        gd.line([(0, y), (S, y)], fill=(c, c + 2, c + 3, 255))
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    im.alpha_composite(Image.composite(grad, Image.new("RGBA", (S, S), (0, 0, 0, 0)), m))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(box, r, outline=(120, 124, 128, 255), width=10)               # серая окантовка (С1-83)
    d.rounded_rectangle((116, 116, 908, 908), r - 16, outline=(10, 10, 10, 255), width=6)
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    im = plate()
    eye = Image.open(EYE).convert("RGBA")
    w = 700
    eye = eye.resize((w, round(eye.height * w / eye.width)), Image.LANCZOS)
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))                                   # жёлтое свечение зрачка
    ImageDraw.Draw(glow).ellipse((S / 2 - 190, S / 2 - 190, S / 2 + 190, S / 2 + 190), fill=(255, 230, 40, 70))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    im.alpha_composite(eye, ((S - eye.width) // 2, (S - eye.height) // 2))
    im.save(OUT / "smena.png")
    im.save(OUT / "smena.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.save(OUT / "smena.icns")
    print("готово:", OUT)


if __name__ == "__main__":
    main()
