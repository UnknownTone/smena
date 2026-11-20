"""Шторка перед первым выводом: при первом открытии вкладки ВЫВОД (за запуск) видоискатель слева направо
закрывает металлическая рольставня — еле заметный знак «!» в треугольнике и правила подключения полустёртым
трафаретом. Микрокнопка «руководство смены» открывает руководство; клик по шторке — убрать (уезжает обратно).
"""
import random

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from smena.settings import ROOT
from smena.ui.theme import THEME

RULES = ["1. Перед подключением аудио убавить громкость до нуля на источнике.",
         "2. HDMI подключать при выключенном проекторе.",
         "3. Аудиосигнал подавать только на соответствующий вход аудиокарты.",
         "4. Не подключать и не отключать аудиокабели при высокой громкости.",
         "5. Не допускать перегрузки сигнала (CLIP).",
         "6. Проектор выключать штатно, дождавшись охлаждения."]
MANUAL = ROOT / "docs" / "manual" / "smena_manual.html"


def stencil_path(text, font, x, y):
    """Контур надписи с перемычками трафарета: узкий разрез через замкнутые «окна» букв."""
    from PySide6.QtGui import QFontMetrics, QPainterPath
    path = QPainterPath()
    path.addText(QPointF(x, y), font, text)
    fm = QFontMetrics(font)
    cuts = QPainterPath()
    cx = x
    for ch in text:
        adv = fm.horizontalAdvance(ch)
        if ch.upper() in "ОАРДБВЕЁФЯЮQOBDPRA0689Ы":
            cuts.addRect(QRectF(cx + adv * 0.47, y - fm.ascent() * 0.98, max(1.3, adv * 0.07), fm.ascent() * 1.05))
        cx += adv
    return path.subtracted(cuts)


def spray(img, p, path, color, alpha, seed):
    """Краска через трафарет: чёрная тень (контраст), ореол распыла, краска, лёгкая стёртость."""
    from PySide6.QtGui import QPainterPathStroker
    layer = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    layer.fill(0)
    q = QPainter(layer)
    q.setRenderHint(QPainter.Antialiasing)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(0, 0, 0, 170))                               # тень букв
    q.drawPath(path.translated(1.6, 2.0))
    st = QPainterPathStroker()
    st.setWidth(5)
    halo = QColor(color)
    halo.setAlpha(26)
    q.setBrush(halo)
    q.drawPath(st.createStroke(path).united(path))
    c = QColor(color)
    c.setAlpha(alpha)
    q.setBrush(c)
    q.drawPath(path)
    q.setCompositionMode(QPainter.CompositionMode_DestinationOut)  # стёртость
    rng = random.Random(seed)
    b = path.boundingRect()
    for _ in range(int(b.width() * b.height() / 260)):
        x, y = rng.uniform(b.left(), b.right()), rng.uniform(b.top(), b.bottom())
        r = rng.uniform(0.5, 1.8)
        q.setBrush(QColor(0, 0, 0, rng.randint(60, 200)))
        q.drawEllipse(QPointF(x, y), r, r * rng.uniform(0.5, 1.0))
    q.end()
    p.drawImage(0, 0, layer)


