"""Видоискатель: превью вывода (moderngl в QOpenGLWidget, общий GL-контекст) + рамка и HUD поверх.

Сцена рисуется Renderer'ом в FBO размера вывода, превью показывает этот FBO уменьшенным.
host (главное окно) даёт верхнее фото и яркость и после кадра делает выходной проход, запись, снимок калибровки.
"""
import logging

import moderngl
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from smena.render.gl import Renderer
from smena.ui.theme import THEME

log = logging.getLogger("smena.gl")


class GLPreview(QOpenGLWidget):
    ready = Signal(str)      # GL_RENDERER

    def __init__(self, clock, loader, size, parent=None):
        super().__init__(parent)
        self.clock, self.loader = clock, loader
        self.render_size = tuple(size)
        self.ctx = None
        self.renderer = None
        self.gl_renderer = ""
        self.frames = 0
        self.host = None

    def initializeGL(self):
        try:
            self.ctx = moderngl.create_context()
            self.gl_renderer = self.ctx.info["GL_RENDERER"]
            log.info("GL_RENDERER: %s, GL %s", self.gl_renderer, self.ctx.version_code)
            self.renderer = Renderer(self.ctx, self.render_size)
        except Exception as e:
            self.gl_renderer = f"ошибка GL: {e}"
            log.exception("GL не инициализирован")
            self.ctx = None
        self.ready.emit(self.gl_renderer)

    def set_render_size(self, size):
        self.render_size = tuple(size)
        if self.renderer:
            self.makeCurrent()
            self.renderer.resize(size)
            self.doneCurrent()

    def paintGL(self):
        if not self.ctx:
            return
        h = self.host
        self.renderer.render(self.clock, self.loader, h.overlay_args(self.renderer) if h else (0.0, 0.5))
        if h:
            h.after_render(self.renderer)
        r = self.devicePixelRatioF()
        target = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        self.renderer.blit(target, (0, 0, round(self.width() * r), round(self.height() * r)),
                           h.brightness() if h else 1.0)
        self.frames += 1


