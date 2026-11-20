"""Клиент SAM-сервера (tools/prep/sam_server.py): фоновый процесс .venv-prep, JSON-строки через stdin/stdout.
Запросы, отправленные до загрузки модели, ждут в очереди; ответ приходит в колбэк по номеру запроса."""
import base64
import json
import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from smena.runtime import prep_available, script_cmd, script_env

log = logging.getLogger("smena.sam")


def unpack(rle, w, h):
    b = np.frombuffer(base64.b64decode(rle), np.uint8)
    return np.unpackbits(b.reshape(h, -1), axis=-1)[:, :w].astype(bool)


def pack(m):
    return base64.b64encode(np.packbits(m.astype(bool), axis=-1).tobytes()).decode("ascii")


class SamClient(QObject):
    state = Signal(str)          # текст состояния для строки статуса

    def __init__(self, python, scripts, parent=None):
        super().__init__(parent)
        self.python, self.scripts = str(python), Path(scripts)
        self.proc = None
        self.ready = False
        self._id = 0
        self._cb = {}
        self._queue = []
        self._buf = b""

    def start(self):
        if self.proc:
            return
        if not prep_available(self.python) or not (self.scripts / "sam_server.py").is_file():
            self.state.emit("SAM 2 недоступен: нет нейросетей или tools/prep/sam_server.py (клики по кандидатам работают)")
            return
        p = QProcess(self)
        p.setProcessEnvironment(script_env(QProcessEnvironment.systemEnvironment()))
        p.setWorkingDirectory(str(self.scripts))
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.readyReadStandardOutput.connect(self._read)
        p.readyReadStandardError.connect(lambda: p.readAllStandardError())   # служебный вывод — в никуда
        p.finished.connect(self._finished)
        self.proc = p
        self.state.emit("SAM 2 загружается… (около 10 с)")
        p.start(*script_cmd(self.python, self.scripts / "sam_server.py"))

    def stop(self):
        if self.proc:
            self.call("quit")
            if not self.proc.waitForFinished(3000):
                self.proc.kill()
            self.proc = None
            self.ready = False

    def call(self, cmd, cb=None, **kw):
        self._id += 1
        req = {"id": self._id, "cmd": cmd, **kw}
        if cb:
            self._cb[self._id] = cb
        if self.ready:
            self._send(req)
        else:
            self._queue.append(req)
            self.start()
        return self._id

    def _send(self, req):
        self.proc.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            if msg.get("ready"):
                self.ready = True
                self.state.emit(f"SAM 2 готов ({msg.get('device')}) — клик в пустое место создаёт маску")
                for req in self._queue:
                    self._send(req)
                self._queue = []
                continue
            cb = self._cb.pop(msg.get("id"), None)
            if msg.get("error"):
                log.warning("SAM: %s", msg["error"])
                self.state.emit(f"SAM 2: ошибка {msg['error'][:80]}")
            if cb:
                cb(msg)

    def _finished(self, *_):
        if self.proc:
            self.state.emit("SAM 2 остановлен")
        self.proc = None
        self.ready = False
