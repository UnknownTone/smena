r"""Корпус SMENA «старая бирюзовая жестянка» — процедурный рендер (numpy + OpenCV, окружение .venv-prep).

Слои: листовой металл с лёгкими вмятинами (карта высот → освещение), выцветшая бирюзовая эмаль, износ по краям
и швам (потёртости до металла, сколы, ржавчина от рыжей до тёмной, глубокая коррозия), микротрещины, царапины;
вырезы под панели — рваная тонкая жесть: срез металла с толщиной, местами загнутая кромка (блик и тень),
краска и ржавчина на сломе, тень на панель под ней. Иерархия: корпус — сильная фактура, панели — слабая.

Режимы:
  mockup <снимок.png> <rects.json> <выход.png>  — макет: интерфейс под корпусом (для согласования дизайна);
  shell  <W> <H> <rects.json> <выход.png>        — только корпус с прозрачными вырезами (RGBA).
"""
import json
import sys

import cv2
import numpy as np

LIGHT = np.array([-0.55, -0.75])          # свет сверху-слева
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def fbm(h, w, scale, rng, octaves=4):
    """Фрактальный шум ~N(0,1): сумма октав сглаженного шума, scale — размер крупных пятен (пиксели)."""
    out = np.zeros((h, w), np.float32)
    amp, s = 1.0, scale
    for _ in range(octaves):
        gh, gw = max(2, int(h / s) + 2), max(2, int(w / s) + 2)
        g = rng.standard_normal((gh, gw)).astype(np.float32)
        out += amp * cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
        amp *= 0.5
        s /= 2.0
    return (out - out.mean()) / (out.std() + 1e-6)


def smooth_band(d, w):
    return np.exp(-np.maximum(d, 0) / w)


BEZEL = 11.0                                # серая окантовка вокруг панели (как рамка экрана С1-83)