class Hud(QWidget):
    """Рамка видоискателя (всегда) и тонкий HUD (роли, фаза цикла, ks, доли) — отключается."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.show_hud = False
        self.info = {}
        self.message = ""         # крупная надпись по центру (например, «нет фото с кешем»)
        self.idle = False         # фото нет — со дна коробки смотрит глаз
        self._eye = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # уголки рамки, как в видоискателе камеры
        p.setPen(QPen(THEME.c("engrave", 0.55), 1.5))
        m, L = 14, 26
        for x, y, dx, dy in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            p.drawLine(x, y, x + dx * L, y)
            p.drawLine(x, y, x, y + dy * L)
        if self.idle:
            self._paint_eye(p, w, h)
        if self.message:
            p.setFont(THEME.font("screen", 15))
            p.setPen(THEME.c("screen_warn"))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
        if not self.show_hud:
            p.end()
            return
        i = self.info
        p.setFont(THEME.font("screen", 12))
        fg = THEME.c("screen_fg")
        dim = THEME.c("screen_dim")
        bar_h = 22
        p.fillRect(QRectF(0, 0, w, bar_h + m), THEME.c("screen_bg", 0.55))
        p.fillRect(QRectF(0, h - bar_h - m, w, bar_h + m), THEME.c("screen_bg", 0.55))
        p.setPen(dim)
        p.drawText(QRectF(m + 8, m - 2, w / 3, 18), Qt.AlignLeft, f"past {i.get('past', '—')}")
        p.setPen(fg)
        p.drawText(QRectF(w / 3, m - 2, w / 3, 18), Qt.AlignCenter, f"MASTER {i.get('master', '—')}")
        p.setPen(dim)
        p.drawText(QRectF(2 * w / 3 - m - 8, m - 2, w / 3, 18), Qt.AlignRight, f"future {i.get('future', '—')}")
        p.setPen(fg)
        bars = "".join("▮" if k <= i.get("in_bar", 0) else "▯" for k in range(4))
        p.drawText(QRectF(m + 8, h - m - 18, w - 2 * m - 16, 18), Qt.AlignLeft,
                   f"{bars}  такт {i.get('bar', 0)}  {i.get('bpm', '—')} BPM")
        p.drawText(QRectF(m + 8, h - m - 18, w - 2 * m - 16, 18), Qt.AlignRight,
                   f"{i.get('cycle', '—')}  ks {i.get('ks', 1)}  {i.get('fps', 0)} fps")
        p.end()


def _eye_paint(self, p, w, h):
    """Полупрозрачный глаз в глубине: тёмная виньетка, глаз дышит (медленно светлеет и гаснет)."""
    import math
    import time
    from PySide6.QtGui import QPixmap, QRadialGradient, QColor
    if self._eye is None:
        f = THEME.textures.get("eye")
        self._eye = QPixmap(str(THEME.dir / f)) if f else QPixmap()
    if self._eye.isNull():
        return
    g = QRadialGradient(w / 2, h / 2, max(w, h) * 0.6)
    g.setColorAt(0, QColor(20, 28, 22, 255))
    g.setColorAt(1, QColor(0, 0, 0, 255))
    p.fillRect(self.rect(), g)
    pm = self._eye.scaledToWidth(int(min(w * 0.42, h * 0.6 * self._eye.width() / self._eye.height())),
                                 Qt.SmoothTransformation)
    breath = 0.5 + 0.5 * math.sin(time.perf_counter() * 2 * math.pi / 6.0)
    p.setOpacity(0.16 + 0.12 * breath)
    p.drawPixmap(int((w - pm.width()) / 2), int((h - pm.height()) / 2 - h * 0.04), pm)
    p.setOpacity(1.0)


Hud._paint_eye = _eye_paint


class Viewfinder(QWidget):
    """Рамка видоискателя с превью в пропорциях вывода; HUD поверх превью."""

    def __init__(self, clock, loader, size):
        super().__init__()
        self.setObjectName("Viewfinder")
        self.setAttribute(Qt.WA_StyledBackground)
        self.gl = GLPreview(clock, loader, size, self)
        self.hud = Hud(self)
        self.aspect = size[0] / size[1]
        self.side = None                 # панель слева от картинки (ВЕРХНЕЕ ФОТО) — в чёрной полосе
        self.setMinimumSize(480, 280)

    def set_side(self, w, width=104):
        self.side, self.side_w = w, width
        w.setParent(self)
        w.show()
        self.resizeEvent(None)

    def set_render_size(self, size):
        self.aspect = size[0] / size[1]
        self.gl.set_render_size(size)
        self.resizeEvent(None)

    def resizeEvent(self, e):
        left = self.side_w if self.side else 0
        if self.side:
            self.side.setGeometry(4, 4, self.side_w, self.height() - 8)
        w, h = self.width() - 12 - left, self.height() - 12
        if w / max(h, 1) > self.aspect:
            gw, gh = int(h * self.aspect), h
        else:
            gw, gh = w, int(w / self.aspect)
        x, y = left + (self.width() - left - gw) // 2, (self.height() - gh) // 2
        self.gl.setGeometry(x, y, gw, gh)
        self.hud.setGeometry(x, y, gw, gh)
        self.hud.raise_()
        btn = getattr(self, "top_btn", None)             # кнопка шторки — сверху по центру картинки
        if btn:
            btn.move(x + (gw - btn.width()) // 2, 3)
            btn.raise_()
        for ch in self.children():                       # шторка — поверх всего видоискателя
            if ch.__class__.__name__ == "Shutter" and ch.isVisible():
                ch.anim.stop()
                ch.setGeometry(self.rect())
                ch.raise_()
                if btn:
                    btn.raise_()
