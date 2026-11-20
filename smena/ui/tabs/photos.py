"""Вкладка ФОТО: папка фото и кеша, список фото со статусом кеша, миниатюра,
подготовка фото (SAM 2 → отбор → LaMa во внешнем процессе .venv-prep) с прогрессом и журналом."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from smena.prep.bridge import PrepRunner, check_paths
from smena.scene import library


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


def mmss(sec):
    return "—" if sec < 0 else f"{int(sec // 60)}:{int(sec % 60):02d}"


class PhotosTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.entries = []
        self.runner = PrepRunner(self)
        self.runner.line.connect(self._log)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._prep_done)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        g = QGridLayout()
        g.setHorizontalSpacing(6)
        self.edits = {}
        for row, (name, key, tip) in enumerate((("ФОТО", "photos_dir", "Папка с фото"),
                                                ("КЕШ", "cache_dir", "Папка кеша"))):
            g.addWidget(lbl(name, "dim"), row, 0)
            e = QLineEdit(win.settings[key])
            e.editingFinished.connect(lambda k=key, e=e: self._set_path(k, e.text()))
            g.addWidget(e, row, 1)
            b = QPushButton("Выбрать…")
            b.clicked.connect(lambda _=False, k=key, t=tip: self._choose_dir(k, t))
            g.addWidget(b, row, 2)
            self.edits[key] = e
        v.addLayout(g)

        self.summary = lbl("", "dim")
        v.addWidget(self.summary)
        row = QHBoxLayout()
        row.addStretch()
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.rescan)
        row.addWidget(self.refresh_btn)
        self.prep = QPushButton("Подготовить фото")
        self.prep.setToolTip("SAM 2 → отбор → LaMa для фото без кеша (готовые пропускаются)")
        self.prep.clicked.connect(self.start_prep)
        row.addWidget(self.prep)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.runner.stop)
        row.addWidget(self.stop_btn)
        ed = QPushButton("Редактор элементов")
        ed.setToolTip("ручной выбор элементов кликами (SAM 2 по точке) и разметка для обучения модели")
        ed.clicked.connect(win.open_editor)
        row.addWidget(ed)
        v.addLayout(row)

        split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["№", "фото", "верх", "низ", "кеш"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(self._select)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(1, hdr.ResizeMode.Stretch)
        for c, w in ((0, 40), (2, 52), (3, 52), (4, 90)):
            self.tree.setColumnWidth(c, w)
        split.addWidget(self.tree)

        info = QWidget()
        hb = QHBoxLayout(info)
        hb.setContentsMargins(0, 0, 0, 0)
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumSize(180, 110)
        hb.addWidget(self.thumb, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        hb.addWidget(self.details, 1)
        split.addWidget(info)

        prep = QWidget()
        pv = QVBoxLayout(prep)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)
        pg = QGridLayout()
        pg.setHorizontalSpacing(6)
        self.paths = {}
        for r, (name, key, is_file) in enumerate((("PYTHON", "prep_python", True), ("СКРИПТЫ", "prep_scripts", False))):
            pg.addWidget(lbl(name, "dim"), r, 0)
            e = QLineEdit(win.settings[key])
            e.setToolTip("python окружения подготовки (.venv-prep)" if is_file else "папка tools\\prep")
            e.editingFinished.connect(lambda k=key, e=e: self._set_prep_path(k, e.text()))
            pg.addWidget(e, r, 1)
            b = QPushButton("Выбрать…")
            b.clicked.connect(lambda _=False, k=key, f=is_file: self._choose_prep(k, f))
            pg.addWidget(b, r, 2)
            self.paths[key] = e
        pv.addLayout(pg)
        self.path_state = lbl("", "dim")
        self.path_state.setWordWrap(True)
        pv.addWidget(self.path_state)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(True)
        self.bar.setFormat("")
        pv.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("журнал подготовки фото")
        pv.addWidget(self.log, 1)
        split.addWidget(prep)
        split.setSizes([330, 100, 170])
        v.addWidget(split, 1)
        self._check_paths()
        self.rescan()

    # ----------------------------------------------------------------- папки
    def _choose_dir(self, key, title):
        d = QFileDialog.getExistingDirectory(self, title, self.edits[key].text())
        if d:
            self.edits[key].setText(str(Path(d)))
            self._set_path(key, self.edits[key].text())

    def _set_path(self, key, text):
        s = self.win.settings
        if s[key] == text:
            return
        if self.runner.running:
            QMessageBox.information(self, "Фото", "Идёт подготовка фото — сначала дождитесь её или нажмите «Стоп».")
            self.edits[key].setText(s[key])
            return
        s[key] = text
        # другая папка фото: если текущий кеш не про неё — свой кеш рядом с фото
        if key == "photos_dir":
            if not any(e.ready and e.source for e in library.scan(text, s["cache_dir"])):
                s["cache_dir"] = str(Path(text) / "_smena_cache")
                self.edits["cache_dir"].setText(s["cache_dir"])
        s.save()
        self.rescan()

    def _choose_prep(self, key, is_file):
        cur = self.paths[key].text()
        if is_file:
            f, _ = QFileDialog.getOpenFileName(self, "python окружения подготовки", cur, "python (python*)")
        else:
            f = QFileDialog.getExistingDirectory(self, "Папка скриптов tools\\prep", cur)
        if f:
            self.paths[key].setText(str(Path(f)))
            self._set_prep_path(key, self.paths[key].text())

    def _set_prep_path(self, key, text):
        self.win.settings[key] = text
        self.win.settings.save()
        self._check_paths()

    def _check_paths(self):
        s = self.win.settings
        probs = check_paths(s["prep_python"], s["prep_scripts"])
        self.path_state.setProperty("role", "warn" if probs else "dim")
        self.path_state.setText("; ".join(probs) if probs else "окружение подготовки найдено")
        self.path_state.style().polish(self.path_state)
        return not probs

    # ----------------------------------------------------------------- список
    def rescan(self):
        s = self.win.settings
        self.entries = library.scan(s["photos_dir"], s["cache_dir"])
        cur = self.tree.currentItem()
        cur_name = self.entries[cur.data(0, Qt.UserRole)].name if cur and cur.data(0, Qt.UserRole) is not None \
            and cur.data(0, Qt.UserRole) < len(self.entries) else None
        self.tree.clear()
        for i, e in enumerate(self.entries, 1):
            it = QTreeWidgetItem([f"{i:02d}", e.name, str(e.n_top) if e.ready else "–",
                                  str(e.n_bottom) if e.ready else "–", e.status])
            it.setData(0, Qt.UserRole, i - 1)
            if e.error:
                it.setToolTip(4, e.error)
            self.tree.addTopLevelItem(it)
        if self.entries:
            idx = next((i for i, e in enumerate(self.entries) if e.name == cur_name), 0)
            self.tree.setCurrentItem(self.tree.topLevelItem(idx))
        ready = sum(e.ready for e in self.entries)
        no_src = all(e.source is None for e in self.entries) and self.entries
        missing = len(self.missing())
        self.summary.setText(f"{len(self.entries)} фото · с кешем {ready} · без кеша {len(self.entries) - ready}"
                             + (" · только кеш (исходных фото нет)" if no_src else ""))
        self.prep.setText(f"Подготовить фото ({missing})" if missing else "Подготовить фото")
        self.win.library_changed(self.entries)

    def missing(self):
        """Фото без готового кеша (есть исходный файл)."""
        return [e for e in self.entries if e.source and not e.ready]

    # ------------------------------------------------------------ подготовка
    def start_prep(self):
        if self.runner.running:
            return
        if not self._check_paths():
            QMessageBox.warning(self, "Подготовка фото", self.path_state.text())
            return
        miss = self.missing()
        if not miss:
            self._log("все фото уже подготовлены")
            return
        s = self.win.settings
        self.log.clear()
        for w in (self.prep, self.refresh_btn, *self.edits.values(), *self.paths.values()):
            w.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.win.engine.log_event(f"подготовка фото: {len(miss)} шт.")
        from smena.editor.train import MODEL_PATH
        model = MODEL_PATH if s.v.get("prep_use_model") and MODEL_PATH.is_file() else None
        if model:
            self._log(f"отбор — моделью по разметке ({MODEL_PATH.name})")
        self.runner.start(s["prep_python"], s["prep_scripts"], s["photos_dir"], s["cache_dir"], miss, model=model)

    def _log(self, text):
        self.log.appendPlainText(text)

    def _progress(self, step, i, n, frac, eta):
        self.bar.setValue(int(frac * 1000))
        self.bar.setFormat(f"{step}: {i} / {n} · {frac * 100:.0f}% · осталось ~{mmss(eta)}")

    def _prep_done(self, ok, text):
        for w in (self.prep, self.refresh_btn, *self.edits.values(), *self.paths.values()):
            w.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if not ok:
            self.bar.setFormat(text)
        self.win.engine.log_event(f"подготовка фото: {text}")
        self.rescan()                 # новые фото сразу идут в показ

    # ------------------------------------------------------------- карточка
    def _select(self, cur, _prev):
        if not cur:
            return
        e = self.entries[cur.data(0, Qt.UserRole)]
        pm = QPixmap(str(e.preview)) if e.preview else QPixmap()
        if not pm.isNull():
            pm = pm.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb.setPixmap(pm)
        lines = [f"{e.name}", f"источник: {e.source or '—'}", f"кеш: {e.cache or '—'}"]
        if e.meta:
            cl = e.meta.get("composition_line", {})
            lines.append(f"размер: {e.meta.get('size')} · линия: {cl.get('y', cl.get('y_left', '?'))} "
                         f"({cl.get('method', '?')})")
            for el in e.meta.get("elements", []):
                lines.append(f"  эл.{el['id']}: {el.get('half')} · {el.get('polarity')} · луч {el.get('ray_edge')} "
                             f"· {el.get('shape')} · {100 * el.get('area', 0):.1f}%")
        if e.error:
            lines.append(f"ОШИБКА: {e.error}")
        self.details.setPlainText("\n".join(lines))
