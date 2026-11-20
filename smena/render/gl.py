"""Рендер сцены в FBO размера вывода (1920×1080 по умолчанию) и показ FBO в окне (превью; на M4 — вывод).

Фон и элементы — текстурированные квады с альфа-маской. Содержимое элемента движется полосами
вдоль полярности прямо в шейдере: силуэт (альфа) стоит, RGB сдвигается, за краем — зеркальное повторение
(эталон — render_demo.draw_element). Газетная вырезка (SPEC §4.6) — тот же шейдер: квад шире на поле каймы,
под элементом тень и бумага (текстура из scene/assets.paper), лёгкое обесцвечивание.

0.1.2: смена кадра с фоном (наплыв, шторка, мерцание, через чёрное), непрозрачность элементов («ОРИГИНАЛ»),
верхнее фото, выходной проход (ЯРКОСТЬ, калибровка сеткой, маски) → текстура выхода для HDMI и записи REC.
"""
import logging
import math

import moderngl
import numpy as np

log = logging.getLogger("smena.gl")

MAX_STRIPS = 8
TEX_TTL = 600              # кадров без использования — текстура освобождается

VS_QUAD = """
#version 330
in vec2 corner;
uniform vec4 rect;      // x, y, w, h — пиксели холста (y вниз)
uniform vec2 canvas;
uniform float angle;    // радианы, положительный — по часовой
out vec2 uv;
void main() {
    vec2 p = (corner - 0.5) * rect.zw;
    float c = cos(angle), s = sin(angle);
    p = vec2(c * p.x - s * p.y, s * p.x + c * p.y) + rect.xy + rect.zw * 0.5;
    uv = corner;
    gl_Position = vec4(p.x / canvas.x * 2.0 - 1.0, 1.0 - p.y / canvas.y * 2.0, 0.0, 1.0);
}
"""
FS_IMG = """
#version 330
in vec2 uv;
out vec4 color;
uniform sampler2D tex;
uniform float gain;
uniform float alpha;
void main() { vec4 t = texture(tex, uv); color = vec4(t.rgb * gain, t.a * alpha); }
"""
FS_EL = """
#version 330
in vec2 uv;                 // по квадрату элемента (при газете — расширенному на поле каймы)
out vec4 color;
uniform sampler2D tex;
uniform sampler2D paper;    // газетная вырезка: R — бумага, G — размытая бумага (тень)
uniform int pol;            // 0 — полярность X (полосы горизонтальные, едут по X), 1 — Y
uniform int nstrip;
uniform float offs[8];      // сдвиги полос в долях размера вдоль полярности
uniform float opacity;
uniform float news;         // сила газетного эффекта 0..1 (SPEC §4.6)
uniform vec2 inner_off;     // расширенный uv → uv элемента: (uv - inner_off) * inner_scale
uniform vec2 inner_scale;
uniform vec2 shadow_off;    // смещение тени в uv расширенного квадрата
float mirror(float s) { float m = mod(s, 2.0); return m < 1.0 ? m : 2.0 - m; }
void main() {
    vec2 e = (uv - inner_off) * inner_scale;
    bool inside = all(greaterThanEqual(e, vec2(0.0))) && all(lessThanEqual(e, vec2(1.0)));
    float along = pol == 0 ? e.x : e.y;
    float across = pol == 0 ? e.y : e.x;
    int j = clamp(int(across * float(nstrip)), 0, nstrip - 1);
    float s = mirror(along - offs[j]);
    vec2 suv = pol == 0 ? vec2(s, e.y) : vec2(e.x, s);
    float ea = inside ? texture(tex, e).a : 0.0;
    vec3 rgb = texture(tex, clamp(suv, 0.0, 1.0)).rgb;
    if (news <= 0.0) {
        color = vec4(rgb, ea * opacity);
        return;
    }
    // газетная вырезка: тень → светлая бумага без желтизны → элемент, очень лёгкое обесцвечивание
    float lum = dot(rgb, vec3(0.299, 0.587, 0.114));
    rgb = mix(rgb, vec3(lum), 0.22 * news);
    float sh = texture(paper, uv - shadow_off).g * 0.45 * news;
    float pa = texture(paper, uv).r * news;
    vec3 col = vec3(0.0);
    float a = sh;
    col = mix(col, vec3(0.935, 0.935, 0.925), pa);
    a = a + pa * (1.0 - a);
    col = mix(col, rgb, ea);
    a = a + ea * (1.0 - a);
    color = vec4(col, a * opacity);
}
"""
VS_BLIT = """
#version 330
in vec2 corner;
out vec2 uv;
void main() { uv = corner; gl_Position = vec4(corner * 2.0 - 1.0, 0.0, 1.0); }
"""
FS_BLIT = """
#version 330
in vec2 uv;
out vec4 color;
uniform sampler2D tex;
uniform float gain;
void main() { color = vec4(texture(tex, uv).rgb * gain, 1.0); }
"""
# выходной проход: сетка калибровки (узлы — позиции в долях кадра, y вниз) и маска в координатах выхода
VS_WARP = """
#version 330
in vec2 pos;
in vec2 tuv;
out vec2 uv;
void main() { uv = vec2(tuv.x, 1.0 - tuv.y); gl_Position = vec4(pos.x * 2.0 - 1.0, 1.0 - pos.y * 2.0, 0.0, 1.0); }
"""
FS_WARP = """
#version 330
in vec2 uv;
out vec4 color;
uniform sampler2D tex;
uniform sampler2D mask;
uniform vec2 size;
uniform float gain;
void main() {
    float m = texture(mask, vec2(gl_FragCoord.x / size.x, 1.0 - gl_FragCoord.y / size.y)).r;
    color = vec4(texture(tex, uv).rgb * gain * m, 1.0);
}
"""
WARP_SUB = 12              # каждая клетка сетки — 12×12 квадов (плавный изгиб)


