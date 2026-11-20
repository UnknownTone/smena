"""Точка входа SMENA: формат GL и общий контекст → QApplication → тема → звук → главное окно.

Порядок важен: QApplication создаётся раньше импорта soundcard, чтобы главный поток остался в STA
(иначе ломаются диалоги Qt); soundcard грузится лениво (smena/audio/capture.py).
"""
import logging
import logging.handlers
import os
import sys

from PySide6.QtCore import Qt, QTimer
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


def main():
    setup_logging()
    sys.excepthook = excepthook
    log.info("SMENA %s, Python %s", VERSION, sys.version.split()[0])

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

    from smena.audio.capture import AudioEngine
    from smena.audio.triggers import Triggers
    from smena.params import Params
    from smena.ui.main_window import MainWindow
    from smena.ui.theme import THEME

    settings = Settings()
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
