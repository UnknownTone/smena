"""Действия триггеров над сценой (таблица автора v2, SPEC §5–§6; эталон — render_demo main / element_frame).

Э — двигается сам элемент (множитель FX), С — содержимое (полосы), замены и исключения — через мастер-клок.
СИЛА канала умножает величину действия, ВКЛ выключает его. Внезапное — на ближайшую долю.
"""
import math
import random


class Actions:
    def __init__(self, clock, triggers, params):
        self.clock, self.trig, self.params = clock, triggers, params
        self.rng = random.Random(11)
        self.bass_s = self.side_s = self.cent_s = 0.5
        self.pwm_w = 0.0
        self.last_drop = -1e9          # доля последнего обрыва
        self.pwm_display = None        # для анимации фейдера PWM
        self._entry_seen = {"bottom": 0.0, "top": 0.0}
        self._t = None
        self.next_news = None          # доля следующей газетной вырезки (SPEC §4.6)
        self._news_now = False

    def g(self, n):
        """СИЛА канала (0..2), 0 если выключен."""
        p = self.params
        return p[f"t{n}.gain"] / 100.0 if p[f"t{n}.on"] else 0.0

    def instances(self):
        c = self.clock
        return [(i, r) for i, r in ((c.past, "past"), (c.master, "master"), (c.future, "future")) if i]

    # ------------------------------------------------------------------ кадр
    def update(self, now):
        clk, tr = self.clock, self.trig
        if not clk.master:
            return
        dt = 0.0 if self._t is None else min(0.1, now - self._t)
        self._t = now
        beat = clk.beat
        lv = tr.levels
        # входы мастер-клока
        clk.ks = tr.ks
        clk.stepped = lv[6] * self.g(6) > 0.55                     # №6 почерк
        clk.circular = self.g(20) > 0                              # №20 круговая замена
        d = {"high": lv[10] * self.g(10), "lowmid": lv[11] * self.g(11), "mid": lv[16] * self.g(16),
             "lfo": lv[17] * self.g(17)}
        clk.levels = lambda d=d: d
        for half in ("bottom", "top"):                             # въезд future — на атаки своей половины
            if tr.entry[half] > self._entry_seen[half]:
                self._entry_seen[half] = tr.entry[half]
                clk.entry_trigger[half] = True
        while tr.events:
            n, t, mag = tr.events.popleft()
            self.handle(n, mag, now, beat)
        self._news(beat)
        self.continuous(now, dt, beat)

    # ------------------------------------------------------- газетные вырезки
    def news_now(self):
        """Ручной запуск (кнопка ▶ ГАЗЕТА) — на ближайшей сильной доле."""
        self._news_now = True

    def _news(self, beat):
        """Редкий эффект газетных вырезок: случайно, в среднем раз в N тактов (ручка «ГАЗЕТА»; 0 — выкл)."""
        clk = self.clock
        n_bars = self.params["news"]
        if n_bars <= 0 and not self._news_now:
            self.next_news = None
            return
        if self.next_news is None and n_bars > 0:
            self.next_news = clk.bc.next_downbeat(beat + 4 * max(4, n_bars) * self.rng.uniform(0.67, 1.33))
        if not self._news_now and (self.next_news is None or beat < self.next_news):
            return
        start = clk.bc.next_downbeat(beat - 1e-6)
        cand = [e for inst, role in self.instances() if role != "past" for e in inst.elements
                if e.present(beat) and e.gone_from is None and e.news(beat) == 0]
        if cand:
            k = min(len(cand), self.rng.choice((1, 1, 1, 2, 2, 3)))
            # чаще — крупные элементы (вырезку лучше видно), но не только
            cand.sort(key=lambda e: -(e.w * e.h) * self.rng.uniform(0.3, 1.0))
            length = self.rng.choice((4.0, 8.0))                    # 1–2 такта
            for e in cand[:k]:
                e.news_from, e.news_len = start, length
                e.news_tilt = self.rng.choice((-1, 1)) * self.rng.uniform(3.0, 6.0)
            self.trig.eng.log_event(f"газетные вырезки: {k} элем. на {int(length // 4)} такт(а)")
        self._news_now = False
        self.next_news = None if n_bars <= 0 else \
            clk.bc.next_downbeat(beat + 4 * max(4, n_bars) * self.rng.uniform(0.67, 1.33))

    # --------------------------------------------------------------- события
    def handle(self, n, mag, now, beat):
        clk = self.clock
        b0 = math.ceil(beat - 1e-6)                                # на ближайшую долю
        if n == 1:          # смена части: все мерцают → 1 доля только фон master → master въезжает обратно
            for inst, role in self.instances():
                k = 0
                for e in inst.elements:
                    if not e.present(beat) or e.gone_from is not None:
                        continue
                    e.flicker_from = b0
                    if role == "master":
                        e.t_in, e.t_out = b0 + 2, None
                    elif role == "past":
                        e.gone_from = b0 + 1
                    else:
                        e.t_in = b0 + 3 + k
                        k += 1
            clk.past_queue = [e for e in clk.past_queue if e.gone_from is None]
        elif n == 12:       # гармония: past и future мерцают и исчезают; future въедет заново
            for inst, role in self.instances():
                if role == "master":
                    continue
                k = 0
                for e in inst.elements:
                    if not e.present(beat) or e.gone_from is not None:
                        continue
                    e.flicker_from = b0
                    if role == "past":
                        e.gone_from = b0 + 1
                    else:
                        e.t_in = b0 + 3 + k
                        k += 1
            clk.past_queue = [e for e in clk.past_queue if e.gone_from is None]
        elif n == 4:        # акцент: встряска всех (сильный) или части
            amp = (4 + min(10.0, max(0.0, mag - 6))) * self.g(4)
            for inst, _ in self.instances():
                for e in inst.elements:
                    if mag > 12 or self.rng.random() < 0.5:
                        a = self.rng.uniform(0, 2 * math.pi)
                        e.shake = (now, math.cos(a), math.sin(a), amp)
        elif n == 18:       # 2–6 кГц: короткий отскок верхних
            for inst, _ in self.instances():
                for e in inst.elements:
                    if e.half == "top":
                        e.bounce = now
        elif n == 7:        # тональность: мигание элемента master
            cand = [e for e in clk.master.elements if e.present(beat)]
            if cand and self.g(7) > 0:
                self.rng.choice(cand).blink_from = math.ceil(beat * 2) / 2
        elif n == 9:        # суббас: замена нижнего past
            if self.g(9) > 0:
                clk.extra_replace("bottom")
        elif n == 19:       # громкость: замена верхнего past
            if self.g(19) > 0:
                clk.extra_replace("top")
        elif n == 13:       # хэты: смена паттерна полос по Y
            for inst, _ in self.instances():
                for e in inst.elements:
                    if e.pol == "Y":
                        e.new_pattern()
        elif n == 14:       # ритмичность: быстрая замена содержимого нижних; скорость — по крутизне
            k = 1 + 6 * min(1.0, mag / 0.3) * self.g(14)
            for inst, _ in self.instances():
                for e in inst.elements:
                    if e.half == "bottom":
                        e.boost = max(e.boost, k)
        elif n == 15:       # обрыв: PWM для past — ширина к 100%, затем к положению ручки
            self.pwm_w = 1.0
            self.last_drop = beat

    # ---------------------------------------------------------- непрерывное
    def continuous(self, now, dt, beat):
        tr, p = self.trig, self.params
        lv = tr.levels
        fx = p["fx"] / 100.0 * self.clock.dyn             # ОРИГИНАЛ ниже 50 — больше движения
        if dt > 0:
            self.bass_s += (lv[2] - self.bass_s) * dt / 0.6
            self.side_s += (lv[5] - self.side_s) * dt / 1.5
            self.cent_s += (lv[3] - self.cent_s) * dt / 0.8
        period = 60.0 / tr.eng.beat.grid_bpm
        # №15 PWM
        base = p["pwm"] / 100.0
        if dt > 0:
            self.pwm_w += (base - self.pwm_w) * (1 - math.exp(-dt / (2 * period)))
        pwm_on = beat - self.last_drop < 4 and self.g(15) > 0
        self.pwm_display = self.pwm_w * 100 if pwm_on else None
        hide_past = pwm_on and (beat % 1.0) < self.pwm_w
        W = self.clock.W
        g2, g3, g5, g8, g13, g18 = (self.g(n) for n in (2, 3, 5, 8, 13, 18))
        jitter = lv[13] * g13 > 0.85
        decay = math.exp(-dt / period) if dt > 0 else 1.0
        for inst, role in self.instances():
            for e in inst.elements:
                px = e.px_scale                                  # пиксели эталона → холста
                dx = dy = ang = 0.0
                if e.half == "bottom":
                    dx += W * 0.012 * (self.bass_s - 0.5) * 2 * g2 * fx           # №2 бас → X
                    e.vib = 3 * lv[8] * g8                                         # №8 вибрация содержимого
                else:
                    dx += W * 0.010 * (self.side_s - 0.5) * 2 * g5 * fx           # №5 стерео → X
                    ang = 6.0 * max(0.0, self.cent_s - 0.45) / 0.55 * g3 * fx     # №3 яркость → по часовой
                    if now - e.bounce < 0.4:                                       # №18 отскок
                        dy -= 14 * px * math.exp(-(now - e.bounce) / 0.12) * g18 * fx
                    if jitter:                                                     # №13 дрожь верхних
                        dx += self.rng.uniform(-2, 2) * px * g13 * fx
                        dy += self.rng.uniform(-2, 2) * px * g13 * fx
                    e.vib = 0.0
                t0, sx, sy, amp = e.shake                                          # №4 встряска
                if now - t0 < 0.4:
                    k = amp * px * fx * math.exp(-(now - t0) / 0.1) * math.sin(2 * math.pi * 16 * (now - t0))
                    dx += sx * k
                    dy += sy * k
                e.dx, e.dy, e.ang = dx, dy, ang
                e.hidden = role == "past" and hide_past
                if e.boost > 1.0:                                                  # №14 затухает за ~долю
                    e.boost = 1.0 + (e.boost - 1.0) * decay