def render_shell(W, H, rects, seed=1957, bezel=BEZEL):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    # ---------------------------------------------------------------- вырезы (рваная жесть)
    content = np.zeros((H, W), np.uint8)
    hole_sdf = np.full((H, W), 1e6, np.float32)
    for name, (x0, y0, x1, y1) in rects.items():
        m = 5.0 + bezel                                           # вырез: панель + окантовка + зазор
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hx, hy = (x1 - x0) / 2 + m, (y1 - y0) / 2 + m
        r = 7.0
        qx, qy = np.abs(xx - cx) - hx + r, np.abs(yy - cy) - hy + r
        sdf = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - r
        hole_sdf = np.minimum(hole_sdf, sdf)
        content[int(y0):int(y1), int(x0):int(x1)] = 1
    # край: крупные изгибы + рваность + редкие надрывы (неодинаково по периметру)
    # металл рвётся жёстко: пологие изгибы, короткие прямые участки с изломами (ridged), редкие надрывы
    ridged = 1.0 - np.abs(fbm(H, W, 45, rng, 2))
    tear = np.clip(fbm(H, W, 60, rng, 2) - 1.6, 0, None) * 7.0
    disp = 1.4 * fbm(H, W, 160, rng, 2) + 1.6 * ridged + 0.5 * fbm(H, W, 9, rng, 1) + tear
    hole = ((hole_sdf - disp) < 0).astype(np.uint8) | content
    hole = cv2.morphologyEx(hole, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    hole |= content
    metal = 1 - hole
    dm = cv2.distanceTransform(metal, cv2.DIST_L2, 5)             # расстояние от края выреза по металлу
    di = cv2.distanceTransform(hole, cv2.DIST_L2, 5)              # по вырезу (для тени)
    # край корпуса — закатанный борт
    db = np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))
    rim_w = 12.0
    edge_d = np.minimum(dm, np.maximum(db - rim_w, 0))

    # ---------------------------------------------------------------- рельеф: вмятины и волнистость листа
    hgt = fbm(H, W, 260, rng, 3) * 3.0
    for _ in range(9):                                            # отдельные вмятины
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        rad = rng.uniform(40, 170)
        hgt -= rng.uniform(1.5, 4.0) * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * rad ** 2)))
    hgt += 2.2 * np.sin(np.clip(db / rim_w, 0, 1) * np.pi) * (db < rim_w)  # закатанный борт — валик
    gx = cv2.Sobel(hgt, cv2.CV_32F, 1, 0, ksize=5) / 32.0
    gy = cv2.Sobel(hgt, cv2.CV_32F, 0, 1, ksize=5) / 32.0
    relief = np.clip(1.0 + 0.9 * (-gx * LIGHT[0] - gy * LIGHT[1]), 0.7, 1.3)

    # ---------------------------------------------------------------- эмаль
    base = np.array([96, 154, 146], np.float32)                   # выцветшая бирюза (RGB)
    pale = np.array([126, 172, 162], np.float32)
    deep = np.array([84, 134, 128], np.float32)
    t1 = np.clip(fbm(H, W, 320, rng) * 0.35 + 0.35, 0, 1)[..., None]
    t2 = np.clip(fbm(H, W, 90, rng) * 0.25, -0.3, 0.3)[..., None]
    paint = base * (1 - t1) + pale * t1
    paint = paint + (deep - paint) * np.clip(-t2, 0, 1) * 1.5
    paint *= (1.0 + rng.standard_normal((H, W, 1)).astype(np.float32) * 0.012)
    # микротрещины эмали — только местами
    cr = fbm(H, W, 7, rng, 2)
    cracks = np.clip(1 - np.abs(cr) * 6.0, 0, 1) * np.clip(fbm(H, W, 120, rng) - 0.2, 0, 1)
    paint *= (1 - 0.18 * cracks)[..., None]

    # ---------------------------------------------------------------- износ: потёртости, сколы, ржавчина
    # износ неравномерен по периметру: где-то край почти чистый, где-то съеден
    edge_var = np.clip(fbm(H, W, 170, rng, 2) * 0.55 + 0.45, 0.08, 1.0)
    near = smooth_band(edge_d, 7.0) * edge_var
    wear = 0.5 * fbm(H, W, 46, rng) + 0.25 * fbm(H, W, 9, rng, 2) + 1.4 * near
    rub = np.clip((wear - 0.55) * 1.6, 0, 1)                      # краска истёрта (просвечивает металл)
    chip = np.clip((wear - 1.15) * 5.0, 0, 1)                     # скол до металла
    metal_c = np.array([146, 146, 140], np.float32) * (0.85 + 0.15 * fbm(H, W, 5, rng, 2)[..., None])
    col = paint * (1 - 0.45 * rub[..., None]) + metal_c * (0.45 * rub[..., None])
    col = col * (1 - chip[..., None]) + metal_c * chip[..., None]
    chip_rim = np.clip(cv2.GaussianBlur(chip, (0, 0), 1.5) * 2.5 - chip * 2.0, 0, 1)
    col *= (1 - 0.3 * chip_rim)[..., None]                        # тёмная кромка краски у скола

    rust_n = fbm(H, W, 22, rng, 3)
    rust_amt = np.clip(1.6 * smooth_band(edge_d, 5.5) * edge_var + 0.3 * rust_n - 0.6, 0, 1)
    rust_amt = np.maximum(rust_amt, chip * np.clip(fbm(H, W, 7, rng, 2) * 0.6 + 0.2, 0, 1))
    pits = (rng.random((H, W)) > 0.99993).astype(np.float32)      # редкие точки коррозии с тёмным ореолом
    pit = np.clip(cv2.GaussianBlur(pits, (0, 0), 2.2) * 60, 0, 1)
    pit_halo = np.clip(cv2.GaussianBlur(pits, (0, 0), 6.0) * 120 - pit, 0, 1)
    rust_amt = np.maximum(rust_amt, pit)
    orange = np.array([168, 88, 36], np.float32)
    brown = np.array([96, 48, 22], np.float32)
    dark = np.array([46, 24, 12], np.float32)
    k = np.clip(rust_n * 0.5 + 0.5, 0, 1)[..., None]
    rust_c = orange * k + brown * (1 - k)
    deep_c = np.clip(smooth_band(edge_d, 2.5) * 1.1 * edge_var + fbm(H, W, 6, rng, 2) * 0.3 - 0.45, 0, 1)[..., None]
    rust_c = rust_c * (1 - deep_c) + dark * deep_c                # глубокая коррозия у самого среза
    col = col * (1 - rust_amt[..., None]) + rust_c * rust_amt[..., None]
    col *= (1 - 0.35 * pit_halo)[..., None]
    # грязь в низинах и у кромки
    grime = np.clip(smooth_band(edge_d, 24.0) * 0.12 + np.clip(-hgt / 8, 0, 0.12), 0, 0.25)
    col *= (1 - grime)[..., None]
    # царапины
    scr = np.zeros((H, W), np.float32)
    for _ in range(90):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        ang, L = rng.normal(0.4, 0.5), rng.uniform(20, 160)
        x1, y1 = x0 + np.cos(ang) * L, y0 + np.sin(ang) * L
        cv2.line(scr, (int(x0), int(y0)), (int(x1), int(y1)), float(rng.uniform(0.2, 0.7)), 1, cv2.LINE_AA)
    col += scr[..., None] * 26 * (1 - chip[..., None])
    col *= relief[..., None]

    # ---------------------------------------------------------------- рваный край: срез, загиб, тень
    gxe = cv2.Sobel(dm, cv2.CV_32F, 1, 0, ksize=3)
    gye = cv2.Sobel(dm, cv2.CV_32F, 0, 1, ksize=3)
    nrm = np.sqrt(gxe ** 2 + gye ** 2) + 1e-6
    facing = (-(gxe / nrm) * LIGHT[0] - (gye / nrm) * LIGHT[1])  # край, обращённый к свету
    curl_sel = np.clip(fbm(H, W, 110, rng, 2) - 0.7, 0, 1)        # где кромка загнута к зрителю (местами)
    curl_w = 3.0 + 6.0 * curl_sel
    tcurl = dm / curl_w
    in_curl = (tcurl < 1.0) & (curl_sel > 0.05)
    prof = np.sin(np.clip(tcurl, 0, 1) * np.pi)                   # цилиндр загиба
    lip = np.where(in_curl, prof * (0.35 + 0.65 * np.clip(facing * 0.5 + 0.5, 0, 1)), 0)
    lip_rust = rust_c * (0.75 + 0.5 * np.clip(facing * 0.5 + 0.5, 0, 1))[..., None]   # загиб весь в ржавчине
    lip_mix = np.clip(lip * 1.3, 0, 1)[..., None]
    col = col * (1 - lip_mix) + lip_rust * lip_mix
    col *= np.where(in_curl & (tcurl > 0.6), 0.65, 1.0)[..., None]  # за загибом — тень
    cut = dm < 1.7                                                # срез металла (толщина листа)
    cut_c = (88 + 38 * np.clip(facing, -1, 1))[..., None] * np.array([1.0, 0.72, 0.5], np.float32)   # ржавый срез
    col = np.where(cut[..., None], cut_c, col)

    # тень корпуса на панели внутри выреза (от света сверху-слева), сильнее у загибов
    sh_src = cv2.GaussianBlur(metal.astype(np.float32), (0, 0), 5.0)
    M = np.float32([[1, 0, 4], [0, 1, 6]])
    shadow = cv2.warpAffine(sh_src, M, (W, H), borderValue=1.0)
    shadow = np.clip(shadow * (1.0 + 0.8 * cv2.GaussianBlur(curl_sel * (dm < 8), (0, 0), 6)), 0, 1)
    gap = np.clip(1 - di / 2.5, 0, 1) * hole                      # тёмная щель под самым срезом

    col = np.clip(col, 0, 255)
    bz = np.zeros((H, W), np.float32)                             # окантовка: серый пластик / краска по металлу
    bz_col = np.zeros((H, W, 3), np.float32)
    if bezel > 0:
        for name, (x0, y0, x1, y1) in rects.items():
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            ex, ey = (x1 - x0) / 2, (y1 - y0) / 2
            r_out = 12.0
            qx, qy = np.abs(xx - cx) - (ex + bezel) + r_out, np.abs(yy - cy) - (ey + bezel) + r_out
            sd = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2) + np.minimum(np.maximum(qx, qy), 0) - r_out
            inside_panel = (np.abs(xx - cx) <= ex) & (np.abs(yy - cy) <= ey)
            band = (sd <= 0) & ~inside_panel
            # пологий профиль: светлая верхне-левая фаска, тёмная нижне-правая
            fx = np.clip((xx - cx) / (ex + bezel), -1, 1)
            fy = np.clip((yy - cy) / (ey + bezel), -1, 1)
            outer_t = np.clip(-sd / bezel, 0, 1)                       # 0 — внешний край, 1 — у экрана
            shade = 1.0 + 0.10 * (-(fx * LIGHT[0] + fy * LIGHT[1])) * (1 - outer_t) - 0.18 * (outer_t > 0.82)
            grey = np.array([178, 176, 166], np.float32) * (0.93 + 0.07 * fbm(H, W, 20, rng, 2))[..., None]
            c = grey * shade[..., None]
            c *= (1 - 0.35 * np.clip(1 - np.abs(sd + 0.8) / 1.2, 0, 1))[..., None]           # тёмная внешняя грань
            bz = np.maximum(bz, band.astype(np.float32))
            bz_col = np.where(band[..., None], c, bz_col)
    return col, hole.astype(np.float32), shadow * hole, gap, bz, bz_col


