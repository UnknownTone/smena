"""Мост к подготовке фото (01_BUILD_BRIEF.md §6): SAM 2 → отбор v2 → LaMa во внешнем процессе .venv-prep.

Тяжёлая часть (PyTorch, модели) не входит в программу — запускается python окружения подготовки.
Готовые фото пропускаются: в работу идут только фото без кеша. Кеш набора:
    <кеш>\\cands\\<фото>\\…          кандидаты SAM 2
    <кеш>\\selection.json            отбор
    <кеш>\\elements\\<фото>\\…       элементы и чистый фон — их читает программа
"""
import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from smena.runtime import prep_available, script_cmd, script_env

log = logging.getLogger("smena.prep")

# шаг: подпись, скрипт, доля общего времени (замеры: SAM ~13 мин, LaMa ~1.5 мин на 56 фото)
STEPS = [("кандидаты (SAM 2)", "candidates.py", 0.85),
         ("отбор элементов", "auto_select.py", 0.03),
         ("элементы и фон (LaMa)", "build_elements.py", 0.12)]
PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")
NOISE = ("Skipping the post-processing", "postprocess_masks(")   # безвредные сообщения SAM 2 без CUDA-расширения


def check_paths(python, scripts):
    """Список проблем с путями подготовки (пусто — всё на месте)."""
    out = []
    if not prep_available(python):
        out.append(f"нет python подготовки: {python}")
    for _, s, _ in STEPS:
        if not (Path(scripts) / s).is_file():
            out.append(f"нет скрипта: {Path(scripts) / s}")
    return out


class PrepRunner(QObject):
    line = Signal(str)                              # строка журнала
    progress = Signal(str, int, int, float, float)  # шаг, i, n, доля всей работы 0..1, осталось секунд (−1 — неизвестно)
    finished = Signal(bool, str)                    # успех, итог

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.steps = []
        self.step = 0
        self.t0 = 0.0
        self.n_photos = 0
        self._buf = b""
        self._stopped = False
        self._done_in_step = 0

    @property
    def running(self):
        return self.proc is not None

    def start(self, python, scripts, photos_dir, cache_dir, missing, model=None):
        """missing — PhotoEntry без кеша (с исходным файлом); model — модель отбора (редактор элементов) или None."""
        cache = Path(cache_dir)
        names = [e.source.name for e in missing]
        stems = [e.source.stem for e in missing]
        cands, sel, elements = cache / "cands", cache / "selection.json", cache / "elements"
        cache.mkdir(parents=True, exist_ok=True)
        self.python, self.scripts = str(python), Path(scripts)
        self.steps = [
            [str(photos_dir), str(cands), "--only", *names],
            [str(photos_dir), str(cands), str(sel), "--features"] + (["--model", str(model)] if model else []),
            [str(photos_dir), str(cands), str(sel), str(elements), "--only", *stems],
        ]
        self.n_photos = len(missing)
        self.step = 0
        self._stopped = False
        self.t0 = time.perf_counter()
        self.line.emit(f"подготовка: {len(missing)} фото → {cache}")
        self._run_step()

    def stop(self):
        if self.proc:
            self._stopped = True
            self.line.emit("остановлено — готовые фото сохранены, продолжить можно позже")
            self.proc.kill()

    # ------------------------------------------------------------------ шаги
    def _run_step(self):
        label, script, _ = STEPS[self.step]
        self.line.emit(f"— шаг {self.step + 1}/3: {label}")
        self._done_in_step = 0
        self.step_t0 = time.perf_counter()
        p = QProcess(self)
        p.setProcessEnvironment(script_env(QProcessEnvironment.systemEnvironment()))
        p.setWorkingDirectory(str(self.scripts))
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._read)
        p.finished.connect(self._step_done)
        p.errorOccurred.connect(self._error)
        self.proc = p
        self._buf = b""
        p.start(*script_cmd(self.python, self.scripts / script, self.steps[self.step]))
        self._emit_progress(0, self.n_photos)

    def _error(self, err):
        if err == QProcess.FailedToStart and self.proc:
            self.line.emit(f"не запускается: {self.python}")

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            s = raw.decode("utf-8", errors="replace").rstrip()
            if not s or "Warning" in s or s.startswith("  warnings.warn") or any(n in s for n in NOISE):
                continue
            self.line.emit(s)
            m = PROGRESS_RE.search(s)
            if m:
                self._emit_progress(int(m[1]), int(m[2]))
            elif self.step == 1 and " элем." in s:          # отбор: строка на каждое фото
                self._done_in_step += 1
                self._emit_progress(self._done_in_step, max(self._done_in_step, 1))

    def _emit_progress(self, i, n):
        done_w = sum(w for _, _, w in STEPS[:self.step])
        w = STEPS[self.step][2]
        frac = done_w + w * (i / n if n else 0)
        el = time.perf_counter() - self.t0
        eta = el * (1 - frac) / frac if frac > 0.03 else -1.0
        self.progress.emit(STEPS[self.step][0], i, n, frac, eta)

    def _step_done(self, code, status):
        self._read()
        self.proc = None
        if self._stopped:
            self.finished.emit(False, "остановлено")
            return
        if code != 0:
            self.line.emit(f"ошибка: шаг «{STEPS[self.step][0]}» завершился с кодом {code}")
            self.finished.emit(False, f"ошибка на шаге «{STEPS[self.step][0]}»")
            return
        self.step += 1
        if self.step < len(STEPS):
            self._run_step()
        else:
            mins = (time.perf_counter() - self.t0) / 60
            self.line.emit(f"готово: {self.n_photos} фото за {mins:.1f} мин")
            self.progress.emit("готово", self.n_photos, self.n_photos, 1.0, 0.0)
            self.finished.emit(True, f"готово за {mins:.1f} мин")
