"""Точка входа SMENA: формат GL и общий контекст → QApplication → тема → звук → главное окно.

Порядок важен: QApplication создаётся раньше импорта soundcard, чтобы главный поток остался в STA
(иначе ломаются диалоги Qt); soundcard грузится лениво (smena/audio/capture.py).
"""
import logging
import logging.handlers
import os
import sys

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox

from smena import VERSION
from smena.runtime import ROOT
from smena.settings import LOG_DIR, Settings

log = logging.getLogger("smena")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(LOG_DIR / "smena.log", maxBytes=2_000_000, backupCount=3,
                                              encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    if sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


def excepthook(tp, val, tb):
    log.critical("необработанная ошибка", exc_info=(tp, val, tb))
    if QApplication.instance():
        QMessageBox.critical(None, "SMENA — ошибка", f"{tp.__name__}: {val}\n\nПодробности — в журнале:\n{LOG_DIR}")


def fit_screen(app, settings):
    """Первый запуск: если окно (не меньше MIN_W×MIN_H) не помещается на экран — подобрать масштаб, запомнить
    и перезапуститься с ним (QT_SCALE_FACTOR задаётся только до создания QApplication). True — ушли в перезапуск."""
    from smena.ui.main_window import MIN_H, MIN_W
    scr = app.primaryScreen()
    if scr is None:
        return False
    av = scr.availableGeometry()
    need = min(av.width() / MIN_W, (av.height() - 32) / MIN_H)   # 32 — заголовок окна
    scale = 1.0 if need >= 1.0 else max(0.6, int(need * 100) / 100)
    log.info("экран %d×%d, масштаб интерфейса: %.2f", av.width(), av.height(), scale)
    if os.environ.get("SMENA_SMOKE"):                  # пробный запуск — ничего не запоминать
        return False
    settings["ui_scale"] = scale
    settings.save()
    if scale == 1.0:
        return False
    args = sys.argv[1:] if getattr(sys, "frozen", False) else ["-m", "smena", *sys.argv[1:]]
    if QProcess.startDetached(sys.executable, args):
        return True
    return False


def main():
    setup_logging()
    sys.excepthook = excepthook
    log.info("SMENA %s, Python %s", VERSION, sys.version.split()[0])

    settings = Settings()
    scale = settings["ui_scale"]
    if scale and abs(float(scale) - 1.0) > 0.01 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{float(scale):.2f}"   # интерфейс мельче — для экранов меньше макета
        log.info("масштаб интерфейса: %s", os.environ["QT_SCALE_FACTOR"])

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)   # один контекст на превью и окно вывода
    app = QApplication(sys.argv)
    app.setApplicationName("SMENA")
    app.setApplicationVersion(VERSION)
    icon = ROOT / "packaging" / "icons" / "smena.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    if scale is None and fit_screen(app, settings):
        return                                             # перезапуск с подобранным масштабом

    from smena.audio.capture import AudioEngine
    from smena.audio.triggers import Triggers
    from smena.params import Params
    from smena.ui.main_window import MainWindow
    from smena.ui.theme import THEME

    THEME.load(app, settings["theme"])
    params = Params()
    Params.install_factory()                               # заводские пресеты slow / medium / trance
    params.set("sync_ms", float(settings["sync_ms"] or 0.0))
    if settings["last_preset"] in params.preset_names():
        params.load_preset(settings["last_preset"])

    engine = AudioEngine()
    engine.triggers = Triggers(engine, params)
    devs = [d[0] for d in engine.list_devices()]
    if settings["audio_device"] not in devs:
        settings["audio_device"] = None
    engine.start(settings["audio_device"])

    win = MainWindow(app, settings, engine, params)
    smoke = os.environ.get("SMENA_SMOKE")                 # проверка сборки: окно за краем экрана, закрыть через N с
    if smoke:
        win.move(-2400, 40)
    win.show()
    if smoke:
        shot = os.environ.get("SMENA_SHOT")              # снимок окна перед закрытием (README, проверка сборки)
        if shot:
            win.resize(1920, 1040)
            QTimer.singleShot(3000, win.grab)            # за краем экрана окно само не рисуется — корпус заказать
            QTimer.singleShot(int(float(smoke) * 1000) - 400, lambda: win.grab().save(shot))
        QTimer.singleShot(int(float(smoke) * 1000), win.close)
    code = app.exec()
    engine.stop()
    if not smoke:
        settings.save()
    sys.exit(code)
