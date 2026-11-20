"""Вкладка ПРЕСЕТЫ: пресеты (все ручки, кроме каналов триггеров — они на вкладке ТРИГГЕРЫ).

Пресет — %APPDATA%\\SMENA\\presets\\*.json; таблица триггеров (ВКЛ / СИЛА / ЧУВСТВ. 20 каналов) — отдельные файлы
в кеше набора фото: <кеш>\\triggers\\*.json. Так пресет «под человека» и таблица «под набор» не мешают друг другу.
"""
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
                               QWidget)

from smena.settings import PRESET_DIR

BAD = '\\/:*?"<>|'


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(True)
    return w


def bad_name(n):
    return not n or any(c in n for c in BAD)


class PresetsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.p = win.params
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(10)

        # ---------- пресеты
        left = QVBoxLayout()
        left.addWidget(lbl("ПРЕСЕТЫ", "title"))
        self.list = QListWidget()
        self.list.setToolTip("пресеты: двойной клик — загрузить")
        self.list.itemDoubleClicked.connect(lambda _: self.load())
        left.addWidget(self.list, 1)
        for text, fn, tip in (("ЗАГРУЗИТЬ", self.load, "загрузить выбранный пресет"),
                              ("СОХРАНИТЬ", self.save, "сохранить все ручки в выбранный пресет (то же — SAVE наверху)"),
                              ("СОХР. КАК…", self.save_as, "сохранить под новым именем"),
                              ("УДАЛИТЬ", self.delete, "удалить выбранный пресет"),
                              ("ПО УМОЛЧАНИЮ", self.p.reset, "все ручки пресета — по умолчанию (таблица триггеров "
                                                             "не меняется)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            left.addWidget(b)
        info = lbl(f"папка: {PRESET_DIR}", "dim")
        info.setStyleSheet("font-size: 10px;")
        left.addWidget(info)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(240)
        h.addWidget(lw)

        side = QVBoxLayout()
        side.addWidget(lbl("Пресет — все ручки, фейдеры, LFO, провода и переходы (кроме таблицы триггеров — "
                           "она на вкладке ТРИГГЕРЫ, у каждого набора фото своя). SAVE наверху пишет в текущий "
                           "пресет. Заводские: slow — мягко и неспешно, medium — середина, trance — максимум "
                           "движения и модуляций.", "dim"))
        side.addStretch()
        h.addLayout(side, 1)

        self.list.currentTextChanged.connect(lambda n: setattr(self, "_sel", n))
        self._sel = ""
        self.refresh()

    # ------------------------------------------------------------- пресеты
    def refresh(self):
        cur = self.win.settings["last_preset"]
        self.list.clear()
        names = self.p.preset_names()
        self.list.addItems(names)
        if cur in names:
            self.list.setCurrentRow(names.index(cur))

    def _remember(self, n):
        self.win.settings["last_preset"] = n
        self.win.settings.save()

    def current(self):
        it = self.list.currentItem()
        return it.text() if it else None

    def load(self):
        n = self.current()
        if n:
            self.p.load_preset(n)
            self._remember(n)
            self.win.engine.log_event(f"пресет: {n}")

    def save(self, name=None):
        n = name or self.p.current or self.win.settings["last_preset"] or self.current()
        if not n:
            return self.save_as()
        self.p.save_preset(n)
        self._remember(n)
        self.refresh()
        return n

    def save_as(self):
        n, ok = QInputDialog.getText(self, "Пресет", "Имя пресета:")
        n = n.strip()
        if not ok:
            return None
        if bad_name(n):
            QMessageBox.warning(self, "Пресет", f"Имя пустое или содержит {BAD}")
            return None
        return self.save(n)

    def delete(self):
        n = self.current()
        if n and QMessageBox.question(self, "Пресет", f"Удалить пресет «{n}»?") == QMessageBox.Yes:
            self.p.delete_preset(n)
            self.refresh()

