"""Загрузка темы: ui/theme/<имя>/palette.json + style.qss + шрифты + текстуры.

Рисованные виджеты берут цвета только отсюда (`THEME.c("screen_fg")`), QSS — подстановкой @токенов.
Сменить дизайн = положить новую папку темы и выбрать её в настройках; Ctrl+R перезагружает тему на лету.
"""
import json
import logging
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase

from smena.settings import THEMES_DIR

log = logging.getLogger("smena.theme")


class Theme(QObject):
    reloaded = Signal()

    def __init__(self):
        super().__init__()
        self.name = ""
        self.dir = None
        self.colors = {}
        self.fonts = {}
        self.effects = {}
        self.textures = {}
        self._font_ids = []

    def c(self, role, alpha=None):
        col = QColor(self.colors.get(role, "#ff00ff"))
        if alpha is not None:
            col.setAlphaF(alpha)
        return col

    def font(self, role, px, bold=False):
        f = QFont(self.fonts.get(role, "Arial"))
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def load(self, app, name):
        d = THEMES_DIR / name
        if not (d / "palette.json").is_file():
            log.warning("тема %s не найдена, беру smena_pipboy", name)
            d = THEMES_DIR / "smena_pipboy"
        pal = json.loads((d / "palette.json").read_text(encoding="utf-8"))
        self.name, self.dir = d.name, d
        self.colors = pal.get("colors", {})
        self.fonts = pal.get("fonts", {})
        self.effects = pal.get("effects", {})
        self.textures = pal.get("textures", {})

        # шрифты — из байтов: пути с кириллицей не всем загрузчикам по силам
        for i in self._font_ids:
            QFontDatabase.removeApplicationFont(i)
        self._font_ids = []
        for rel in pal.get("font_files", []):
            fid = QFontDatabase.addApplicationFontFromData((d / rel).read_bytes())
            if fid < 0:
                log.warning("шрифт не загружен: %s", rel)
            self._font_ids.append(fid)

        tokens = {f"font_{k}": v for k, v in self.fonts.items()}
        tokens.update({f"tex_{k}": v for k, v in self.textures.items()})
        tokens.update(self.colors)
        tokens["dir"] = d.as_posix()
        qss = (d / "style.qss").read_text(encoding="utf-8")
        qss = re.sub(r"@([a-z_]+)", lambda m: tokens.get(m.group(1), m.group(0)), qss)
        app.setStyleSheet(qss)
        app.setFont(self.font("engrave", 13))
        self.reloaded.emit()
        log.info("тема: %s", pal.get("name", d.name))


THEME = Theme()
