"""Редактор элементов (06_LABELING_TOOL.yaml): ручной выбор элементов кликами + разметка для обучения.

Окно программы SMENA (кнопка на вкладке ФОТО). SAM 2 по точке и LaMa — фоновые процессы .venv-prep
(решения 5–6). Всё сохраняется сразу после каждого действия (selection_manual.json, labels.jsonl).

Мышь: клик по элементу — убрать; по кандидату — сделать элементом; в пустое место — маска SAM 2 по точке;
Shift+клик — добавить точку к последней маске SAM, Alt+клик — отрицательная точка; Ctrl+клик — выделить элемент.
Клавиши: ← → / PgUp PgDn — фото; Space — проверено и дальше; G — объединить; Del — убрать выделенные;
H — верх/низ; R — маска/прямоугольник; X — полярность; P — пауза; B — собрать фото; M — предложить моделью;
Ctrl+Z / Ctrl+Y — отмена / повтор; C / E / L — кандидаты / элементы / линия.

0.1.2 — панель инструментов над холстом: поворот фото ⟲ ⟳, отражение ⇋, выравнивание горизонта (меняют исходное
фото — оригинал копируется в «_SMENA_оригиналы», элементы фото пересобираются подготовкой); элемент от руки,
по точкам, ластик; готовые фигуры ▭ ◯ △ ▬ ▮ ◔. Нарисованное становится элементом-маской, как клик SAM.
"""
import json
import logging
import shutil
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSlider,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from smena.editor import train
from smena.editor.canvas import PALETTE, Canvas, boundary
from smena.editor.data import (GENRES, MAX_ELEMENTS, MAX_OVERLAP, PhotoData, Selections, SetPaths, element_cands,
                               elements_of)
from smena.editor.sam_client import SamClient, pack, unpack
from smena.runtime import script_cmd, script_env

log = logging.getLogger("smena.editor")
STATUS_ICON = {"checked": "✓", "edited": "✎", "auto": "○", "pause": "—"}


def lbl(text="", role=None):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(True)
    return w


# --------------------------------------------------------------- операции над выбором
def remap(entry, order):
    """Перенумеровать переопределения (rect/half/polarity) после перестройки: order — старые номера (1..) или None."""
    old_rect = set(entry.get("rect", []))
    old_half, old_pol = entry.get("half", {}), entry.get("polarity", {})
    entry["rect"], entry["half"], entry["polarity"] = [], {}, {}
    for new, old in enumerate(order, 1):
        if old is None:
            continue
        if old in old_rect:
            entry["rect"].append(new)
        if str(old) in old_half:
            entry["half"][str(new)] = old_half[str(old)]
        if str(old) in old_pol:
            entry["polarity"][str(new)] = old_pol[str(old)]


def rebuild(entry, items):
    """items — [(вид, источник, старый номер или None)] в новом порядке; els — кандидаты, extra — клики SAM."""
    els = [(s, o) for k, s, o in items if k == "cand"]
    ext = [(s, o) for k, s, o in items if k == "extra"]
    entry["els"] = [s for s, _ in els]
    entry["extra"] = [s for s, _ in ext]
    remap(entry, [o for _, o in els] + [o for _, o in ext])


def current_items(entry):
    return [(k, s, i) for i, (k, s) in enumerate(elements_of(entry), 1)]