class Shutter(QWidget):
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("щёлкните по шторке, чтобы поднять её")
        self._pm = None
        self.setMouseTracking(True)
        self.btn = QPushButton("руководство смены ↗", self)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet("QPushButton { color: #cfc9b0; background: rgba(0,0,0,90); border: 1px solid #6b6656;"
                               " border-radius: 2px; padding: 1px 6px; font-size: 10px; }"
                               "QPushButton:hover { border-color: #e2c21e; color: #e2c21e; }")
        self.btn.clicked.connect(self.open_manual)
        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(900)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.hide()

    # ------------------------------------------------------------- показ
    def slide_in(self):
        r = self.parent().rect()
        self._pm = None
        self.setGeometry(QRect(r.left(), r.top(), 0, r.height()))
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(QRect(r.left(), r.top(), 0, r.height()))
        self.anim.setEndValue(r)
        self.anim.start()

    def slide_out(self):
        r = self.geometry()
        self.anim.stop()
        self.anim.setStartValue(r)
        self.anim.setEndValue(QRect(r.left(), r.top(), 0, r.height()))
        self.anim.finished.connect(self._gone, Qt.SingleShotConnection)
        self.anim.start()

    def _gone(self):
        self.hide()
        self.closed.emit()

    def _on_sleeve(self, pos):
        r = getattr(self, "_sleeve", None)
        return r is not None and self.width() >= self.parent().width() - 4 and r.contains(pos)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._on_sleeve(e.position()):
                self.open_manual()
            else:
                self.slide_out()

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("конверт — открыть руководство смены" if self._on_sleeve(e.position()) else
                        "щёлкните по шторке, чтобы поднять её")

    def resizeEvent(self, e):
        full = self.parent().rect()
        self.btn.hide()                                  # руководство — в конверте на шторке

    # ------------------------------------------------------------- руководство
    def open_manual(self):
        """Руководство — HTML в стиле логотипа с глазом, открывается в браузере."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if MANUAL.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(MANUAL)))
            return
        d = QDialog(self.window())
        d.setWindowTitle("SMENA — руководство")
        d.resize(760, 820)
        v = QVBoxLayout(d)
        t = QTextBrowser()
        t.setOpenExternalLinks(True)
        try:
            t.setMarkdown(MANUAL.read_text(encoding="utf-8"))
        except Exception:
            t.setPlainText("\n".join(RULES))
        t.setStyleSheet("QTextBrowser { background: #0b0a07; color: #e6e2cf; border: 1px solid #3e3c1c; "
                        "font-size: 14px; padding: 10px; }")
        v.addWidget(t)
        d.show()

    # ------------------------------------------------------------- рисунок
    def _render(self, W, H):
        """Рольставня: горизонтальные ламели серого металла, ржавые подтёки, знак и правила — трафарет, стёртый
        шумом."""
        img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        rng = random.Random(41)
        slat = max(24, int(H / 13.5))                    # ламель = строка: 3 под знак, 2 под конверт, 6 правил
        fpx = self._fit(W, slat)                         # кегль: строка влезает в ширину и в ламель
        for y in range(0, H, slat):
            g = QLinearGradient(0, y, 0, y + slat)
            g.setColorAt(0.0, QColor("#8a8c84"))
            g.setColorAt(0.15, QColor("#6d6f68"))
            g.setColorAt(0.7, QColor("#55574f"))
            g.setColorAt(0.92, QColor("#3a3b35"))
            g.setColorAt(1.0, QColor("#1c1c18"))
            p.fillRect(0, y, W, slat, g)
        for _ in range(int(W * H / 900)):                 # царапины и пятна
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            p.setPen(QPen(QColor(220, 215, 200, rng.randint(6, 22)), 1))
            p.drawLine(QPointF(x, y), QPointF(x + rng.uniform(-30, 30), y + rng.uniform(-2, 2)))
        for _ in range(int(W / 25)):                      # ржавые подтёки сверху вниз
            x = rng.uniform(0, W)
            L = rng.uniform(H * 0.1, H * 0.6)
            g = QLinearGradient(x, 0, x, L)
            g.setColorAt(0, QColor(130, 64, 24, rng.randint(60, 130)))
            g.setColorAt(1, QColor(130, 64, 24, 0))
            p.fillRect(QRectF(x, 0, rng.uniform(2, 7), L), g)
        # знак: треугольник с «!» — жёлтая краска, заметнее
        cx, a = W * 0.5, slat * 1.15
        cy = slat * 1.55
        tri = QPolygonF([QPointF(cx, cy - a), QPointF(cx + a * 1.15, cy + a), QPointF(cx - a * 1.15, cy + a)])
        p.setPen(QPen(QColor(0, 0, 0, 110), 7))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(tri.translated(2, 3))
        p.setPen(QPen(QColor(232, 200, 30, 150), 6))
        p.setBrush(QColor(232, 200, 30, 22))
        p.drawPolygon(tri)
        f = QFont("Impact")
        f.setPixelSize(int(a * 1.25))
        p.setFont(f)
        p.setPen(QColor(232, 200, 30, 160))
        p.drawText(QRectF(cx - a, cy - a * 0.5, a * 2, a * 1.6), Qt.AlignCenter, "!")
        # руководство в прозрачном полиэтиленовом конверте (рваном) — между знаком и правилами, кликается
        self._sleeve = self._paint_sleeve(p, W, slat, rng)
        # правила: светло-салатовая краска через трафарет, чёрная тень — по одной строке на ламель
        fnt = self._font(fpx)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(fnt)
        for i, line in enumerate(RULES):
            top = (6 + i) * slat
            y = top + slat / 2 + (fm.ascent() - fm.descent()) / 2 - slat * 0.03
            path = stencil_path(line, fnt, W * 0.07, y)
            spray(img, p, path, QColor("#c6ef8c"), 225, 41 + i)
        # нижняя планка с ручкой
        p.fillRect(QRectF(0, H - 8, W, 8), QColor("#1a1a16"))
        p.setPen(QPen(QColor("#000"), 1))
        p.setBrush(QColor("#9a9c94"))
        p.drawRoundedRect(QRectF(W - 14, H * 0.42, 10, H * 0.16), 3, 3)
        p.end()
        return QPixmap.fromImage(img)

    def _paint_sleeve(self, p, W, slat, rng):
        """Прозрачный полиэтиленовый конверт, прихваченный скотчем: внутри карточка «РУКОВОДСТВО СМЕНЫ ↗».
        Плёнка порвана — рваный край вокруг надписи, блики и складки. → прямоугольник для клика."""
        from PySide6.QtGui import QPainterPath
        sw, sh = min(W * 0.42, 460.0), slat * 1.55
        r = QRectF((W - sw) / 2, slat * 3.25, sw, sh)
        # карточка (бумага) под плёнкой
        card = r.adjusted(sw * 0.06, sh * 0.16, -sw * 0.06, -sh * 0.16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRect(card.translated(3, 4))
        p.setBrush(QColor("#e6e1cf"))
        p.drawRect(card)
        p.setPen(QPen(QColor(150, 140, 110, 120), 1))
        p.drawRect(card.adjusted(4, 4, -4, -4))
        eye = THEME.textures.get("eye")
        x0 = card.left() + 12
        if eye:
            pm = QPixmap(str(THEME.dir / eye))
            if not pm.isNull():
                pm = pm.scaledToHeight(int(card.height() * 0.62), Qt.SmoothTransformation)
                p.drawPixmap(int(x0), int(card.center().y() - pm.height() / 2), pm)
                x0 += pm.width() + 12
        f = QFont(THEME.fonts.get("engrave", "PT Sans Narrow"))
        f.setPixelSize(int(card.height() * 0.42))
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        p.setFont(f)
        p.setPen(QColor("#1d1c16"))
        p.drawText(QRectF(x0, card.top(), card.right() - x0 - 8, card.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   "РУКОВОДСТВО СМЕНЫ ↗")
        # плёнка: рваный контур — ровный сверху, рваная дыра справа снизу (видна карточка без бликов)
        film = QPainterPath()
        pts = [QPointF(r.left(), r.top()), QPointF(r.right(), r.top())]
        y = r.top()
        while y < r.bottom():                                       # правый край — рваный
            y += rng.uniform(3, 8)
            pts.append(QPointF(r.right() - rng.uniform(0, 5) - (12 if y > r.center().y() else 0), min(y, r.bottom())))
        x = r.right() - 14
        while x > r.left():                                         # нижний край — рваный с языками
            x -= rng.uniform(5, 14)
            pts.append(QPointF(max(x, r.left()), r.bottom() - rng.uniform(0, 7) - (10 if rng.random() < 0.2 else 0)))
        pts.append(QPointF(r.left(), r.bottom() - 4))
        film.addPolygon(QPolygonF(pts))
        film.closeSubpath()
        hole = QPainterPath()                                       # дыра: плёнку прорвали над надписью
        hc = QPointF(card.right() - card.width() * 0.22, card.center().y() + 2)
        hp = []
        for k in range(14):
            ang = k / 14 * 6.283
            rr = rng.uniform(0.55, 1.0)
            import math
            hp.append(QPointF(hc.x() + math.cos(ang) * card.height() * 0.95 * rr,
                              hc.y() + math.sin(ang) * card.height() * 0.42 * rr))
        hole.addPolygon(QPolygonF(hp))
        hole.closeSubpath()
        film = film.subtracted(hole)
        g = QLinearGradient(r.topLeft(), r.bottomRight())            # плёнка: мутноватая, с бликами
        g.setColorAt(0.0, QColor(255, 255, 255, 70))
        g.setColorAt(0.35, QColor(255, 255, 255, 22))
        g.setColorAt(0.5, QColor(255, 255, 255, 85))
        g.setColorAt(0.62, QColor(255, 255, 255, 18))
        g.setColorAt(1.0, QColor(255, 255, 255, 50))
        p.setPen(QPen(QColor(255, 255, 255, 130), 1))
        p.setBrush(g)
        p.drawPath(film)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))                # складки плёнки
        for _ in range(7):
            x1 = rng.uniform(r.left(), r.right())
            p.drawLine(QPointF(x1, r.top() + 2), QPointF(x1 + rng.uniform(-30, 30), r.bottom() - 6))
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.2))             # закрученные края разрыва
        p.setBrush(Qt.NoBrush)
        p.drawPath(hole)
        p.setPen(Qt.NoPen)                                          # скотч по верхним углам
        for tx, ang in ((r.left() - 10, -18), (r.right() - 30, 16)):
            p.save()
            p.translate(tx + 20, r.top() + 2)
            p.rotate(ang)
            p.setBrush(QColor(225, 215, 170, 120))
            p.drawRect(QRectF(-22, -7, 44, 14))
            p.restore()
        return r

    @staticmethod
    def _font(px):
        f = QFont(THEME.fonts.get("engrave", "PT Sans Narrow"))
        f.setPixelSize(px)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        return f

    @classmethod
    def _fit(cls, W, slat):
        from PySide6.QtGui import QFontMetrics
        fpx = int(slat * 0.52)
        while fpx > 11 and max(QFontMetrics(cls._font(fpx)).horizontalAdvance(r) for r in RULES) > W * 0.86:
            fpx -= 1
        return fpx

    def paintEvent(self, _):
        full = self.parent().rect()
        if self._pm is None or self._pm.size() != full.size():
            self._pm = self._render(full.width(), full.height())
        p = QPainter(self)
        # шторка выезжает слева: видна правая часть рисунка, прижатая к правому краю шторки
        p.drawPixmap(0, 0, self._pm, full.width() - self.width(), 0, self.width(), full.height())
        p.fillRect(QRectF(self.width() - 3, 0, 3, self.height()), QColor(0, 0, 0, 160))   # торец
        p.end()