def mockup(shot, rects_json, out):
    info = json.loads(open(rects_json, encoding="utf-8").read())
    ui = cv2.cvtColor(cv2.imdecode(np.fromfile(shot, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32)
    H, W = ui.shape[:2]
    col, hole, shadow, gap, bz, bz_col = render_shell(W, H, info["rects"])
    # панели — слабая фактура: лёгкая потёртость только на тёмных плашках (не на экранах)
    rng = np.random.default_rng(7)
    pan = np.zeros((H, W), np.float32)
    for name in ("top", "bank_l", "bank_r"):
        if name in info["rects"]:
            x0, y0, x1, y1 = (int(v) for v in info["rects"][name])
            pan[y0:y1, x0:x1] = 1
    lum = ui.mean(axis=2)
    soft = pan * (lum < 45) * (0.06 * fbm(H, W, 30, rng, 3) + 0.04 * fbm(H, W, 4, rng, 2))
    ui = ui * (1 + soft[..., None])
    inside = ui * (1 - 0.6 * shadow[..., None]) * (1 - 0.85 * gap[..., None])
    inside = inside * (1 - bz[..., None]) + bz_col * (1 - 0.55 * shadow[..., None]) * bz[..., None]
    img = col * (1 - hole[..., None]) + inside * hole[..., None]
    cv2.imwrite(out, cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    print(out)


def shell(W, H, rects_json, out):
    """Корпус для программы: непрозрачная картинка — жесть, серые окантовки, тёмная глубина вырезов с тенью.
    Панели программы рисуются поверх в своих прямоугольниках."""
    info = json.loads(open(rects_json, encoding="utf-8").read())
    col, hole, shadow, gap, bz, bz_col = render_shell(int(W), int(H), info["rects"])
    deep = np.array([7, 6, 5], np.float32) * np.ones_like(col)
    deep *= (1 - 0.6 * shadow[..., None]) * (1 - 0.85 * gap[..., None])
    inside = deep * (1 - bz[..., None]) + bz_col * (1 - 0.55 * shadow[..., None]) * bz[..., None]
    img = col * (1 - hole[..., None]) + inside * hole[..., None]
    ok, buf = cv2.imencode(".png", cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    open(out, "wb").write(buf.tobytes())                 # путь может быть с кириллицей — пишем байтами
    print(out)


if __name__ == "__main__":
    if sys.argv[1] == "mockup":
        mockup(*sys.argv[2:5])
    else:
        shell(*sys.argv[2:6])