class EditorWindow(QMainWindow):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.settings = main.settings
        self.setWindowTitle("SMENA — редактор элементов")
        self.resize(1500, 900)
        self.paths = None
        self.sel = None
        self.pd = None
        self.stem = None
        self.photo_cache = {}
        self.mask_cache = {}
        self.active_extra = None       # последняя маска SAM — к ней Shift/Alt-точки
        self.extra_points = []
        self.extra_feats = {}
        self.build_proc = None
        self.show_cands = self.show_els = True
        self.opacity = 0.45
        self.sam = SamClient(self.settings["prep_python"], self.settings["prep_scripts"], self)
        self.sam.state.connect(self._sam_state)
        self._ui()
        self._shortcuts()
        self.load_set()

    # ------------------------------------------------------------------ интерфейс
    def _ui(self):
        body = QWidget()
        body.setObjectName("Body")
        body.setAttribute(Qt.WA_StyledBackground)
        self.setCentralWidget(body)
        h = QHBoxLayout(body)
        h.setContentsMargins(10, 10, 10, 10)
        h.setSpacing(10)

        left = QFrame()
        left.setObjectName("PipScreen")
        lv = QVBoxLayout(left)
        lv.addWidget(lbl("ФОТО", "title"))
        self.set_info = lbl("", "dim")
        lv.addWidget(self.set_info)
        self.photos = QListWidget()
        self.photos.currentRowChanged.connect(self.open_photo)
        lv.addWidget(self.photos, 1)
        self.progress = lbl("", "dim")
        lv.addWidget(self.progress)
        left.setFixedWidth(330)
        h.addWidget(left)

        self.canvas = Canvas()
        self.canvas.clicked.connect(self.on_click)
        self.canvas.line_moved.connect(self.on_line)
        self.canvas.shape_done.connect(self.on_shape)
        self.canvas.erase_done.connect(self.on_erase)
        self.canvas.horizon_done.connect(lambda a: self.transform_photo("angle", a))
        center = QVBoxLayout()
        center.setSpacing(6)
        center.addLayout(self._tools())
        center.addWidget(self.canvas, 1)
        h.addLayout(center, 1)

        right = QFrame()
        right.setObjectName("PipScreen")
        rv = QVBoxLayout(right)
        self.title = lbl("", "title")
        rv.addWidget(self.title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["№", "откуда", "часть", "форма", "ось"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self.refresh_overlay)
        for c, w in ((0, 34), (1, 120), (2, 54), (3, 64), (4, 34)):
            self.tree.setColumnWidth(c, w)
        rv.addWidget(self.tree, 1)

        g = QGridLayout()
        g.setSpacing(4)
        buttons = [("Объединить G", self.merge), ("Разделить", self.split), ("Убрать Del", self.remove_selected),
                   ("Верх/низ H", lambda: self.toggle("half")), ("Маска/прям. R", lambda: self.toggle("rect")),
                   ("Ось X/Y X", lambda: self.toggle("polarity")), ("Пауза P", self.toggle_pause),
                   ("Сбросить к авто", self.reset_auto), ("Отмена Ctrl+Z", lambda: self.history(True)),
                   ("Повтор Ctrl+Y", lambda: self.history(False))]
        for i, (t, fn) in enumerate(buttons):
            b = QPushButton(t)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        rv.addLayout(g)

        row = QHBoxLayout()
        row.addWidget(lbl("жанр", "dim"))
        self.genre = QComboBox()
        self.genre.addItem("—", None)
        for key, name in GENRES:
            self.genre.addItem(name, key)
        self.genre.activated.connect(self.on_genre)
        row.addWidget(self.genre, 1)
        rv.addLayout(row)

        self.check_btn = QPushButton("✓ Проверено и дальше (Space)")
        self.check_btn.clicked.connect(self.check_and_next)
        rv.addWidget(self.check_btn)

        tog = QHBoxLayout()
        self.cb_cands = QCheckBox("кандидаты C")
        self.cb_cands.setChecked(True)
        self.cb_cands.toggled.connect(lambda v: (setattr(self, "show_cands", v), self.refresh_overlay()))
        self.cb_els = QCheckBox("элементы E")
        self.cb_els.setChecked(True)
        self.cb_els.toggled.connect(lambda v: (setattr(self, "show_els", v), self.refresh_overlay()))
        self.cb_line = QCheckBox("линия L")
        self.cb_line.setChecked(True)
        self.cb_line.toggled.connect(lambda v: (setattr(self.canvas, "show_line", v), self.canvas.update()))
        for w in (self.cb_cands, self.cb_els, self.cb_line):
            tog.addWidget(w)
        rv.addLayout(tog)
        op = QHBoxLayout()
        op.addWidget(lbl("заливка", "dim"))
        self.op = QSlider(Qt.Horizontal)
        self.op.setRange(0, 100)
        self.op.setValue(45)
        self.op.valueChanged.connect(lambda v: (setattr(self, "opacity", v / 100), self.refresh_overlay()))
        op.addWidget(self.op, 1)
        rv.addLayout(op)

        rv.addWidget(lbl("СБОРКА И ОБУЧЕНИЕ", "title"))
        b1 = QPushButton("Собрать фото B (LaMa)")
        b1.clicked.connect(lambda: self.build([self.stem]))
        b2 = QPushButton("Собрать все изменённые")
        b2.clicked.connect(self.build_all)
        b3 = QPushButton("Предложить моделью M")
        b3.clicked.connect(self.model_suggest)
        b4 = QPushButton("Обучить модель")
        b4.clicked.connect(self.train_model)
        for b in (b1, b2, b3, b4):
            rv.addWidget(b)
        self.use_model = QCheckBox("модель — при «Подготовить фото»")
        self.use_model.setChecked(bool(self.settings.v.get("prep_use_model")))
        self.use_model.toggled.connect(self._use_model)
        rv.addWidget(self.use_model)
        self.model_info = lbl("", "dim")
        rv.addWidget(self.model_info)
        right.setFixedWidth(360)
        h.addWidget(right)

        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self._model_info()

    def _tools(self):
        """Панель над холстом: фото, выделение, фигуры, кисть."""
        bar = QHBoxLayout()
        bar.setSpacing(3)

        def btn(text, tip, fn=None, check=False):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCheckable(check)
            b.setStyleSheet("padding: 3px 7px;")
            if fn:
                b.clicked.connect(fn)
            bar.addWidget(b)
            return b
        bar.addWidget(lbl("ФОТО", "engrave_red"))
        btn("⟲ 90°", "повернуть фото на 90° против часовой (исходный файл; оригинал — в «_SMENA_оригиналы»; "
                     "элементы фото пересоберутся)", lambda: self.transform_photo("rot", -90))
        btn("⟳ 90°", "повернуть фото на 90° по часовой", lambda: self.transform_photo("rot", 90))
        btn("⇋", "отразить фото по горизонтали", lambda: self.transform_photo("flip", 0))
        bar.addSpacing(10)
        bar.addWidget(lbl("ВЫДЕЛЕНИЕ", "engrave_red"))
        self.tool_group = QButtonGroup(self)
        tools = [("sam", "✦ SAM", "SAM — клик по объекту: нейросеть сама находит контур (как раньше); клик по "
                                 "элементу — убрать, по кандидату — сделать элементом"),
                 ("hand", "✎ РУКА", "обвести элемент от руки — контур замкнётся сам"),
                 ("points", "⬠ ТОЧКИ", "многоугольник: клик — точка, двойной клик — замкнуть, правый клик — отмена"),
                 ("erase", "⌫ ЛАСТИК", "ластик: срезать лишнее с выделенного элемента (или с того, по которому "
                                      "ведёте)"),
                 ("horizon", "⊾ ГОРИЗ.", "выровнять горизонт: проведите линию вдоль горизонта — фото повернётся "
                                        "и обрежется по краям"),
                 ("rect", "▭", "фигура: прямоугольник — тянуть мышью"),
                 ("ellipse", "◯", "фигура: эллипс — тянуть мышью"),
                 ("tri", "△", "фигура: треугольник — тянуть мышью"),
                 ("hband", "▬", "фигура: горизонтальная полоса на всю ширину — тянуть по высоте"),
                 ("vband", "▮", "фигура: вертикальная полоса на всю высоту — тянуть по ширине"),
                 ("sector", "◔", "фигура: сектор 90° — от центра тянуть к краю (направление — середина сектора)")]
        for k, (key, text, tip) in enumerate(tools):
            if key == "rect":
                bar.addSpacing(10)
                bar.addWidget(lbl("ФИГУРЫ", "engrave_red"))
            b = btn(text, tip, check=True)
            self.tool_group.addButton(b, k)
        self.tool_group.button(0).setChecked(True)
        self.tool_group.idClicked.connect(lambda k: self.canvas.set_tool(tools[k][0]))
        bar.addSpacing(10)
        bar.addWidget(lbl("КИСТЬ", "engrave_red"))
        self.brush = QSlider(Qt.Horizontal)
        self.brush.setRange(4, 120)
        self.brush.setValue(24)
        self.brush.setFixedWidth(90)
        self.brush.setToolTip("толщина ластика, пиксели фото")
        self.brush.valueChanged.connect(lambda v: setattr(self.canvas, "brush", float(v)))
        bar.addWidget(self.brush)
        self.smooth = QSlider(Qt.Horizontal)
        self.smooth.setRange(1, 20)
        self.smooth.setValue(4)
        self.smooth.setFixedWidth(70)
        self.smooth.setToolTip("сглаживание линии от руки")
        self.smooth.valueChanged.connect(lambda v: setattr(self.canvas, "smooth", v))
        bar.addWidget(self.smooth)
        bar.addStretch()
        return bar

    def _shortcuts(self):
        keys = [("Right", lambda: self.goto(1)), ("Left", lambda: self.goto(-1)), ("PgDown", lambda: self.goto(1)),
                ("PgUp", lambda: self.goto(-1)), ("Space", self.check_and_next), ("G", self.merge),
                ("Delete", self.remove_selected), ("H", lambda: self.toggle("half")),
                ("R", lambda: self.toggle("rect")), ("X", lambda: self.toggle("polarity")), ("P", self.toggle_pause),
                ("B", lambda: self.build([self.stem])), ("M", self.model_suggest),
                ("Ctrl+Z", lambda: self.history(True)), ("Ctrl+Y", lambda: self.history(False)),
                ("C", self.cb_cands.toggle), ("E", self.cb_els.toggle), ("L", self.cb_line.toggle)]
        for k, fn in keys:
            QShortcut(QKeySequence(k), self, activated=fn)

    def _sam_state(self, text):
        self.status.setText(text)

    # ------------------------------------------------------------------ набор фото
    def load_set(self):
        s = self.settings
        self.paths = SetPaths(s["photos_dir"], s["cache_dir"])
        self.sel = Selections(self.paths)
        p = self.paths
        have = (p.cands / p.stems[0] / "cands.npz").is_file() if p.stems else False
        self.set_info.setText(f"набор: {p.set_name} · {len(p.stems)} фото\nкандидаты: {p.cands}\n"
                              f"авто: {p.auto.name} · ручной: {p.manual.name}\nкеш: {p.elements}")
        self.photos.blockSignals(True)
        self.photos.clear()
        for i, st in enumerate(p.stems):
            self.photos.addItem(QListWidgetItem(self._row_text(i, st)))
        self.photos.blockSignals(False)
        if not have:
            self.canvas.hint = "у набора нет кандидатов SAM 2 — сначала вкладка ФОТО → «Подготовить фото»"
            self.canvas.set_photo(None)
            return
        self.sam.start()
        first = next((i for i, st in enumerate(p.stems) if self.sel.status(st) != "checked"), 0)
        self.photos.setCurrentRow(first)
        self._progress()

    def _row_text(self, i, stem):
        return f"{STATUS_ICON[self.sel.status(stem)]} {i + 1:03d}  {stem}  · {self.sel.count(stem)}"

    def _progress(self):
        st = [self.sel.status(s) for s in self.paths.stems]
        self.progress.setText(f"проверено {st.count('checked')} / {len(st)} · изменено {st.count('edited')} · "
                              f"пауз {st.count('pause')}")

    def goto(self, d):
        r = self.photos.currentRow() + d
        if 0 <= r < self.photos.count():
            self.photos.setCurrentRow(r)

    def open_photo(self, row):
        if row < 0 or not self.paths or row >= len(self.paths.stems):
            return
        self.stem = stem = self.paths.stems[row]
        try:
            pd = self.photo_cache.get(stem) or PhotoData(self.paths, stem)
        except Exception as e:
            self.canvas.hint = f"{stem}: нет кандидатов ({e})"
            self.canvas.set_photo(None)
            return
        self.photo_cache = {stem: pd, **{k: v for k, v in list(self.photo_cache.items())[-3:] if k != stem}}
        self.pd = pd
        img = QImage(str(pd.source)) if pd.source else QImage()
        self.canvas.set_photo(img.scaled(pd.W, pd.H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                              if not img.isNull() else None)
        self.active_extra, self.extra_points = None, []
        if pd.source:
            self.sam.call("image", path=str(pd.source))
        if not pd.features:
            self.sam.call("features", lambda m, pd=pd: pd.load_features(), photos=str(self.paths.photos),
                          cdir=str(pd.dir), stem=stem)
        self.refresh()

    # ------------------------------------------------------------------ показ
    def _mask(self, kind, src):
        key = (self.stem, kind, json.dumps(src) if kind == "cand" else src)
        if key not in self.mask_cache:
            self.mask_cache[key] = self.pd.group_mask(src) if kind == "cand" else self.pd.extra_mask(src)
            if len(self.mask_cache) > 400:
                self.mask_cache.pop(next(iter(self.mask_cache)))
        return self.mask_cache[key]

    def _line(self, entry):
        if entry.get("line_y") is not None:
            return entry["line_y"]
        pj = self.paths.elements / self.stem / "photo.json"
        try:
            return json.loads(pj.read_text(encoding="utf-8"))["composition_line"]["y"]
        except Exception:
            return 0.5

    def _half(self, entry, i, m):
        if str(i) in entry.get("half", {}):
            return entry["half"][str(i)]
        ly = int(self._line(entry) * self.pd.H)
        return "bottom" if m[ly:].sum() >= m[:ly].sum() else "top"

    def _polarity(self, entry, i, m):
        if str(i) in entry.get("polarity", {}):
            return entry["polarity"][str(i)]
        ys, xs = np.nonzero(m)
        return "X" if len(xs) and (np.ptp(xs) >= np.ptp(ys)) else "Y"

    def refresh(self):
        if not self.pd:
            return
        e = self.sel.entry(self.stem)
        self.canvas.line_y = self._line(e)
        idx = self.genre.findData(e.get("genre"))
        self.genre.setCurrentIndex(max(idx, 0))
        self.tree.blockSignals(True)
        self.tree.clear()
        for i, (kind, src) in enumerate(elements_of(e), 1):
            m = self._mask(kind, src)
            if kind == "cand":
                origin = (f"кусок #{src['n']}" if isinstance(src, dict) else "канд. " + "+".join(f"#{n}" for n in src))
            else:
                drawn = getattr(self, "drawn", {}).get((self.stem, src))
                origin = f"{drawn} {src.replace('.png', '')}" if drawn else f"SAM {src.replace('.png', '')}"
            it = QTreeWidgetItem([str(i), origin, "верх" if self._half(e, i, m) == "top" else "низ",
                                  "прям." if i in e.get("rect", []) else "маска", self._polarity(e, i, m)])
            it.setData(0, Qt.UserRole, i)
            self.tree.addTopLevelItem(it)
        self.tree.blockSignals(False)
        n = len(elements_of(e))
        warn = f" · больше {MAX_ELEMENTS}!" if n > MAX_ELEMENTS else ""
        self.title.setText(f"{self.stem} — {'ПАУЗА' if e.get('pause') else f'{n} элем.'}{warn}"
                           f"{' · ✓ проверено' if e.get('checked') else ''}")
        row = self.paths.stems.index(self.stem)
        self.photos.item(row).setText(self._row_text(row, self.stem))
        self._progress()
        self.refresh_overlay()

    def selected(self):
        return sorted(it.data(0, Qt.UserRole) for it in self.tree.selectedItems())

    def refresh_overlay(self):
        if not self.pd:
            return
        pd, e = self.pd, self.sel.entry(self.stem)
        rgba = np.zeros((pd.H, pd.W, 4), np.uint8)
        used = set()
        items = elements_of(e)
        for kind, src in items:
            used.update(element_cands(kind, src))
        if self.show_cands:
            if not hasattr(pd, "bounds"):
                pd.bounds = {n: boundary(pd.cand_mask(n)) for n in pd.cands}
            for n, b in pd.bounds.items():
                if n not in used:
                    rgba[b] = (210, 210, 210, 150)
        labels = []
        sel = set(self.selected())
        if self.show_els:
            for i, (kind, src) in enumerate(items, 1):
                m = self._mask(kind, src)
                col = PALETTE[(i - 1) % len(PALETTE)]
                fill = rgba[m]
                fill[:] = (*col, int(255 * self.opacity))
                rgba[m] = fill
                rgba[boundary(m, 2 if i in sel else 1)] = (255, 255, 255, 255) if i in sel else (*col, 255)
                ys, xs = np.nonzero(m)
                if len(xs):
                    labels.append((float(np.median(xs)), float(np.median(ys)), str(i), col))
        self.canvas.labels = labels
        self.canvas.set_overlay(rgba)

    # ------------------------------------------------------------------ метки
    def _feat(self, n):
        return self.pd.features.get(str(n))

    def _log_cand(self, n, label, source="user", group=None):
        e = self.sel.entry(self.stem)
        self.sel.log({"photo": self.stem, "cand": n, "mask": None, "label": label, "source": source, "group": group,
                      "auto": int(n in self.sel.auto_cands(self.stem)), "features": self._feat(n),
                      "genre": e.get("genre")})

    def _log_extra(self, name, label=1, source="user"):
        e = self.sel.entry(self.stem)
        self.sel.log({"photo": self.stem, "cand": None, "mask": name, "label": label, "source": source,
                      "group": None, "auto": 0, "features": self.extra_feats.get((self.stem, name)),
                      "genre": e.get("genre")})

    # ------------------------------------------------------------------ клики
    def on_click(self, x, y, mods):
        if not self.pd:
            return
        e = self.sel.entry(self.stem)
        if mods & (Qt.ShiftModifier | Qt.AltModifier) and self.active_extra:
            self.extra_points.append([x, y, 0 if mods & Qt.AltModifier else 1])
            name, st = self.active_extra, self.stem
            self.sam.call("predict", lambda r: self._extra_done(r, name, False, st), points=self.extra_points)
            return
        hits = []
        for i, (kind, src) in enumerate(elements_of(e), 1):
            m = self._mask(kind, src)
            if m[y, x]:
                hits.append((m.sum(), i))
        if mods & Qt.ControlModifier:                       # выделить элемент (для объединения)
            if hits:
                i = min(hits)[1]
                it = self.tree.topLevelItem(i - 1)
                it.setSelected(not it.isSelected())
            return
        if hits:                                             # клик по элементу — убрать
            self.remove([min(hits)[1]])
            return
        used = set()
        for kind, src in elements_of(e):
            used.update(element_cands(kind, src))
        cands = [(self.pd.cands[n]["area"], n) for n in self.pd.cands
                 if n not in used and self.pd.cand_mask(n)[y, x]]
        if cands:                                            # клик по кандидату — сделать элементом
            n = min(cands)[1]

            def add(en):
                if en.get("pause"):
                    en["pause"] = False
                items = current_items(en)
                k = sum(1 for it in items if it[0] == "cand")
                rebuild(en, items[:k] + [("cand", [n], None)] + items[k:])
            self.sel.change(self.stem, add)
            self._log_cand(n, 1)
            self.refresh()
            return
        if not self.sam.proc:                                # пустое место — маска SAM 2 по точке
            self.status.setText("SAM 2 недоступен — клик по пустому месту не работает")
            return
        name = self.pd.next_extra_name()
        self.active_extra, self.extra_points = name, [[x, y, 1]]
        self.status.setText("SAM 2: маска по точке…")
        st = self.stem
        self.sam.call("predict", lambda r: self._extra_done(r, name, True, st), points=self.extra_points)

    def _extra_done(self, r, name, new, stem):
        if "rle" not in r or stem != self.stem:            # ответ пришёл, когда уже другое фото
            return
        m = unpack(r["rle"], r["w"], r["h"])
        if m.shape != (self.pd.H, self.pd.W) or m.sum() < 30:
            self.status.setText("SAM 2: пустая маска — попробуйте другую точку")
            return
        self.pd.save_extra(name, m)
        self.mask_cache.pop((self.stem, "extra", name), None)
        stem = self.stem
        if new:
            def add(en):
                if en.get("pause"):
                    en["pause"] = False
                rebuild(en, current_items(en) + [("extra", name, None)])
            self.sel.change(stem, add)
        self.sam.call("mask_features", lambda f: self._extra_feat(f, stem, name, new),
                      rle=r["rle"], w=r["w"], h=r["h"], score=r.get("score", 0.5))
        self.status.setText(f"SAM 2: маска {name} (оценка {r.get('score', 0):.2f}) — Shift/Alt+клик уточняют")
        self.refresh()

    def _extra_feat(self, f, stem, name, new):
        self.extra_feats[(stem, name)] = f.get("features")
        if new and stem == self.stem:
            self._log_extra(name)

    # ------------------------------------------------------------- рисование
    def on_shape(self, m, origin):
        """Элемент от руки / по точкам / фигурой — новая маска extra (как клик SAM)."""
        if not self.pd:
            return
        name = self.pd.next_extra_name()
        self.pd.save_extra(name, m)
        self.mask_cache.pop((self.stem, "extra", name), None)
        stem = self.stem

        def add(en):
            if en.get("pause"):
                en["pause"] = False
            rebuild(en, current_items(en) + [("extra", name, None)])
        self.sel.change(stem, add)
        self.drawn = getattr(self, "drawn", {})
        self.drawn[(stem, name)] = origin
        if self.sam.proc:
            self.sam.call("mask_features", lambda f: self._extra_feat(f, stem, name, True),
                          rle=pack(m), w=self.pd.W, h=self.pd.H, score=0.9)
        self.status.setText(f"элемент {origin}: {name}")
        self.refresh()

    def on_erase(self, stroke):
        """Ластик: срезать мазок с выделенного элемента (или с того, который мазок задевает больше всех)."""
        if not self.pd:
            return
        e = self.sel.entry(self.stem)
        items = current_items(e)
        sel = self.selected()
        target = None
        if len(sel) == 1:
            target = next((it for it in items if it[2] == sel[0]), None)
        if target is None:
            hits = [((self._mask(k, s) & stroke).sum(), (k, s, i)) for k, s, i in items]
            hits = [h for h in hits if h[0] > 0]
            if not hits:
                self.status.setText("ластик: мазок не задел ни одного элемента")
                return
            target = max(hits, key=lambda h: h[0])[1]
        kind, src, idx = target
        m = self._mask(kind, src) & ~stroke
        if m.sum() < 30:
            self.remove([idx])
            return
        name = self.pd.next_extra_name()
        self.pd.save_extra(name, m)
        self.mask_cache.pop((self.stem, "extra", name), None)
        self.sel.change(self.stem, lambda en: rebuild(en, [("extra", name, o) if o == idx else (k, s2, o)
                                                           for k, s2, o in current_items(en)]))
        self.status.setText(f"ластик: элемент {idx} поправлен")
        self.refresh()

    # ------------------------------------------------------- поворот исходного фото
    def transform_photo(self, kind, value):
        """Поворот / отражение / горизонт: меняется исходный файл (оригинал — копией в «_SMENA_оригиналы»),
        кандидаты и элементы этого фото убираются в «_старое» кеша и готовятся заново (ФОТО → подготовка)."""
        if not self.pd or not self.pd.source:
            return
        src = Path(self.pd.source)
        what = {"rot": f"повернуть на {abs(value):.0f}° {'по' if value > 0 else 'против'} часовой",
                "flip": "отразить по горизонтали", "angle": f"выровнять горизонт (поворот {value:+.1f}°, края обрежутся)"}
        if QMessageBox.question(self, "Фото", f"{src.name}: {what[kind]}?\n\nИсходный файл изменится (оригинал "
                                f"сохранится в «_SMENA_оригиналы»). Элементы этого фото будут подготовлены заново "
                                f"(SAM 2 + LaMa, ~20 с), ручной выбор элементов фото сбросится.") != QMessageBox.Yes:
            return
        img = QImage(str(src))
        if img.isNull():
            self.status.setText(f"не читается: {src}")
            return
        if kind == "rot":
            out = img.transformed(QTransform().rotate(value), Qt.SmoothTransformation)
        elif kind == "flip":
            out = img.mirrored(True, False)
        else:                                            # горизонт: поворот и обрезка без пустых углов
            W, H = img.width(), img.height()
            rot = img.transformed(QTransform().rotate(value), Qt.SmoothTransformation)
            a = abs(np.radians(value))
            c, s_ = np.cos(a), np.sin(a)
            # наибольший прямоугольник тех же пропорций внутри повёрнутого
            k = min(W / (W * c + H * s_), H / (W * s_ + H * c))
            w2, h2 = int(W * k), int(H * k)
            out = rot.copy((rot.width() - w2) // 2, (rot.height() - h2) // 2, w2, h2)
        backup = src.parent / "_SMENA_оригиналы"
        backup.mkdir(exist_ok=True)
        if not (backup / src.name).exists():
            shutil.copy2(src, backup / src.name)
        if not out.save(str(src), quality=95):
            self.status.setText(f"не записался: {src}")
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        old = Path(self.settings["cache_dir"]) / "_старое" / f"{self.stem}_{stamp}"
        old.mkdir(parents=True, exist_ok=True)
        for d, sub in ((self.pd.dir, "cands"), (self.paths.elements / self.stem, "elements")):
            if d.is_dir():
                shutil.move(str(d), str(old / sub))
        self.sel.manual.pop(self.stem, None)
        self.sel.save()
        self.photo_cache.pop(self.stem, None)
        self.mask_cache = {k: v for k, v in self.mask_cache.items() if k[0] != self.stem}
        self.pd = None
        self.canvas.hint = f"{src.name}: фото изменено — идёт подготовка (вкладка ФОТО), потом откройте фото снова"
        self.canvas.set_photo(None)
        self.sam.stop()                                  # видеопамять — подготовке (SAM 2 + LaMa)
        tab = self.main.photos_tab
        tab.rescan()
        tab.runner.finished.connect(self._prep_after_transform)
        tab.start_prep()
        self.status.setText(f"{src.name}: {what[kind]} — готовлю элементы заново")

    def _prep_after_transform(self, ok, text):
        try:
            self.main.photos_tab.runner.finished.disconnect(self._prep_after_transform)
        except Exception:
            pass
        self.status.setText(f"подготовка: {text}")
        if self.isVisible():
            self.load_set()

    # ------------------------------------------------------------------ операции
    def remove(self, idxs):
        e = self.sel.entry(self.stem)
        items = current_items(e)
        gone = [it for it in items if it[2] in idxs]
        self.sel.change(self.stem, lambda en: rebuild(en, [it for it in current_items(en) if it[2] not in idxs]))
        for kind, src, _ in gone:
            for n in element_cands(kind, src):
                self._log_cand(n, 0)
            if kind == "extra":
                self._log_extra(src, label=0)
        self.refresh()

    def remove_selected(self):
        if self.selected():
            self.remove(self.selected())

    def merge(self):
        idxs = self.selected()
        if len(idxs) < 2:
            self.status.setText("объединить: выделите 2+ элемента (Ctrl+клик или в списке)")
            return
        e = self.sel.entry(self.stem)
        items = current_items(e)
        chosen = [it for it in items if it[2] in idxs]
        plain = all(k == "cand" and not isinstance(s, dict) for k, s, _ in chosen)
        if plain:                                            # кандидаты → один элемент из нескольких частей
            group = sorted({n for _, s, _ in chosen for n in s})

            def fn(en):
                its = current_items(en)
                out = []
                for it in its:
                    if it[2] == idxs[0]:
                        out.append(("cand", group, idxs[0]))
                    elif it[2] not in idxs:
                        out.append(it)
                rebuild(en, out)
            self.sel.change(self.stem, fn)
            for n in group:
                self._log_cand(n, 1, group=group)
        else:                                                # с масками SAM / кусками — объединённая маска
            m = np.zeros((self.pd.H, self.pd.W), bool)
            for k, s, _ in chosen:
                m |= self._mask(k, s)
            name = self.pd.next_extra_name()
            self.pd.save_extra(name, m)
            self.sel.change(self.stem, lambda en: rebuild(en, [it for it in current_items(en) if it[2] not in idxs]
                                                          + [("extra", name, idxs[0])]))
            self.sam.call("mask_features", lambda f: self._extra_feat(f, self.stem, name, True),
                          rle=pack(m), w=self.pd.W, h=self.pd.H, score=0.9)
        self.refresh()

    def split(self):
        idxs = self.selected()
        e = self.sel.entry(self.stem)

        def fn(en):
            out = []
            for k, s, o in current_items(en):
                if o in idxs and k == "cand" and not isinstance(s, dict) and len(s) > 1:
                    out += [("cand", [n], o if j == 0 else None) for j, n in enumerate(s)]
                else:
                    out.append((k, s, o))
            rebuild(en, out)
        if any(k == "cand" and not isinstance(s, dict) and len(s) > 1 for k, s, o in current_items(e) if o in idxs):
            self.sel.change(self.stem, fn)
            self.refresh()
        else:
            self.status.setText("разделить: выделите элемент из нескольких частей")

    def toggle(self, what):
        idxs = self.selected()
        if not idxs:
            self.status.setText("выделите элемент(ы) в списке или Ctrl+кликом")
            return
        e = self.sel.entry(self.stem)
        cur = {i: (k, s) for k, s, i in current_items(e)}

        def fn(en):
            for i in idxs:
                m = self._mask(*cur[i])
                if what == "half":
                    en["half"][str(i)] = "bottom" if self._half(en, i, m) == "top" else "top"
                elif what == "polarity":
                    en["polarity"][str(i)] = "Y" if self._polarity(en, i, m) == "X" else "X"
                elif what == "rect":
                    en["rect"] = sorted(set(en["rect"]) ^ {i})
        self.sel.change(self.stem, fn)
        self.refresh()
        for i in idxs:
            self.tree.topLevelItem(i - 1).setSelected(True)

    def toggle_pause(self):
        self.sel.change(self.stem, lambda en: en.update(pause=not en.get("pause")))
        self.refresh()

    def reset_auto(self):
        self.sel.reset_to_auto(self.stem)
        self.refresh()

    def history(self, back):
        if self.sel.step(self.stem, back):
            self.mask_cache = {k: v for k, v in self.mask_cache.items() if k[0] != self.stem}
            self.refresh()

    def on_line(self, y):
        self.sel.change(self.stem, lambda en: en.update(line_y=round(y, 4)))
        self.refresh()

    def on_genre(self, _):
        g = self.genre.currentData()
        self.sel.change(self.stem, lambda en: en.update(genre=g))
        self.refresh()

    def check_and_next(self):
        """Проверено: все кандидаты фото получают метку (выбранные — 1, остальные — 0), дальше."""
        if not self.pd:
            return
        stem, pd = self.stem, self.pd
        self.sel.change(stem, lambda en: en.update(checked=True))
        if pd.features:
            self._log_checked(stem, pd)
        else:                                   # признаки ещё считаются — метки запишем, когда будут готовы
            pd.load_features()
            if pd.features:
                self._log_checked(stem, pd)
            else:
                self.sam.call("features", lambda m: (pd.load_features(), self._log_checked(stem, pd)),
                              photos=str(self.paths.photos), cdir=str(pd.dir), stem=stem)
        self.refresh()
        self.goto(1)

    def _log_checked(self, stem, pd):
        """Метки по всем кандидатам проверенного фото: выбранные — 1, остальные — 0."""
        e = self.sel.entry(stem)
        auto = self.sel.auto_cands(stem)
        chosen = {}
        for kind, src in elements_of(e):
            for n in element_cands(kind, src):
                chosen[n] = element_cands(kind, src)
        for n in pd.cands:
            label = int(n in chosen)
            self.sel.log({"photo": stem, "cand": n, "mask": None, "label": label,
                          "source": "user" if label != int(n in auto) else "auto_kept",
                          "group": chosen.get(n) if len(chosen.get(n, [])) > 1 else None,
                          "auto": int(n in auto), "features": pd.features.get(str(n)), "genre": e.get("genre")})
        for kind, src in elements_of(e):
            if kind == "extra":
                self.sel.log({"photo": stem, "cand": None, "mask": src, "label": 1, "source": "user", "group": None,
                              "auto": 0, "features": self.extra_feats.get((stem, src)), "genre": e.get("genre")})

    # ------------------------------------------------------------------ сборка
    def build(self, stems):
        stems = [s for s in stems if s]
        if not stems or self.build_proc:
            return
        for s in stems:                                      # в ручной файл — всё, что собираем
            if s not in self.sel.manual:
                self.sel.change(s, lambda en: None)
        s = self.settings
        p = QProcess(self)
        p.setProcessEnvironment(script_env(QProcessEnvironment.systemEnvironment()))
        p.setWorkingDirectory(s["prep_scripts"])
        p.setProcessChannelMode(QProcess.MergedChannels)
        out = []
        p.readyReadStandardOutput.connect(lambda: out.append(bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))
        p.finished.connect(lambda code, _st: self._built(code, stems, "".join(out)))
        self.build_proc = p
        self.status.setText(f"сборка {len(stems)} фото (LaMa)…")
        p.start(*script_cmd(s["prep_python"], Path(s["prep_scripts"]) / "build_elements.py",
                            [self.paths.photos, self.paths.cands, self.paths.manual, self.paths.elements,
                             "--only", *stems]))

    def build_all(self):
        stems = [s for s in self.paths.stems if self.sel.status(s) != "auto"]
        if not stems:
            self.status.setText("изменённых фото нет")
            return
        self.build(stems)

    def _built(self, code, stems, out):
        self.build_proc = None
        if code != 0:
            self.status.setText("сборка: ошибка — подробности в журнале")
            log.warning("build_elements: %s", out[-2000:])
            return
        self.status.setText(f"собрано {len(stems)} фото — программа видит новые элементы")
        self.main.photos_tab.rescan()
        if len(stems) == 1:
            prev = self.paths.elements / stems[0] / "preview.jpg"
            if prev.is_file():
                d = QDialog(self)
                d.setWindowTitle(f"Собрано: {stems[0]}")
                v = QVBoxLayout(d)
                lab = QLabel()
                lab.setPixmap(QPixmap(str(prev)).scaledToWidth(1100, Qt.SmoothTransformation))
                v.addWidget(lab)
                d.show()

    # ------------------------------------------------------------------ модель
    def _model_info(self):
        m = train.load_model()
        self.model_info.setText(train.describe(m) if m else "модели пока нет — разметьте фото (Space) и «Обучить»")

    def _use_model(self, on):
        self.settings["prep_use_model"] = bool(on)
        self.settings.save()

    def model_suggest(self):
        m = train.load_model()
        if not m or not self.pd:
            self.status.setText("модели нет — сначала «Обучить модель»")
            return
        if not self.pd.features:
            self.status.setText("признаки фото ещё считаются (SAM-сервер) — попробуйте через пару секунд")
            return
        probs = sorted(((train.proba(f, m), int(n)) for n, f in self.pd.features.items()), reverse=True)
        picked = []
        for p, n in probs:
            if p < m.get("threshold", 0.5) or len(picked) >= MAX_ELEMENTS:
                break
            mk = self.pd.cand_mask(n)
            if all((mk & self.pd.cand_mask(q)).sum() / min(mk.sum(), self.pd.cand_mask(q).sum()) < MAX_OVERLAP
                   for q in picked):
                picked.append(n)

        def fn(en):
            keep = [it for it in current_items(en) if it[0] == "extra" or isinstance(it[1], dict)]
            rebuild(en, [("cand", [n], None) for n in picked] + keep)
            en["pause"] = False
        self.sel.change(self.stem, fn)
        self.status.setText(f"модель предложила {len(picked)} элем. — поправьте и нажмите Space")
        self.refresh()

    def train_model(self):
        try:
            m = train.train()
        except Exception as e:
            QMessageBox.warning(self, "Обучение", str(e))
            return
        self._model_info()
        QMessageBox.information(self, "Обучение", train.describe(m))

    def closeEvent(self, e):
        self.sam.stop()
        super().closeEvent(e)
