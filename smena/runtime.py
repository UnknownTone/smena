"""Платформа и способ запуска: Windows / macOS / Linux, разработка (venv) или сборка PyInstaller.

Подготовка фото (SAM 2, LaMa), SAM-сервер редактора и корпус «жестянка» работают отдельными процессами:
  разработка — python окружения подготовки (.venv-prep) + скрипт;
  сборка     — то же приложение с ключом `--run-script <скрипт> …` (интерпретатор и пакеты уже внутри).
"""
import importlib.util
import os
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))

PKG_DIR = Path(__file__).resolve().parent
# корень ресурсов: в сборке — папка с данными приложения, при разработке — vj/
ROOT = Path(getattr(sys, "_MEIPASS", PKG_DIR.parent))


def data_dir():
    """Настройки, пресеты, журнал, кеш корпуса."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA", Path.home())) / "SMENA"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "SMENA"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "SMENA"


def default_prep_python():
    """python окружения подготовки при разработке (в сборке не нужен)."""
    if FROZEN:
        return sys.executable
    venv = ROOT / ".venv-prep"
    return str(venv / "Scripts" / "python.exe") if IS_WIN else str(venv / "bin" / "python")


def external_python(python):
    """Сборка без нейросетей (Windows), но на вкладке ФОТО указан свой python с ними (например .venv-prep)."""
    if not (FROZEN and python and Path(python).is_file()):
        return False
    try:
        return Path(python).resolve() != Path(sys.executable).resolve()
    except OSError:
        return False


def prep_available(python):
    """Есть ли чем запускать тяжёлые скрипты (torch)."""
    if FROZEN:
        return importlib.util.find_spec("torch") is not None or external_python(python)
    return bool(python) and Path(python).is_file()


def shell_available(python):
    """Корпус рисует numpy + OpenCV: в сборке они внутри, при разработке — в .venv-prep."""
    if FROZEN:
        return importlib.util.find_spec("cv2") is not None or external_python(python)
    return bool(python) and Path(python).is_file()


def script_cmd(python, script, args=(), light=False):
    """(программа, аргументы) для QProcess / subprocess. Сборка: тем же приложением, если в нём есть нужное
    (light — скрипту хватает numpy + OpenCV, как корпусу), иначе — внешним python (окружение с нейросетями)."""
    args = [str(a) for a in args]
    inside = importlib.util.find_spec("cv2" if light else "torch") is not None
    if FROZEN and (inside or not external_python(python)):
        return sys.executable, ["--run-script", str(script), *args]
    return str(python), ["-u", "-X", "utf8", str(script), *args]


def script_env(env):
    """Переменные окружения для дочернего процесса (QProcessEnvironment)."""
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")
    env.insert("PYTORCH_ENABLE_MPS_FALLBACK", "1")       # macOS: недостающие операции Metal — на процессоре
    return env


def run_script(argv):
    """Режим сборки: `SMENA --run-script <скрипт> …` — выполнить скрипт тем же интерпретатором."""
    import runpy
    script = Path(argv[0])
    if sys.stdout is None:                              # оконная сборка без каналов — вывод в никуда
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    sys.argv = [str(script), *argv[1:]]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name="__main__")
