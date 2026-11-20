r"""Упаковка готовой сборки PyInstaller в файл для раздачи → build/out/.
  Windows: Inno Setup → SMENA_Setup-<версия>.exe   (ISCC из Program Files или из PATH)
  macOS:   SMENA-<версия>-mac-arm64.dmg (SMENA.app + ярлык «Программы», hdiutil)

Запуск: python tools/build/package.py [папка dist]   (по умолчанию build/dist)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from smena import VERSION  # noqa: E402

OUT = ROOT / "build" / "out"


def iscc():
    for p in (shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
              r"C:\Program Files\Inno Setup 6\ISCC.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")):
        if p and Path(p).is_file():
            return p
    sys.exit("Inno Setup 6 (ISCC.exe) не найден")


def windows(dist):
    src = dist / "SMENA"
    if not (src / "SMENA.exe").is_file():
        sys.exit(f"нет сборки: {src}")
    subprocess.run([iscc(), f"/DAppVersion={VERSION}", f"/DSrcDir={src}", f"/DOutDir={OUT}",
                    str(ROOT / "packaging" / "smena.iss")], check=True)


def mac(dist):
    app = dist / "SMENA.app"
    if not app.is_dir():
        sys.exit(f"нет сборки: {app}")
    arch = os.uname().machine
    dmg = OUT / f"SMENA-{VERSION}-mac-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as t:
        stage = Path(t) / "SMENA"
        stage.mkdir()
        subprocess.run(["ditto", str(app), str(stage / "SMENA.app")], check=True)   # ditto сохраняет подпись
        (stage / "Applications").symlink_to("/Applications")
        shutil.copy(ROOT / "packaging" / "mac" / "README — first launch.txt", stage)
        subprocess.run(["hdiutil", "create", "-volname", f"SMENA {VERSION}", "-srcfolder", str(stage),
                        "-ov", "-format", "UDZO", "-fs", "HFS+", str(dmg)], check=True)
    print("готово:", dmg)


def main():
    dist = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "dist"
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        windows(dist)
    elif sys.platform == "darwin":
        mac(dist)
    else:
        sys.exit("упаковка — только Windows и macOS")
    for f in sorted(OUT.iterdir()):
        print(f"{f.name}: {f.stat().st_size / 2**20:.0f} МБ")


if __name__ == "__main__":
    main()
