"""REC: запись выхода (то, что идёт на HDMI) в mp4 со звуком.

Видео: кадры текстуры выхода, 30 к/с, через PBO (чтение без остановки видеокарты) → поток записи → ffmpeg
(NVENC видеокарты, если есть; иначе x264). Звук: блоки источника после эквалайзера и громкости (поток звука) →
временный wav. На СТОП — склейка в mp4 (видео без перекодирования + AAC). Файлы: Видео\\SMENA\\SMENA_дата_время.mp4.
"""
import logging
import queue
import subprocess
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QStandardPaths

from smena.audio.capture import NO_WINDOW, SR, ffmpeg_exe

log = logging.getLogger("smena.rec")
FPS = 30
_enc = None

# аппаратные кодеки по порядку: NVIDIA (Windows), Apple VideoToolbox (macOS); иначе — x264 на процессоре
HW = (("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-b:v", "0"]),
      ("h264_videotoolbox", ["-c:v", "h264_videotoolbox", "-q:v", "70", "-allow_sw", "1"]))
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]


def encoder():
    """Аргументы кодека: первый аппаратный, что прошёл пробный кадр (результат запоминается)."""
    global _enc
    if _enc is None:
        _enc = X264
        for name, args in HW:
            try:
                p = subprocess.run([ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x144:d=0.1",
                                    "-c:v", name, "-f", "null", "-"], capture_output=True, timeout=20,
                                   creationflags=NO_WINDOW)
                if p.returncode == 0:
                    _enc = args
                    break
            except Exception:
                pass
        log.info("кодек записи: %s", _enc[1])
    return _enc


def has_nvenc():
    return encoder()[1] != "libx264"


def rec_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation) or str(Path.home() / "Videos")
    return Path(base) / "SMENA"


class Recorder:
    def __init__(self, log_event=None):
        self.log_event = log_event or log.info
        self.active = False
        self.path = None
        self.t0 = 0.0
        self.frames = 0
        self._pbo = []
        self._pending = None
        self._next_t = 0.0
        self._q = None
        self._thread = None
        self._wav = None
        self._wav_lock = threading.Lock()
        self.size = None
        self.error = None

    # ------------------------------------------------------------- старт / стоп
    def start(self, size):
        if self.active:
            return
        d = rec_dir()
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = d / f"SMENA_{stamp}.mp4"
        self._video = d / f".SMENA_{stamp}_video.mp4"
        self._audio = d / f".SMENA_{stamp}_audio.wav"
        self.size = tuple(size)
        w, h = self.size
        enc = encoder()
        self._proc = subprocess.Popen(
            [ffmpeg_exe(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
             "-r", str(FPS), "-i", "-", "-vf", "vflip", *enc, "-pix_fmt", "yuv420p", str(self._video)],
            stdin=subprocess.PIPE, creationflags=NO_WINDOW)
        with self._wav_lock:
            self._wav = wave.open(str(self._audio), "wb")
            self._wav.setnchannels(2)
            self._wav.setsampwidth(2)
            self._wav.setframerate(SR)
        self._q = queue.Queue(maxsize=12)
        self._thread = threading.Thread(target=self._writer, name="rec", daemon=True)
        self._thread.start()
        self.t0 = self._next_t = time.perf_counter()
        self.frames = 0
        self.error = None
        self.active = True
        self.log_event(f"REC: запись → {self.path.name}")

    def stop(self):
        if not self.active:
            return
        self.active = False
        with self._wav_lock:
            self._wav.close()
            self._wav = None
        self._q.put(None)
        threading.Thread(target=self._finish, name="rec-mux", daemon=True).start()

    def _finish(self):
        self._thread.join(timeout=30)
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=60)
            r = subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", str(self._video), "-i", str(self._audio),
                                "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart",
                                str(self.path)], capture_output=True, creationflags=NO_WINDOW, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode("utf-8", "replace")[-400:])
            self._video.unlink(missing_ok=True)
            self._audio.unlink(missing_ok=True)
            self.log_event(f"REC: сохранено {self.path} ({self.frames / FPS:.0f} с)")
        except Exception as e:
            self.error = str(e)
            log.exception("запись не склеена")
            self.log_event(f"REC: ошибка склейки — части остались в {self._video.parent}")

    # ------------------------------------------------------------- видео
    def tick(self, renderer, now):
        """Из кадра GL (контекст текущий): по часам — кадр 30 к/с; при отставании кадр повторяется."""
        if not self.active:
            if self._pbo:
                self.release()
            return
        if renderer.size != self.size:
            self.stop()
            self.log_event("REC: разрешение изменилось — запись остановлена")
            return
        if now < self._next_t:
            return
        n = 1 + int((now - self._next_t) * FPS)
        self._next_t += n / FPS
        if not self._pbo:
            w, h = self.size
            self._pbo = [renderer.ctx.buffer(reserve=w * h * 3) for _ in range(2)]
            self._k = 0
        buf = self._pbo[self._k]
        renderer.out_fbo.read_into(buf, components=3, alignment=1)    # асинхронно в PBO
        if self._pending is not None:                                  # прошлый кадр уже готов
            data, cnt = self._pending
            self._push(data.read(), cnt)
        self._pending = (buf, n)
        self._k ^= 1

    def _push(self, data, cnt):
        for _ in range(cnt):
            try:
                self._q.put_nowait(data)
                self.frames += 1
            except queue.Full:                                         # диск не успевает — кадр пропускаем
                break

    def release(self):
        for b in self._pbo:
            b.release()
        self._pbo, self._pending = [], None

    def _writer(self):
        while True:
            data = self._q.get()
            if data is None:
                return
            try:
                self._proc.stdin.write(data)
            except Exception as e:
                self.error = str(e)
                log.exception("ffmpeg записи")
                return

    # ------------------------------------------------------------- звук
    def audio(self, block):
        """Из потока звука: блок (n, 2) float32 после эквалайзера."""
        if not self.active:
            return
        pcm = (np.clip(block, -1, 1) * 32767).astype("<i2").tobytes()
        with self._wav_lock:
            if self._wav:
                self._wav.writeframes(pcm)

    @property
    def elapsed(self):
        return time.perf_counter() - self.t0 if self.active else 0.0