def warp_mesh(nodes, nx, ny):
    """Треугольники (x, y, u, v) по сетке nx×ny узлов: позиция — билинейно по углам клетки, uv — ровная сетка."""
    import numpy as np
    P = np.asarray(nodes, np.float32).reshape(ny, nx, 2)
    s = np.linspace(0, 1, WARP_SUB + 1, dtype=np.float32)
    out = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            p00, p10, p01, p11 = P[j, i], P[j, i + 1], P[j + 1, i], P[j + 1, i + 1]
            a, b = np.meshgrid(s, s)                       # a — по x, b — по y
            pos = (p00 * ((1 - a) * (1 - b))[..., None] + p10 * (a * (1 - b))[..., None]
                   + p01 * ((1 - a) * b)[..., None] + p11 * (a * b)[..., None])
            uv = np.dstack([(i + a) / (nx - 1), (j + b) / (ny - 1)])
            v = np.dstack([pos, uv]).astype(np.float32)
            q00, q10, q01, q11 = v[:-1, :-1], v[:-1, 1:], v[1:, :-1], v[1:, 1:]
            out.append(np.stack([q00, q10, q11, q00, q11, q01], axis=2).reshape(-1, 4))
    return np.concatenate(out).astype(np.float32)


class Renderer:
    def __init__(self, ctx, size):
        self.ctx = ctx
        self.size = None
        self.prog_img = ctx.program(vertex_shader=VS_QUAD, fragment_shader=FS_IMG)
        self.prog_el = ctx.program(vertex_shader=VS_QUAD, fragment_shader=FS_EL)
        self.prog_blit = ctx.program(vertex_shader=VS_BLIT, fragment_shader=FS_BLIT)
        self.prog_warp = ctx.program(vertex_shader=VS_WARP, fragment_shader=FS_WARP)
        self.vao_warp = None
        self.mask_white = ctx.texture((1, 1), 1, b"\xff")
        self.mask_tex = None
        self.map_version = None
        self.white = ctx.texture((1, 1), 4, bytes([255, 255, 255, 255]))
        self.overlay_tex = None
        self.overlay_src = None
        self.pending_overlay = None        # (путь, w, h, байты RGBA) — текстура создаётся в кадре
        quad = ctx.buffer(np.array([0, 0, 1, 0, 0, 1, 1, 1], np.float32).tobytes())
        self.vao_img = ctx.vertex_array(self.prog_img, [(quad, "2f", "corner")])
        self.vao_el = ctx.vertex_array(self.prog_el, [(quad, "2f", "corner")])
        self.vao_blit = ctx.vertex_array(self.prog_blit, [(quad, "2f", "corner")])
        self.textures = {}         # (ключ фото, имя) → [текстура, кадр последнего использования]
        self.paper_none = ctx.texture((1, 1), 2, bytes(2))   # заглушка, когда газеты нет
        self.frame_no = 0
        self.blackout = False
        self.resize(size)

    def resize(self, size):
        size = tuple(int(v) for v in size)
        if size == self.size:
            return
        if self.size:
            for o in (self.fbo, self.color, self.out_fbo, self.out_color):
                o.release()
        self.size = size
        self.color = self.ctx.texture(size, 4)
        self.color.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.fbo = self.ctx.framebuffer(color_attachments=[self.color])
        self.out_color = self.ctx.texture(size, 4)         # выход: HDMI и запись
        self.out_color.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.out_fbo = self.ctx.framebuffer(color_attachments=[self.out_color])
        self.map_version = None

    # ------------------------------------------------------------ текстуры
    def _tex(self, assets, name):
        k = (assets.key, name)
        t = self.textures.get(k)
        if t is None:
            img = assets.images.get(name)
            if img is None:
                return None
            w, h, data = img
            tex = self.ctx.texture((w, h), 4, data)
            tex.repeat_x = tex.repeat_y = False
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t = self.textures[k] = [tex, 0]
        t[1] = self.frame_no
        return t[0]

    def _paper(self, assets, name):
        """Текстура бумаги газетной вырезки (RG) → (текстура, поле M, ширина и высота картинки элемента)."""
        p = assets.papers.get(name) if assets else None
        img = assets.images.get(name) if assets else None
        if p is None or img is None:
            return None
        k = (assets.key, name + "#paper")
        t = self.textures.get(k)
        if t is None:
            M, w2, h2, data = p
            tex = self.ctx.texture((w2, h2), 2, data)
            tex.repeat_x = tex.repeat_y = False
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t = self.textures[k] = [tex, 0]
        t[1] = self.frame_no
        return t[0], p[0], img[0], img[1]

    def _evict(self):
        old = [k for k, (_, used) in self.textures.items() if self.frame_no - used > TEX_TTL]
        for k in old:
            self.textures.pop(k)[0].release()

    # --------------------------------------------------------------- сцена
    def _background(self, inst, loader, gain=1.0, alpha=1.0):
        """Фон фото: подложка (если фото не заполняет кадр) + фон в своём прямоугольнике."""
        assets = loader.get(inst.entry)
        if not assets:
            return
        W, H = self.size
        if not inst.full:
            pw, ph = inst.entry.meta["size"]
            sc = max(W / pw, H / ph)
            self._img(self._tex(assets, "_blur"), ((W - pw * sc) / 2, (H - ph * sc) / 2, pw * sc, ph * sc),
                      0.45 * gain, alpha)
        self._img(self._tex(assets, "background.png"), inst.rect, gain, alpha)

    def _backgrounds(self, clock, loader):
        """Фон master; во время смены кадра с фоном — вместе с фоном past (наплыв, шторка, мерцание, чёрное)."""
        ctx = self.ctx
        ctx.disable(moderngl.BLEND)
        tr = clock.transition()
        if not tr:
            self._background(clock.master, loader)
            return
        kind, u = tr
        W, H = self.size
        if kind == 5:                                   # через чёрное
            if u < 0.5:
                self._background(clock.past, loader, gain=1 - 2 * u)
            else:
                self._background(clock.master, loader, gain=2 * u - 1)
            return
        if kind == 4:                                   # мерцание: доля вспышек нового фото растёт
            new = (u * 8) % 1.0 < u or u > 0.9
            self._background(clock.master if new else clock.past, loader)
            return
        self._background(clock.past, loader)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        if kind == 3:                                   # шторка слева направо
            ctx.scissor = (0, 0, max(1, int(u * W)), H)
            self._background(clock.master, loader)
            ctx.scissor = None
        else:                                           # наплыв
            self._background(clock.master, loader, alpha=u)
        ctx.disable(moderngl.BLEND)

    def set_overlay(self, path):
        """Верхнее фото: картинка (PNG с прозрачностью) читается сразу, текстура — в ближайшем кадре."""
        if path == self.overlay_src:
            return
        self.overlay_src = path
        from PySide6.QtGui import QImage
        img = QImage(path) if path else QImage()
        if img.isNull():
            self.pending_overlay = ("", 0, 0, b"")
            return
        img = img.convertToFormat(QImage.Format_RGBA8888).mirrored(False, False)
        self.pending_overlay = (path, img.width(), img.height(), bytes(img.constBits())[:img.width() * img.height() * 4])

    def _overlay(self, alpha, size):
        if self.pending_overlay is not None:
            path, w, h, data = self.pending_overlay
            self.pending_overlay = None
            if self.overlay_tex:
                self.overlay_tex.release()
                self.overlay_tex = None
            if w:
                self.overlay_tex = self.ctx.texture((w, h), 4, data)
                self.overlay_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        if not self.overlay_tex or alpha <= 0.0:
            return
        W, H = self.size
        w, h = self.overlay_tex.size
        sc = min(W * size / w, H * size / h)
        ctx = self.ctx
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._img(self.overlay_tex, ((W - w * sc) / 2, (H - h * sc) / 2, w * sc, h * sc), 1.0, alpha)

    def render(self, clock, loader, overlay=(0.0, 0.5)):
        """Кадр сцены в FBO. overlay — (непрозрачность, размер) верхнего фото."""
        self.frame_no += 1
        ctx = self.ctx
        self.fbo.use()
        ctx.viewport = (0, 0, *self.size)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        W, H = self.size
        if self.blackout or not clock.master:
            self._finish()
            return
        for p in (self.prog_img, self.prog_el):
            p["canvas"].value = (W, H)
        self._backgrounds(clock, loader)
        # элементы: past → master → future
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        pe = self.prog_el
        pe["tex"].value = 0
        pe["paper"].value = 1
        for inst, e, x, y, ang, news, alpha, k in clock.draw_list():
            a = loader.get(inst.entry)
            tex = self._tex(a, e.file) if a else None
            if tex is None:
                continue
            tex.use(0)
            pap = self._paper(a, e.file) if news > 0 else None
            if pap is not None:                     # газетная вырезка: квад шире на поле каймы
                ptex, M, iw, ih = pap
                ptex.use(1)
                sx, sy = e.w / iw, e.h / ih         # пиксели картинки → холста
                pe["rect"].value = (x - M * sx, y - M * sy, e.w + 2 * M * sx, e.h + 2 * M * sy)
                ew, eh = iw + 2 * M, ih + 2 * M
                pe["inner_off"].value = (M / ew, M / eh)
                pe["inner_scale"].value = (ew / iw, eh / ih)
                pe["shadow_off"].value = (0.35 * M / ew, 0.45 * M / eh)   # тень вниз-вправо
                pe["news"].value = float(news)
            else:
                self.paper_none.use(1)
                pe["rect"].value = (x, y, e.w, e.h)
                pe["inner_off"].value = (0.0, 0.0)
                pe["inner_scale"].value = (1.0, 1.0)
                pe["news"].value = 0.0
            pe["angle"].value = math.radians(ang)
            pe["pol"].value = 0 if e.pol == "X" else 1
            pe["nstrip"].value = e.nstrip
            offs = [o * k for o in e.strip_offsets()] + [0.0] * (MAX_STRIPS - e.nstrip)
            pe["offs"].value = offs[:MAX_STRIPS]
            pe["opacity"].value = float(alpha)
            self.vao_el.render(moderngl.TRIANGLE_STRIP)
        self._overlay(*overlay)
        if clock.flash_k > 0:                       # вспышка оригинала: белая вспышка камеры, быстро гаснет
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self._img(self.white, (0, 0, W, H), 1.0, 0.92 * clock.flash_k ** 4)
        self._finish()

    def _img(self, tex, rect, gain, alpha=1.0):
        if tex is None:
            return
        tex.use(0)
        self.prog_img["rect"].value = rect
        self.prog_img["angle"].value = 0.0
        self.prog_img["gain"].value = gain
        self.prog_img["alpha"].value = alpha
        self.vao_img.render(moderngl.TRIANGLE_STRIP)

    # ----------------------------------------------------------- выход
    def output(self, mapping, gain, use_mask=True):
        """Сцена → текстура выхода: калибровка сеткой, маска, яркость (HDMI и запись)."""
        ctx = self.ctx
        if mapping.version != self.map_version:
            self.map_version = mapping.version
            data = warp_mesh(mapping.out_nodes(), mapping.nx, mapping.ny)
            if self.vao_warp:
                self.vao_warp.release()
                self._warp_buf.release()
            self._warp_buf = ctx.buffer(data.tobytes())
            self.vao_warp = ctx.vertex_array(self.prog_warp, [(self._warp_buf, "2f 2f", "pos", "tuv")])
            if self.mask_tex:
                self.mask_tex.release()
                self.mask_tex = None
            m = mapping.mask_bytes()
            if m is not None:
                w, h, b = m
                self.mask_tex = ctx.texture((w, h), 1, b, alignment=1)
                self.mask_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.out_fbo.use()
        ctx.viewport = (0, 0, *self.size)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        ctx.disable(moderngl.BLEND)
        if self.blackout:
            return
        self.color.use(0)
        (self.mask_tex if use_mask and self.mask_tex else self.mask_white).use(1)
        pw = self.prog_warp
        pw["tex"].value = 0
        pw["mask"].value = 1
        pw["size"].value = self.size
        pw["gain"].value = gain
        self.vao_warp.render(moderngl.TRIANGLES)

    def snapshot(self, mapping, gain, level=2):
        """Уменьшенный кадр выхода без маски (чтобы видеть, что вырезаешь) для холста калибровки:
        (w, h, байты RGBA снизу вверх). Потом выход перерисовывается как обычно."""
        self.output(mapping, gain, use_mask=False)
        self.out_color.build_mipmaps()
        w, h = max(1, self.size[0] >> level), max(1, self.size[1] >> level)
        data = self.out_color.read(level=level)
        self.output(mapping, gain)
        return w, h, data

    def _finish(self):
        self.ctx.disable(moderngl.BLEND)
        self.color.build_mipmaps()
        if self.frame_no % 120 == 0:
            self._evict()

    # --------------------------------------------------------------- показ
    def blit(self, target, viewport, gain=1.0):
        """FBO сцены → превью, во весь viewport (ЯРКОСТЬ — gain)."""
        target.use()
        self.ctx.viewport = viewport
        self.ctx.disable(moderngl.BLEND)
        self.color.use(0)
        self.prog_blit["gain"].value = gain
        self.vao_blit.render(moderngl.TRIANGLE_STRIP)
