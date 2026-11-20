"""Захват звука: loopback выхода (по умолчанию) или вход звуковой карты, блоки по 512 сэмплов.

Программа только слушает — ничего не воспроизводит (docs/build/03_AUDIO_CAPTURE.md).
COM: QApplication создаётся раньше, главный поток остаётся STA (нужно Qt-диалогам);
soundcard импортируется лениво — в потоке захвата или после QApplication (проверено, работает).
Тестовый режим «файл» — исключение: программа сама играет файл (репетиции без Traktor).
0.1.2: эквалайзер и громкость (audio/eq.py) — на звук, который играет SMENA, и на звук записи REC (`rec_tap`).
"""
import logging
import re
import subprocess
import threading
import time
import warnings
from collections import deque
from pathlib import Path

import numpy as np

from smena.audio.beat import BeatTracker
from smena.audio.eq import Eq
from smena.audio.features import HOP, Features
from smena.runtime import IS_MAC

log =logging.getLogger("smena.audio")

SR = 48000                # WASAPI / CoreAudio сами приводят частоту; 48 кГц — частота большинства устройств
SILENCE_HINT_S = 5.0      # после стольких секунд тишины — подсказка про ASIO


FILE_BLOCKS = 4           # режим «файл»: блоков по 512 на одну порцию плееру (~43 мс)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_duration(path):
    """Длительность файла в секундах (по выводу ffmpeg), 0 — не удалось."""
    try:
        p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True,
                           text=True, errors="replace", creationflags=NO_WINDOW, timeout=10)
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
        if m:
            return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    except Exception:
        log.exception("длительность файла не определена")
    return 0.0


VIRTUAL = ("blackhole", "loopback audio", "soundflower", "vb-cable")   # виртуальные «кабели» звука системы


def _is_virtual(name):
    return any(v in name.lower() for v in VIRTUAL)


def _mac_virtual(sc):
    """macOS: виртуальное устройство (BlackHole и т.п.), куда направлен звук системы, или None."""
    for m in sc.all_microphones():
        if _is_virtual(m.name):
            return m
    return None


def _sc():
    import soundcard
    # soundcard при импорте сам включает свои предупреждения — глушим после импорта
    # («data discontinuity» в loopback бывает при тишине и безвредна)
    warnings.filterwarnings("ignore", category=soundcard.SoundcardRuntimeWarning)
    return soundcard


