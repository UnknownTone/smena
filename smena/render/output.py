"""Окно вывода (HDMI): текстура выхода рендера на выбранный монитор — полный экран без рамки или окно.

Контекст GL общий с превью (AA_ShareOpenGLContexts): текстура выхода берётся по её номеру (external_texture),
своя только программа показа. F — полный экран / окно, Esc — в окно.
"""
import logging

import moderngl
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from smena.render.gl import FS_BLIT, VS_BLIT

log = logging.getLogger("smena.output")


class OutputWindow(QOpenGLWidget):
    closed = Signal()

    def __init__(self, preview):
        super().__init__(None, Qt.Window)
        self.preview = preview                 # GLPreview: его Renderer держит текстуру выхода
        self.setWindowTitle("SMENA — вывод")
        self.setCursor(Qt.BlankCursor)
        self.ctx = None
        self._tex = None
        self._tex_key = None

    def place(self, monitor, fullscreen):
        screens = QGuiApplication.screens()
        sc = screens[min(max(monitor - 1, 0), len(screens) - 1)]
        self.setScreen(sc)
        g = sc.geometry()
        if fullscreen:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setGeometry(g)
            self.showFullScreen()
        else:
            self.setWindowFlag(Qt.FramelessWindowHint, False)
            self.showNormal()
            self.setGeometry(g.x() + 60, g.y() + 60, g.width() // 2, g.height() // 2)
        self.show()

    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.prog = self.ctx.program(vertex_shader=VS_BLIT, fragment_shader=FS_BLIT)
        quad = self.ctx.buffer(np.array([0, 0, 1, 0, 0, 1, 1, 1], np.float32).tobytes())
        self.vao = self.ctx.vertex_array(self.prog, [(quad, "2f", "corner")])

    def paintGL(self):
        r = self.preview.renderer
        if not self.ctx or not r:
            return
        key = (r.out_color.glo, r.size)
        if key != self._tex_key:              # текстура выхода пересоздана (смена разрешения)
            self._tex_key = key
            self._tex = self.ctx.external_texture(r.out_color.glo, r.size, 4, 0, "f1")
        fb = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        fb.use()
        k = self.devicePixelRatioF()
        self.ctx.viewport = (0, 0, round(self.width() * k), round(self.height() * k))
        self.ctx.clear(0, 0, 0, 1)
        self._tex.use(0)
        self.prog["gain"].value = 1.0
        self.vao.render(moderngl.TRIANGLE_STRIP)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        elif e.key() in (Qt.Key_F, 0x0410):     # F / А
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)
