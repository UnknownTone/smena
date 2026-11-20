"""Проверка сборки без окна: `SMENA --selftest` (так же — `python -m smena --selftest`).

Обязательное (ошибка → код 1): пакеты программы, ресурсы темы, демо-набор, ffmpeg.
Желательное (только предупреждение): OpenGL-контекст и шейдеры (на сборочных машинах без видеокарты его может
не быть), нейросети и модели (в лёгкой сборке их нет), корпус (OpenCV).
"""
import importlib
import importlib.util
import sys
import traceback

from smena import VERSION
from smena.runtime import FROZEN, IS_MAC, IS_WIN, ROOT


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    bad, warn = [], []

    def need(name, fn):
        try:
            r = fn()
            print(f"  ok   {name}" + (f": {r}" if r else ""))
        except Exception as e:
            bad.append(name)
            print(f"  FAIL {name}: {e!r}")
            traceback.print_exc(limit=2)

    def want(name, fn):
        try:
            r = fn()
            print(f"  ok   {name}" + (f": {r}" if r else ""))
        except Exception as e:
            warn.append(name)
            print(f"  warn {name}: {e!r}")

    plat = "Windows" if IS_WIN else "macOS" if IS_MAC else sys.platform
    print(f"SMENA {VERSION} selftest — {plat}, Python {sys.version.split()[0]}, {'сборка' if FROZEN else 'исходники'}")

    for mod in ("numpy", "PySide6.QtWidgets", "moderngl", "imageio_ffmpeg"):
        need(f"import {mod}", lambda m=mod: getattr(importlib.import_module(m), "__version__", "") or "")
    for mod in ("smena.app", "smena.ui.main_window", "smena.render.gl", "smena.scene.clock", "smena.audio.triggers"):
        need(f"import {mod}", lambda m=mod: importlib.import_module(m) and "")

    def theme():
        from smena.settings import THEMES_DIR
        d = THEMES_DIR / "smena_pipboy"
        for f in ("style.qss", "palette.json", "textures/eye.png", "fonts/PTMono-Regular.ttf"):
            if not (d / f).is_file():
                raise FileNotFoundError(f)
        return ""
    need("тема и шрифты", theme)

    def sample():
        from smena.scene.library import scan
        from smena.settings import SAMPLE_CACHE
        ents = scan(str(SAMPLE_CACHE), str(SAMPLE_CACHE))
        if not ents:
            raise RuntimeError(f"пусто: {SAMPLE_CACHE}")
        return f"{len(ents)} фото"
    need("демо-набор", sample)

    def presets():
        n = len(list((ROOT / "data" / "presets").glob("*.json")))
        if not n:
            raise FileNotFoundError("data/presets")
        return f"{n} пресета"
    need("заводские пресеты", presets)

    def ffmpeg():
        import subprocess
        from smena.audio.capture import ffmpeg_exe
        p = subprocess.run([ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=20)
        return p.stdout.split("\n")[0][:60]
    need("ffmpeg", ffmpeg)

    def gl():
        import moderngl
        from smena.render import gl as G
        ctx = moderngl.create_standalone_context(require=330)
        for vs, fs in ((G.VS_QUAD, G.FS_IMG), (G.VS_QUAD, G.FS_EL), (G.VS_BLIT, G.FS_BLIT), (G.VS_WARP, G.FS_WARP)):
            ctx.program(vertex_shader=vs, fragment_shader=fs)
        return ctx.info.get("GL_RENDERER", "")
    want("OpenGL 3.3 и шейдеры", gl)

    want("звук (soundcard)", lambda: importlib.import_module("soundcard") and "")
    want("корпус (OpenCV)", lambda: importlib.import_module("cv2").__version__)

    if importlib.util.find_spec("torch"):
        def nn():
            import torch
            dev = "cuda" if torch.cuda.is_available() else \
                "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
            importlib.import_module("sam2.build_sam")
            importlib.import_module("simple_lama_inpainting")
            return f"torch {torch.__version__}, {dev}"
        want("нейросети", nn)

        def models():
            sys.path.insert(0, str(ROOT / "tools" / "prep"))
            import prepare_photos as P
            miss = [p.name for p in (P.SAM_CKPT, P.LAMA_CKPT) if not p.is_file()]
            if miss:
                raise FileNotFoundError(", ".join(miss))
            return str(P.MODELS)
        want("модели SAM 2 и LaMa", models)
    else:
        print("  --   нейросети: не входят в эту сборку")

    print(f"итог: {'ОШИБКИ: ' + ', '.join(bad) if bad else 'ok'}" + (f"; предупреждения: {', '.join(warn)}" if warn else ""))
    return 1 if bad else 0