class AudioEngine:
    def __init__(self):
        self.sr = SR
        self.features = Features(SR)
        self.beat = BeatTracker(SR / HOP)
        self.events = deque(maxlen=200)     # (номер, время, текст) — журнал для вкладки ЗВУК
        self._seq = 0
        self.triggers = None                # audio/triggers.py — подключается после создания Params
        self.eq = Eq(SR)
        self.rec_tap = None                 # REC: функция(блок (n, 2) после эквалайзера) или None

        self.device_id = None
        self.device_name = ""
        self.file_path = None      # не None — играет тестовый файл
        self.file_pos = 0.0
        self.file_dur = 0.0
        self.running = False
        self.error = None
        self.silent_since = time.perf_counter()
        self.last_block_t = 0.0
        self.blocks = 0
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ устройства
    @staticmethod
    def list_devices():
        """[(id, подпись, это_loopback)] — выходы (loopback) и входы звуковых карт."""
        out = []
        try:
            sc = _sc()
            mics = sc.all_microphones() if IS_MAC else sc.all_microphones(include_loopback=True)
            for m in mics:
                loop = bool(getattr(m, "isloopback", False)) or _is_virtual(m.name)
                out.append((m.id, ("🔊 " if loop else "🎤 ") + m.name, loop))
        except Exception:
            log.exception("список устройств не получен")
        return out

    @staticmethod
    def default_label():
        try:
            if IS_MAC:
                v = _mac_virtual(_sc())
                return ("🔊 по умолчанию: " + v.name) if v else "🎤 по умолчанию: " + _sc().default_microphone().name
            return "🔊 по умолчанию: " + _sc().default_speaker().name
        except Exception:
            return "🔊 выход по умолчанию"

    def log_event(self, text):
        self._seq += 1
        self.events.append((self._seq, time.time(), text))
        log.info(text)

    # --------------------------------------------------------------- захват
    def start(self, device_id=None):
        """Запуск или переключение устройства — без перезапуска программы."""
        self.stop()
        self.device_id = device_id
        self.file_path = None
        self._run(self._loop)

    def start_file(self, path, offset=0.0):
        """Тестовый режим «файл»: программа сама играет аудиофайл на выход по умолчанию и анализирует его."""
        self.stop()
        self.file_path = str(path)
        self.file_pos = float(offset)
        self.file_dur = probe_duration(self.file_path)
        self._run(self._file_loop)

    def _run(self, target):
        self.error = None
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=target, name="audio", daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.5)
        self._thread = None

    def _loop(self):
        try:
            sc = _sc()
            if self.device_id is None and IS_MAC:          # macOS: системного loopback нет
                mic = _mac_virtual(sc) or sc.default_microphone()
            elif self.device_id is None:
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            elif IS_MAC:
                mic = sc.get_microphone(id=self.device_id)
            else:
                mic = sc.get_microphone(id=self.device_id, include_loopback=True)
            self.device_name = mic.name
            self.log_event(f"устройство: {mic.name}")
            with mic.recorder(samplerate=SR, blocksize=HOP) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=HOP)
                    self._process(data, time.perf_counter())
                    tap = self.rec_tap
                    if tap:
                        st = data[:, :2] if data.ndim == 2 and data.shape[1] >= 2 else                             np.repeat(data.reshape(-1, 1), 2, axis=1)
                        tap(self.eq.process(np.ascontiguousarray(st, np.float32)))
        except Exception as e:  # покажем в интерфейсе, а не уроним программу
            self.error = repr(e)
            log.exception("ошибка захвата звука")
        finally:
            self.running = False

    def _file_loop(self):
        """ffmpeg → f32le стерео → плеер soundcard; анализ получает те же блоки с отметкой времени,
        когда они прозвучат (через буфер плеера). В конце файла — с начала (репетиция по кругу)."""
        proc = None
        try:
            sc = _sc()
            spk = sc.default_speaker()
            name = Path(self.file_path).name
            self.device_name = f"файл: {name}"
            self.log_event(f"тестовый файл: {name} → {spk.name}")
            chunk = HOP * FILE_BLOCKS
            latency = chunk / SR      # примерная задержка буфера плеера
            with spk.player(samplerate=SR, channels=2, blocksize=chunk) as pl:
                while not self._stop.is_set():
                    proc = subprocess.Popen(
                        [ffmpeg_exe(), "-v", "error", "-ss", f"{self.file_pos:.3f}", "-i", self.file_path,
                         "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
                    got = False
                    while not self._stop.is_set():
                        raw = proc.stdout.read(chunk * 8)
                        if len(raw) < 8:
                            break
                        got = True
                        data = np.frombuffer(raw[:len(raw) // 8 * 8], np.float32).reshape(-1, 2)
                        out = self.eq.process(data)          # эквалайзер, громкость, «беззвучно»
                        pl.play(out)
                        tap = self.rec_tap
                        if tap:
                            tap(out)
                        t = time.perf_counter() + latency
                        for i in range(0, len(data) - HOP + 1, HOP):
                            self._process(data[i:i + HOP], t + i / SR)
                        self.file_pos += len(data) / SR
                    proc.kill()
                    proc = None
                    if not got:
                        raise RuntimeError("ffmpeg не прочитал файл")
                    if not self._stop.is_set():
                        self.file_pos = 0.0
                        self.log_event("тестовый файл: с начала")
        except Exception as e:
            self.error = repr(e)
            log.exception("ошибка тестового файла")
        finally:
            if proc:
                proc.kill()
            self.running = False

    def _process(self, data, now):
        """data — (HOP, каналы). Стерео сохраняется для признаков M3 (стерео-ширина S/M)."""
        if data.ndim == 2 and data.shape[1] > 1:
            mono = data[:, :2].mean(axis=1)
            side = (data[:, 0] - data[:, 1]) * 0.5
        else:
            mono = data.reshape(-1)
            side = None
        f = self.features
        f.process(mono, side)
        self.beat.push(f.flux, f.bass_flux, now)
        if self.triggers:
            self.triggers.process(now)
        if not f.silent:
            self.silent_since = now
        self.last_block_t = now
        self.blocks += 1

    # ----------------------------------------------------------------- статус
    def silence_s(self, now):
        return now - self.silent_since

    def stalled(self, now):
        """Блоки перестали приходить (устройство пропало)."""
        return self.running and self.blocks > 0 and now - self.last_block_t > 1.0
