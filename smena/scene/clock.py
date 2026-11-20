"""Мастер-клок (SPEC §2.3–2.5, §4.3–4.4; эталон — render_demo.schedule), в реальном времени.

Время сцены — **доли**: свой непрерывный счётчик, который мягко подстраивается под фазу BeatTracker.
Смена темпа растягивает расписание без скачков; граница цикла всегда на сильной доле; всё, что по сетке,
делается по предсказанию (без задержки).

Цикл фото N (доли от начала цикла c0):
  0         фон мгновенно → N (master), его элементы уже на местах
  0 … P     уходят элементы past: круговая замена по часовой, шаг на долю, свинг, пропуск по ks;
            в P — крайний срок: оставшиеся уходят принудительно
  P … P+S   моно-показ master
  P+S … T   последовательно въезжают элементы future (по слотам; триггеры — раньше слота, M3)
  T         смена фона, роли сдвигаются

0.1.2: вид смены кадра (рез / элементы / наплыв / шторка / мерцание / через чёрное), квант, порядок фото,
переход к фото по номеру (⏮, ◀), пауза (ПУСК / СТОП), «ОРИГИНАЛ» / «СИЛА ЭФФ.» / «ЭЛЕМЕНТЫ» — в draw_list.
Значения фейдеров вкладки ФЕЙДЕРЫ — через Modulation (провода LFO).
"""
import math
import random

from smena.scene.elements import PhotoInstance

SWING = 1 / 3              # чётные шаги круговой замены опаздывают (≈ 2:1)
LFO_DEFAULT = 0.3          # пока нет признака №17 (M3)
CUT, ELEM, DISSOLVE, WIPE, FLICKER, BLACK = range(6)    # виды смены кадра (TRANSITIONS)


def smooth(u, curve):
    """Кривая перехода: curve 0 — линейно, 1 — мягкая S (smootherstep)."""
    u = min(max(u, 0.0), 1.0)
    s = u * u * u * (u * (6 * u - 15) + 10)
    return u + (s - u) * curve


class BeatClock:
    """Непрерывный счётчик долей с подстройкой фазы (ФАПЧ) к BeatTracker."""

    def __init__(self, tracker):
        self.tr = tracker
        self.beat = 0.0
        self.delta = 0          # целая разница между долями трекера и сцены
        self._t = None

    def update(self, now):
        pos = self.tr.position(now)
        if self._t is None:
            self.beat = pos["beat_f"]
        else:
            dt = max(0.0, now - self._t)
            step = dt * self.tr.grid_bpm / 60.0
            err = (pos["beat_f"] - (self.beat + step) + 0.5) % 1.0 - 0.5
            step += err * min(1.0, dt * 3.0)
            self.beat += max(step, 0.0)      # счётчик никогда не идёт назад
        self._t = now
        self.delta = round(pos["beat_f"] - self.beat)
        return self.beat

    def in_bar(self, b):
        return (math.floor(b + 1e-6) + self.delta - self.tr.bar_offset) % 4

    def next_downbeat(self, b):
        """Ближайшая сильная доля не раньше b."""
        n = math.ceil(b - 1e-6)
        while self.in_bar(n) != 0:
            n += 1
        return n

    def last_downbeat(self, b):
        n = math.floor(b + 1e-6)
        while self.in_bar(n) != 0:
            n -= 1
        return n


