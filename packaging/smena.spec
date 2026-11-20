# -*- mode: python ; coding: utf-8 -*-
# Сборка SMENA (PyInstaller 6, onedir).
#   Windows:  pyinstaller packaging/smena.spec            → dist/SMENA/SMENA.exe   (лёгкая, без нейросетей)
#   macOS:    SMENA_NN=1 pyinstaller packaging/smena.spec → dist/SMENA.app          (с SAM 2 и LaMa внутри)
# Скрипты подготовки и корпуса лежат внутри как данные и запускаются тем же приложением: SMENA --run-script …
import ast
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from smena import VERSION  # noqa: E402

NN = os.environ.get("SMENA_NN") == "1"
MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"

datas = [
    (str(ROOT / "smena" / "ui" / "theme"), "smena/ui/theme"),
    (str(ROOT / "data" / "sample_cache"), "data/sample_cache"),
    (str(ROOT / "data" / "presets"), "data/presets"),
    (str(ROOT / "data" / "labels" / "model.json"), "data/labels"),
    (str(ROOT / "docs" / "manual"), "docs/manual"),
    (str(ROOT / "tools" / "render" / "tin_shell.py"), "tools/render"),
    (str(ROOT / "packaging" / "icons" / "smena.png"), "packaging/icons"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "CREDITS.md"), "."),
]
for f in (ROOT / "tools" / "prep").glob("*.py"):
    datas.append((str(f), "tools/prep"))
datas += collect_data_files("soundcard")          # заголовки cffi
datas += collect_data_files("imageio_ffmpeg")      # ffmpeg

hidden = ["glcontext", "smena.selftest", "cv2"] + collect_submodules("glcontext")


def script_imports(files):
    """Модули, которые импортируют скрипты-данные (PyInstaller их не анализирует)."""
    local = {f.stem for f in (ROOT / "tools" / "prep").glob("*.py")}
    out = set()
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                out.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                out.add(node.module.split(".")[0])
    return sorted(out - local)


scripts = [ROOT / "tools" / "render" / "tin_shell.py"]
if NN:
    scripts += list((ROOT / "tools" / "prep").glob("*.py"))
    hidden += collect_submodules("sam2") + collect_submodules("simple_lama_inpainting")
    hidden += collect_submodules("hydra") + collect_submodules("omegaconf") + collect_submodules("iopath")
    datas += collect_data_files("sam2") + collect_data_files("hydra")        # конфиги моделей (yaml)
    datas.append((str(ROOT / "models"), "models"))
else:
    # без нейросетей: из скриптов подготовки нужен только отбор (auto_select, torn) — его зовёт редактор
    scripts += [ROOT / "tools" / "prep" / "auto_select.py", ROOT / "tools" / "prep" / "torn.py"]
hidden += [m for m in script_imports(scripts) if NN or m not in ("torch", "sam2", "simple_lama_inpainting")]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"] + ([] if NN else ["torch", "torchvision"]),
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SMENA",
    console=False,
    icon=str(ROOT / "packaging" / "icons" / ("smena.icns" if MAC else "smena.ico")),
    version=str(ROOT / "packaging" / "version_info.txt") if WIN else None,
    upx=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SMENA", upx=False)

if MAC:
    app = BUNDLE(
        coll,
        name="SMENA.app",
        icon=str(ROOT / "packaging" / "icons" / "smena.icns"),
        bundle_identifier="app.smena.vj",
        version=VERSION,
        info_plist={
            "CFBundleName": "SMENA",
            "CFBundleDisplayName": "SMENA",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "SMENA слушает звук (вход карты или BlackHole), чтобы визуал шёл в такт музыке.",
            "LSApplicationCategoryType": "public.app-category.music",
        },
    )
