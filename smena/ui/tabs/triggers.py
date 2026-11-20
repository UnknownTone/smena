"""Вкладка ТРИГГЕРЫ: таблица 20 триггеров — признак звука, подробно что делает со сценой, ВКЛ / СИЛА / ЧУВСТВ.

Таблица хранится отдельно от пресетов — файлами в кеше набора фото: <кеш>\\triggers\\*.json
(у каждого набора фото свои настройки триггеров). SAVE наверху пишет её в выбранный здесь файл.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from smena.triggers_table import DETAILS, TRIGGERS

BAD = '\\/:*?"<>|'


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(True)
    return w


class TriggersTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.p = win, win.params
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(lbl("ТРИГГЕРЫ · ТАБЛИЦА", "title"))
        self.cfg = QComboBox()
        self.cfg.setToolTip("файл таблицы триггеров в кеше набора фото — выбор загружает его")
        self.cfg.activated.connect(lambda _: self.load_cfg())
        row.addWidget(self.cfg, 1)
        for text, fn, tip in (("СОХР.", self.save_cfg, "сохранить таблицу в выбранный файл"),
                              ("СОХР. КАК…", self.save_cfg_as, "сохранить таблицу в новый файл кеша набора")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        info = lbl("Каждый триггер слушает свой признак звука и делает своё действие со сценой. СИЛА — величина "
                   "действия, ЧУВСТВ. — порог срабатывания (больше — срабатывает чаще). Галочка — вкл / выкл.", "dim")
        info.setStyleSheet("font-size: 11px;")
        v.addWidget(info)
        self.cfg_dir = lbl("", "dim")
        self.cfg_dir.setStyleSheet("font-size: 10px;")
        v.addWidget(self.cfg_dir)

        self.table = QTableWidget(len(TRIGGERS), 5)
        self.table.setHorizontalHeaderLabels(["ВКЛ  №", "ТРИГГЕР · ПРИЗНАК ЗВУКА", "ЧТО ДЕЛАЕТ СО СЦЕНОЙ",
                                              "СИЛА", "ЧУВСТВ."])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.table.setWordWrap(True)
        hh = self.table.horizontalHeader()
        for c, mode in enumerate((QHeaderView.ResizeToContents, QHeaderView.Fixed, QHeaderView.Stretch,
                                  QHeaderView.Fixed, QHeaderView.Fixed)):
            hh.setSectionResizeMode(c, mode)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 70)
        self.rows = {}
        for r, t in enumerate(TRIGGERS):
            tip = f"№{t.n} {t.short} — {t.name} ({t.kind})\n{DETAILS[t.n]}"
            on = QCheckBox(f"{t.n:02d}")
            on.setToolTip(f"ВКЛ / ВЫКЛ триггер №{t.n} {t.short}")
            on.toggled.connect(lambda x, n=t.n: self.p.set(f"t{n}.on", x))
            self.table.setCellWidget(r, 0, on)
            for c, text in ((1, f"{t.short} · {t.kind}\n{t.name}"), (2, DETAILS[t.n])):
                it = QTableWidgetItem(text)
                it.setToolTip(tip)
                self.table.setItem(r, c, it)
            spins = []
            for c, key, what in ((3, "gain", f"СИЛА — величина действия: {DETAILS[t.n]}"),
                                 (4, "sens", "ЧУВСТВ. — порог срабатывания; больше — срабатывает чаще")):
                it = QTableWidgetItem("")
                it.setTextAlignment(Qt.AlignCenter)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable)
                it.setData(Qt.UserRole, (t.n, key))
                it.setToolTip(f"№{t.n} {what}" + chr(10) + "двойной клик — ввести число 0…200")
                self.table.setItem(r, c, it)
                spins.append(it)
            self.rows[t.n] = (on, *spins)
        self.table.resizeRowsToContents()
        self.table.itemChanged.connect(self._edited)
        v.addWidget(self.table, 1)
        self.p.changed.connect(self._param)
        for t in TRIGGERS:
            self._row(t.n)
        self.refresh_cfg()

    # ------------------------------------------------------------- файлы таблиц
    def cache_dir(self):
        return self.win.settings["cache_dir"]

    def refresh_cfg(self):
        names = self.p.trigger_names(self.cache_dir())
        cur = self.win.settings.v.get("trigger_config")
        self.cfg.clear()
        self.cfg.addItems(names)
        if cur in names:
            self.cfg.setCurrentIndex(names.index(cur))
        self.cfg_dir.setText(f"{self.p.trigger_dir(self.cache_dir())}" + ("" if names else " · файлов пока нет"))

    def load_cfg(self, name=None):
        n = name or self.cfg.currentText()
        if not n:
            return
        try:
            self.p.load_triggers(self.cache_dir(), n)
        except Exception as e:
            QMessageBox.warning(self, "Таблица триггеров", str(e))
            return
        self.win.settings["trigger_config"] = n
        self.win.settings.save()
        self.win.engine.log_event(f"таблица триггеров: {n}")

    def save_cfg(self):
        n = self.cfg.currentText()
        if not n:
            return self.save_cfg_as()
        self.p.save_triggers(self.cache_dir(), n)
        self.win.settings["trigger_config"] = n
        self.win.settings.save()
        self.refresh_cfg()
        return n

    def save_cfg_as(self):
        n, ok = QInputDialog.getText(self, "Таблица триггеров", "Имя файла таблицы (в кеше набора):")
        n = n.strip()
        if not ok:
            return None
        if not n or any(c in n for c in BAD):
            QMessageBox.warning(self, "Таблица триггеров", f"Имя пустое или содержит {BAD}")
            return None
        self.p.save_triggers(self.cache_dir(), n)
        self.win.settings["trigger_config"] = n
        self.win.settings.save()
        self.refresh_cfg()
        return n

    # ------------------------------------------------------------- значения
    def _edited(self, it):
        d = it.data(Qt.UserRole)
        if not d:
            return
        n, key = d
        try:
            x = float(it.text().replace("%", "").strip())
        except ValueError:
            self._row(n)
            return
        self.p.set(f"t{n}.{key}", float(min(max(round(x), 0), 200)))
        self._row(n)

    def _row(self, n):
        on, gain, sens = self.rows[n]
        on.blockSignals(True)
        on.setChecked(bool(self.p[f"t{n}.on"]))
        on.blockSignals(False)
        self.table.blockSignals(True)
        for it, k in ((gain, "gain"), (sens, "sens")):
            it.setText(f"{self.p[f't{n}.{k}']:.0f} %")
        self.table.blockSignals(False)
        for c in (1, 2):
            self.table.item(n - 1, c).setForeground(Qt.gray if not self.p[f"t{n}.on"] else
                                                    self.table.palette().text())

    def _param(self, k):
        if k.startswith("t") and "." in k and k[1:k.index(".")].isdigit():
            self._row(int(k[1:k.index(".")]))