class MasterClock:
    def __init__(self, engine, params, size, mod):
        self.engine, self.params, self.mod = engine, params, mod
        self.rng = random.Random(5)
        self.paused = False
        self._resume = False
        self.anchor = None                  # первая смена — точка отсчёта для кванта «4 такта»
        self.tr_kind = ELEM                 # вид текущей смены кадра
        self.tr_dur = 4.0
        self.tr_curve = 0.5
        self._dir = 1                       # порядок «туда-обратно»
        self.effect = 1.0                   # сила эффекта на кадр (ОРИГИНАЛ × СИЛА ЭФФ.)
        self.dyn = 1.0                      # множитель динамики (ОРИГИНАЛ < 50)
        self.gran = 32                      # сколько элементов фото двигаются
        self.bright = 1.0                   # ЯРКОСТЬ (через ОБРАЗ: резко / плавно)
        self.img = None                     # ОБРАЗ плавно: текущие значения, к которым тянутся
        self.img_target = None              # … и цель, взятая на смене фото
        self._img_beat = None
        self.flash = False                  # вспышка оригинала в конце этого фото
        self.flash_k = 0.0                  # сила вспышки на кадр (0..1) — белое и «элементы на места»
        self.c0 = 0.0
        self.bc = BeatClock(engine.beat)
        self.W, self.H = size
        self.fill = True                    # фото на весь кадр (обрезка краёв) / целиком с подложкой
        self.entries = []
        self.pending = None                 # новый набор фото — ждёт ближайшей смены фото
        self.past = self.master = self.future = None
        self._seed = 0
        self.beat = 0.0
        self._now = None
        # входы для триггеров (scene/actions.py)
        self.ks = 1
        self.stepped = False                # №6 почерк: ступенчатый
        self.circular = True                # №20 включён — круговая замена шагами по долям
        self.entry_trigger = {"bottom": False, "top": False}
        self.levels = lambda: {}
        self.log = engine.log_event
        self._step_acc = 0.0
        self._last_q = None

    # ------------------------------------------------------------- набор фото
    def set_library(self, entries):
        """Новый список фото. Во время показа — применяется на ближайшей смене фото (без обрыва):
        тот же набор (дополнен) — показ продолжается с текущего фото, другой набор — с первого фото."""
        ready = [e for e in entries if e.ready]
        if self.master is None or not ready:
            if ready or self.master is None:
                self.entries = ready
                self.past = self.master = self.future = None
            self.pending = None
            return
        self.pending = ready
        self.log(f"набор фото: {len(ready)} шт. — со следующей смены фото")

    def _apply_pending(self):
        """Подменить список на смене фото; вернуть индекс следующего future в новом списке."""
        new, self.pending = self.pending, None
        names = [e.name for e in new]
        cur = self.future.name if self.future else self.master.name
        self.entries = new
        if cur in names:                      # тот же набор — продолжаем по порядку
            return names.index(cur) + 1
        return 0                              # другой набор — с первого фото

    def set_fill(self, on):
        """Фото на весь кадр / целиком — раскладка пересобирается с текущего фото."""
        if on != self.fill:
            self.fill = on
            if self.master is not None:
                self.goto(self.master.index, keep_past=False)

    def set_size(self, size):
        if tuple(size) != (self.W, self.H):
            self.W, self.H = size
            self.past = self.master = self.future = None     # перестроить раскладку

    def _new(self, index):
        self._seed += 1
        n = len(self.entries)
        return PhotoInstance(self.entries[index % n], index % n, self.W, self.H, self._seed, self.fill)

    def _start(self, beat):
        self.master = self._new(0)
        for e in self.master.elements:
            e.t_in = -1e9
        self.past = None
        self.future = self._new(1) if len(self.entries) > 1 else None
        self._begin_cycle(self.bc.last_downbeat(beat))
        self.log(f"мастер-клок: старт, master {self.master.name}")

    # ------------------------------------------------------------------ цикл
    def _begin_cycle(self, c0):
        p = self.params
        self.c0 = c0
        if self.anchor is None:
            self.anchor = c0
        morph = p["tr.on"]
        self.T = max(4, int(round(self.mod.v("T") if morph else p["T"]))) * 4
        self.P = p["P"] * self.T
        self.S = min(p["S"] * 4, 0.3 * self.T)      # как в эталоне: при малом T окну въезда остаётся место
        self.entry = p["entry"]
        q = int(round(p["tr.quant"])) if morph else 1          # МОРФИНГ выкл — как раньше: на такт
        if q == 0:                                    # на долю
            self.c_end = math.ceil(c0 + self.T - 1e-6)
        else:                                         # на такт / на каждые 4 такта от первой смены
            self.c_end = self.bc.next_downbeat(c0 + self.T - 2)
            while q == 2 and (self.c_end - self.anchor) % 16 > 1e-6 and self.c_end - c0 < self.T + 16:
                self.c_end = self.bc.next_downbeat(self.c_end + 1)
        # уход past: круговая замена по часовой
        self.past_queue = [e for e in self.past.clockwise() if e.t_out is None and e.gone_from is None] \
            if self.past else []
        self.step = 0
        self.next_step = c0
        # въезд future: слоты окна [a, b], последний успевает встать до смены фона
        a = c0 + self.P + self.S
        b = max(c0 + self.T - self.entry, a + 1)
        self.order = self.future.clockwise() if self.future else []
        n = len(self.order)
        self.slots = [a + (i + 0.5) / n * (b - a) for i in range(n)]
        self.win_a, self.win_b = a, b
        # до 32 элементов (SPEC §3.1): если по одному в долю не укладываются — по 1/2 или 1/4 доли
        win = max(b - a, 1.0)
        self.entry_step = 1.0 if n <= win else (0.5 if n <= 2 * win else 0.25)
        self.next_i = 0
        self.last_in = a - self.entry_step
        # круговая замена: сколько past уходит за шаг, чтобы успеть до крайнего срока P
        self.per_step = max(1, math.ceil(len(self.past_queue) / max(1.0, self.P - 1)))
        # вспышка оригинала (фейдер ВСПЫШКА): решается на смене фото, случается в его последнюю долю
        self.flash = self.rng.random() * 100 < self.mod.v("orig.flash")
        # ОБРАЗ плавно: новые положения фейдеров берутся только на смене фото
        self.img_target = self._img_raw()

    def _pick_transition(self):
        """Вид смены кадра: фейдер ВИД (с LFO), с вероятностью «СЛУЧАЙ» — любой."""
        if not self.params["tr.on"]:                  # МОРФИНГ выкл — как в первых версиях
            self.tr_kind, self.tr_dur, self.tr_curve = ELEM, 0.0, 0.5
            return
        if self.rng.random() * 100 < self.params["tr.rand"]:
            self.tr_kind = self.rng.randrange(6)
        else:
            self.tr_kind = int(round(self.mod.v("tr.kind")))
        self.tr_dur = max(0.0, self.mod.v("tr.dur"))
        self.tr_curve = self.mod.v("tr.curve") / 100.0

    def _next_index(self, i):
        """Следующее фото по фейдеру ПОРЯДОК: по папке / случайно / туда-обратно."""
        n = len(self.entries)
        order = int(round(self.params["tr.order"])) if self.params["tr.on"] else 0
        if n <= 1:
            return 0
        if order == 1:
            j = self.rng.randrange(n - 1)
            return j + 1 if j >= i else j
        if order == 2:
            if not 0 <= i + self._dir < n:
                self._dir = -self._dir
            return i + self._dir
        return (i + 1) % n

    def _rotate(self):
        c0 = self.c_end
        self.past, self.master = self.master, self.future
        self._pick_transition()
        for e in self.past.elements:            # ждали возврата после №1 — уже не вернутся
            if e.t_in is not None and e.t_in > c0:
                e.gone_from = c0
            if self.tr_kind == CUT:             # рез: элементы старого фото исчезают вместе с ним
                e.gone_from = c0
        for e in self.master.elements:          # не успевшие въехать — въезжают сейчас
            if e.t_in is None:
                e.t_in = c0
        nxt = self._apply_pending() if self.pending else self._next_index(self.master.index)
        self.future = self._new(nxt) if len(self.entries) > 0 else None
        self._begin_cycle(c0)
        self.log(f"смена фото: master {self.master.name} ({self.master.index + 1}/{len(self.entries)})")

    def goto(self, index, keep_past=True):
        """Сразу к фото №index (⏮ — к первому, ◀ — к предыдущему): его элементы на местах,
        элементы прежнего фото уходят как past."""
        if not self.entries or self.master is None:
            return
        n = len(self.entries)
        old = self.master
        self.master = self._new(index % n)
        for e in self.master.elements:
            e.t_in = -1e9
        self.past = old if keep_past else None
        if self.past:
            for e in self.past.elements:
                if e.t_in is None or e.t_in > self.beat:
                    e.gone_from = self.beat
        self.future = self._new(self._next_index(self.master.index)) if n > 1 else None
        self.tr_kind = ELEM
        self._begin_cycle(math.floor(self.beat))
        self.log(f"к фото {self.master.index + 1}/{n}: {self.master.name}")

    def set_paused(self, on):
        """СТОП — кадр замирает; ПУСК — показ продолжается с того же фото (новый цикл)."""
        if self.paused and not on:
            self._resume = True
        self.paused = on

    def shutter(self):
        """ЗАТВОР: future становится master на ближайшей сильной доле."""
        if not self.future:
            return
        b = math.ceil(self.beat)
        self.c_end = self.bc.next_downbeat(self.beat + 0.5)
        for e in self.order[self.next_i:]:
            e.t_in = b
        self.next_i = len(self.order)
        for e in self.past_queue:
            e.t_out = b
        self.past_queue = []
        self.log("ЗАТВОР: следующее фото на сильную долю")

    # ------------------------------------------------------------------ кадр
    def update(self, now):
        beat = self.bc.update(now)
        dt = 0.0 if self._now is None else min(0.1, now - self._now)
        self._now, self.beat = now, beat
        if not self.entries:
            return
        if self.master is None:
            self._start(beat)
        if self._resume:
            self._resume = False
            self.goto(self.master.index, keep_past=False)
        if self.pending and self.future is None:          # было одно фото — новый набор сразу идёт как future
            self.future = self._new(self._apply_pending())
            self.order = []
        if self.future is not None and beat >= self.c_end:
            self._rotate()
        self._effect()
        p_flick = self.params["flicker_in"] / 100.0       # «МЕРЦ»: доля появлений мерцанием на месте
        for inst in (self.past, self.master, self.future):
            if inst:
                for e in inst.elements:
                    e.flick_in = e.appear_u < p_flick
        self._past_steps(beat)
        self._future_entries(beat)
        self.entry_trigger = {"bottom": False, "top": False}
        self._strips(dt)

    IMG_KEYS = ("orig", "strength", "gran", "bright")

    def _img_raw(self):
        return {k: self.mod.v(k) for k in self.IMG_KEYS}

    def _image(self):
        """Значения ОБРАЗА: резко — сразу как на фейдерах; плавно — цель берётся на смене фото,
        значения тянутся к ней мягко (≈ 2 доли)."""
        raw = self._img_raw()
        if not self.params["img.smooth"] or self.img is None:
            self.img = dict(raw)
            self.img_target = dict(raw)
            self._img_beat = self.beat
            return self.img
        db = max(0.0, self.beat - (self._img_beat if self._img_beat is not None else self.beat))
        self._img_beat = self.beat
        k = 1.0 - math.exp(-db / 2.0)
        tgt = self.img_target or raw
        for key in self.IMG_KEYS:
            self.img[key] += (tgt[key] - self.img[key]) * k
        return self.img

    def _effect(self):
        """ОРИГИНАЛ и СИЛА ЭФФ. → сила эффекта 0..1 и множитель динамики; ЭЛЕМЕНТЫ → сколько двигаются;
        вспышка оригинала — в последнюю долю фото (не дольше 0.45 с)."""
        im = self._image()
        orig = im["orig"]
        k_orig = min(1.0, (100.0 - orig) / 50.0)
        boost = max(0.0, (50.0 - orig) / 50.0)            # ниже 50: все элементы и больше движения
        self.effect = k_orig * im["strength"] / 100.0
        self.dyn = 1.0 + boost
        g = im["gran"]
        self.gran = int(round(g + (32 - g) * boost))
        self.bright = im["bright"] / 100.0
        self.flash_k = 0.0
        if self.flash and self.future is not None:
            bps = self.engine.beat.grid_bpm / 60.0
            L = min(self.mod.v("orig.hold") * bps, 0.5 * self.T)       # ПОКАЗ: секунды → доли, не больше ½ цикла
            r = self.beat - (self.c_end - L)
            if 0.0 <= r < L:
                w = min(L, 0.35 * bps)                                  # белая вспышка — первые ≤ 0.35 с
                self.flash_k = max(0.0, 1.0 - r / w)
                self.effect *= max(0.0, 1.0 - min(1.0, r / (0.12 * w)))  # элементы встают на места

    def transition(self):
        """(вид, u 0..1) во время смены кадра с фоном (наплыв, шторка, мерцание, через чёрное), иначе None."""
        if self.tr_kind not in (DISSOLVE, WIPE, FLICKER, BLACK) or not self.past or self.tr_dur <= 0:
            return None
        u = (self.beat - self.c0) / self.tr_dur
        if not 0 <= u < 1:
            return None
        return self.tr_kind, smooth(u, self.tr_curve)

    def extra_replace(self, half):
        """№9 суббас / №19 громкость: дополнительная замена нижнего / верхнего элемента past (на четверть доли)."""
        for e in self.past_queue:
            if e.half == half:
                self.past_queue.remove(e)
                e.t_out = math.ceil(self.beat * 4) / 4
                return True
        return False

    def _past_steps(self, beat):
        deadline = self.c0 + self.P
        while self.past_queue and beat >= self.next_step and self.next_step < deadline:
            if self.circular and self.step % max(1, self.ks) == 0:
                for _ in range(min(self.per_step, len(self.past_queue))):
                    e = self.past_queue.pop(0)
                    e.t_out = self.next_step + (SWING if self.step % 2 else 0.0)
            self.step += 1
            self.next_step += 1
        if self.past_queue and beat >= deadline:          # крайний срок сильнее ks и шагов
            for e in self.past_queue:
                e.t_out = deadline
            self.past_queue = []

    def _future_entries(self, beat):
        st = self.entry_step                              # не чаще одного элемента в долю (или в 1/2, 1/4 доли)
        snap = lambda x: math.ceil(x / st - 1e-6) * st
        while self.next_i < len(self.order):
            e = self.order[self.next_i]
            earliest = self.last_in + st
            due = snap(max(self.slots[self.next_i], earliest))
            trig = self.entry_trigger.get(e.half) and beat >= self.win_a and beat >= earliest
            if not (beat >= due or trig):
                break
            e.t_in = min(snap(beat) if trig else due, max(self.win_b, earliest))
            self.last_in = e.t_in
            self.next_i += 1
            self.entry_trigger[e.half] = False            # одна атака — один въезд

    def _strips(self, dt):
        """Содержимое элементов: полосы вдоль полярности (эталон — element_frame)."""
        if dt <= 0:
            return
        if self.stepped:                  # №6 ступенчатый почерк: полосы шагают по четвертям доли
            q = math.floor(self.beat * 4)
            self._step_acc += dt
            if q == self._last_q:
                return
            self._last_q = q
            dt, self._step_acc = self._step_acc, 0.0
        else:
            self._step_acc = 0.0
        lv = self.levels()
        f = self.engine.features.level
        lfo = lv.get("lfo", LFO_DEFAULT)
        amp = self.params["strips"] / 100.0 * self.dyn
        spread = self.params["spread"]
        phase = self.beat % 1.0
        for inst in (self.past, self.master, self.future):
            if not inst:
                continue
            for e in inst.elements:
                if not e.present(self.beat):
                    continue
                if e.pol == "Y":
                    drive = lv.get("high", f["high"])                   # №10 верх → по Y
                else:
                    drive = lv.get("lowmid", f["lowmid"]) if e.central else 0.5 * lfo   # №11 → по X
                speed = (8 + 90 * drive) * (0.5 + 1.2 * lfo) / max(1, self.ks)        # №17 / ks
                if e.id % 2 == 0:                                       # №16 пульс паттерна
                    speed *= 1 + 0.8 * lv.get("mid", f["mid"]) * max(0.0, math.cos(2 * math.pi * phase)) ** 4
                e.advance_strips(speed * amp, dt, spread)

    # ------------------------------------------------------------------ вывод
    def draw_list(self):
        """[(экземпляр, элемент, x, y, угол, газета 0..1, непрозрачность, сила полос)] в порядке
        past → master → future; газетные вырезки — поверх остальных (наклеены сверху).

        Сила эффекта E (ОРИГИНАЛ × СИЛА ЭФФ.): элементы master тянутся к своим местам, полосы и повороты
        затихают, past и future гаснут; при E = 0 — фото как есть. Элементы сверх «ЭЛЕМЕНТЫ» стоят на месте
        как часть фото master (у past и future их не видно)."""
        out, news = [], []
        E = self.effect
        if not self.params["img.alpha"]:
            return self._draw_solid(E)
        for inst in (self.past, self.master, self.future):
            if not inst:
                continue
            is_master = inst is self.master
            for e in inst.elements:
                active = e.rank < self.gran
                vis = active and e.visible(self.beat)
                if is_master and (not active or not vis):
                    a = 1.0 if not active else 1.0 - E           # на месте, как часть фото
                    if a > 0.01 and e.gone_from is None:
                        out.append((inst, e, e.home[0], e.home[1], 0.0, 0.0, a, 0.0))
                    continue
                if not vis:
                    continue
                x, y = e.position(self.beat, self.entry, self.stepped)
                k = e.news(self.beat) * E
                if is_master:
                    x, y = e.home[0] + (x - e.home[0]) * E, e.home[1] + (y - e.home[1]) * E
                    a = 1.0
                else:
                    a = E
                if a <= 0.01:
                    continue
                (news if k > 0 else out).append((inst, e, x, y, (e.ang + e.news_tilt * k) * E, k, a, E))
        return out + news

    def _draw_solid(self, E):
        """Без прозрачности: сила эффекта уменьшает число элементов в игре (крупные — дольше всех) и движение;
        элементы вне игры у master стоят на местах как часть фото, у past и future — не видны."""
        out, news = [], []
        n_play = int(round(self.gran * E))
        for inst in (self.past, self.master, self.future):
            if not inst:
                continue
            is_master = inst is self.master
            for e in inst.elements:
                vis = e.rank < n_play and e.visible(self.beat)
                if not vis:
                    if is_master and e.gone_from is None and (e.rank >= n_play or E < 0.5):
                        out.append((inst, e, e.home[0], e.home[1], 0.0, 0.0, 1.0, 0.0))
                    continue
                x, y = e.position(self.beat, self.entry, self.stepped)
                k = e.news(self.beat) * E
                if is_master:
                    x, y = e.home[0] + (x - e.home[0]) * E, e.home[1] + (y - e.home[1]) * E
                (news if k > 0 else out).append((inst, e, x, y, (e.ang + e.news_tilt * k) * E, k, 1.0, E))
        return out + news

    def needed(self):
        """Фото, которые нужны сейчас и следующими (для фоновой подгрузки)."""
        if not self.entries:
            return []
        i = self.master.index if self.master else 0
        n = len(self.entries)
        return [self.entries[(i + k) % n] for k in (-1, 0, 1, 2) if n > 0]

    def phase_name(self):
        if not self.master:
            return "—"
        r = self.beat - self.c0
        if r < self.P and self.past:
            return "past+master"
        if r < self.P + self.S:
            return "моно master"
        return "въезд future"

    def hud(self):
        r = self.beat - self.c0 if self.master else 0
        return {"past": self.past.name if self.past else "—",
                "master": self.master.name if self.master else "—",
                "future": self.future.name if self.future else "—",
                "cycle": f"{self.phase_name()} {r:4.1f}/{self.T if self.master else 0}"
                         + (" · СТОП" if self.paused else ""),
                "ks": self.ks}
