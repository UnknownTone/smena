"""Статистически значимые изменения признаков на уровне тактов."""
import os, math, json, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
TEMPO = {"1": None, "2": 139.6, "3": 120.2, "4": None}   # None -> псевдо-такт 2 с


# ---------- t-распределение без scipy ----------
def betacf(a, b, x):
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny); h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c; c = c if abs(c) > tiny else tiny; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c; c = c if abs(c) > tiny else tiny
        de = d * c; h *= de
        if abs(de - 1) < 1e-12:
            break
    return h


def betai(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return bt * betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1 - bt * betacf(b, a, 1 - x) / b


def p_two(t, df):
    return betai(df / 2, 0.5, df / (df + t * t))


def db(x):
    return 10 * np.log10(np.asarray(x, float) + 1e-10)


def bar_edges(f, bpm, n):
    if bpm is None:
        L = 2.0 * FPS
        return np.arange(0, n, L).astype(int), L
    L = 4 * 60 * FPS / bpm; p = 60 * FPS / bpm
    env = f["flux_bass"].astype(float) + 0.3 * f["flux"].astype(float)
    cand = np.arange(0, p, 1.0)
    sc = [env[np.arange(o, n, p).astype(int)].sum() for o in cand]
    bo = cand[int(np.argmax(sc))]
    best = max(range(4), key=lambda q: env[np.arange(bo + q * p, n, L).astype(int)].sum())
    return np.arange(bo + best * p, n, L).astype(int), L


def bar_features(f, edges):
    ch = f["chroma"]; out = {}
    seg = list(zip(edges[:-1], edges[1:]))
    def agg(x, fn=np.mean): return np.array([fn(x[a:b]) for a, b in seg])
    out["Громкость RMS, дБ"] = db(agg(f["rms"].astype(float) ** 2))
    for k, nm in [("sub", "Суббас 20–60, дБ"), ("bass", "Бас 60–150, дБ"), ("lowmid", "Низкая середина 150–500, дБ"),
                  ("mid", "Середина 0.5–2 кГц, дБ"), ("himid", "Верхняя середина 2–6 кГц, дБ"), ("high", "Верх 6–16 кГц, дБ")]:
        out[nm] = db(agg(f[f"e_{k}"].astype(float)))
    out["Яркость (центроид), log2 Гц"] = np.log2(agg(f["centroid"].astype(float)))
    out["Шумность (плоскостность), log"] = np.log10(agg(f["flatness"].astype(float)) + 1e-9)
    out["Доля ударного (HPSS)"] = agg(f["perc_ratio"].astype(float))
    out["Стерео-ширина S/M"] = agg(f["side_ratio"].astype(float))
    out["Плотность атак (flux)"] = np.log(agg(f["flux"].astype(float)) + 1e-9)
    out["Атаки баса (бочка)"] = np.log(agg(f["flux_bass"].astype(float)) + 1e-9)
    out["Атаки верха (хэты)"] = np.log(agg(f["flux_high"].astype(float)) + 1e-9)
    out["Пик-фактор (динамика), дБ"] = db(agg(f["peak"].astype(float) ** 2, np.max)) - out["Громкость RMS, дБ"]
    out["Модуляция яркости в такте"] = agg(np.log2(f["centroid"].astype(float) + 1), np.std)
    out["Модуляция баса в такте (wobble)"] = agg(db(f["e_bass"]), np.std)
    cb = np.array([ch[a:b].mean(0) for a, b in seg]); cb /= cb.sum(1, keepdims=True)
    out["Тональная ясность (хрома)"] = 1 - (-(cb * np.log(cb + 1e-12)).sum(1)) / np.log(12)
    out["_chroma"] = cb
    return out


def welch_scan(x, W):
    n = len(x); T = np.zeros(n); D = np.zeros(n); P = np.ones(n); M = np.zeros(n)
    for i in range(W, n - W + 1):
        a, b = x[i - W:i], x[i:i + W]; va, vb = a.var(ddof=1), b.var(ddof=1)
        se = math.sqrt(va / W + vb / W) + 1e-12; t = (b.mean() - a.mean()) / se
        df = (va / W + vb / W) ** 2 / ((va / W) ** 2 / (W - 1) + (vb / W) ** 2 / (W - 1) + 1e-30)
        T[i] = t; D[i] = (b.mean() - a.mean()) / math.sqrt((va + vb) / 2 + 1e-12)
        P[i] = p_two(abs(t), max(df, 1)); M[i] = b.mean() - a.mean()
    return T, D, P, M


def peaks_sep(score, mask, sep):
    keep = []
    for i in np.argsort(-score):
        if mask[i] and all(abs(i - j) >= sep for j in keep):
            keep.append(int(i))
    return sorted(keep)


# минимальная «слышимая» величина изменения
def jnd(name):
    if "дБ" in name and "Пик" not in name: return 1.5
    if "Пик" in name: return 1.0
    if "log2" in name: return 0.15
    if "Шумность" in name: return 0.15
    if "HPSS" in name: return 0.03
    if "S/M" in name: return 0.05
    if "Атаки" in name or "атак" in name: return 0.15
    if "wobble" in name: return 0.4
    if "Модуляция яркости" in name: return 0.03
    if "хрома" in name: return 0.01
    return 0


def ev(i, t, delta, d=0.0, p=0.0):
    return {"bar": int(i), "t": round(float(t), 1), "delta": round(float(delta), 3), "d": round(float(d), 2), "p": float(p)}


W = 8
results = {}; per_track = {}
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); n = len(f["rms"])
    edges, L = bar_edges(f, TEMPO[k], n)
    bf = bar_features(f, edges); nb = len(edges) - 1
    per_track[k] = {"bars": nb, "bar_s": L / FPS, "dur": n / FPS, "edges": (edges / FPS).round(3).tolist()}
    alpha = 0.01 / max(nb - 2 * W, 1)                     # Бонферрони по позициям
    for name, x in bf.items():
        if name.startswith("_"): continue
        T, D, P, M = welch_scan(x, W)
        sig = (P < alpha) & (np.abs(D) > 2.0) & (np.abs(M) >= jnd(name))
        results.setdefault(name, {})[k] = [ev(i, edges[i] / FPS, M[i], D[i], P[i]) for i in peaks_sep(np.abs(T), sig, W)]

    # гармонические смены: косинусное расстояние хромы 8 до / 8 после, порог — блочные перестановки
    cb = bf["_chroma"]
    def hscan(c):
        h = np.zeros(len(c))
        for i in range(W, len(c) - W + 1):
            a, b = c[i - W:i].mean(0), c[i:i + W].mean(0); h[i] = 1 - a @ b / np.linalg.norm(a) / np.linalg.norm(b)
        return h
    hs = hscan(cb); rng = np.random.default_rng(0); null = []
    blocks = [cb[i:i + 4] for i in range(0, nb, 4)]
    for _ in range(100):
        null.append(hscan(np.vstack([blocks[j] for j in rng.permutation(len(blocks))])).max())
    thr = np.quantile(null, 0.99)                        # 1% по максимуму трека — уже с поправкой
    results.setdefault("Смена гармонии / тонального центра", {})[k] = [ev(i, edges[i] / FPS, hs[i]) for i in peaks_sep(hs, hs > thr, W)]

    # секции: новизна Фута по всем признакам
    X = np.column_stack([(v - v.mean()) / (v.std() + 1e-9) for nm, v in bf.items() if not nm.startswith("_")] + [cb * 3])
    S = X @ X.T / X.shape[1]; Wk = 8
    sgn = np.r_[-np.ones(Wk), np.ones(Wk)]; g = np.outer(sgn, sgn)
    nov = np.zeros(nb)
    for i in range(Wk, nb - Wk): nov[i] = -(S[i - Wk:i + Wk, i - Wk:i + Wk] * g).sum() / (2 * Wk) ** 2
    def novscan(Xp):
        Sp = Xp @ Xp.T / Xp.shape[1]; o = np.zeros(len(Xp))
        for i in range(Wk, len(Xp) - Wk): o[i] = -(Sp[i - Wk:i + Wk, i - Wk:i + Wk] * g).sum() / (2 * Wk) ** 2
        return o.max()
    bl = [X[i:i + 4] for i in range(0, nb, 4)]
    nnull = [novscan(np.vstack([bl[j] for j in rng.permutation(len(bl))])) for _ in range(100)]
    nthr = np.quantile(nnull, 0.95)
    results.setdefault("Смена части (новизна по всем признакам)", {})[k] = [ev(i, edges[i] / FPS, nov[i]) for i in peaks_sep(nov, nov > nthr, Wk)]

    # провалы: RMS (0.25 с) ниже медианы на ≥6 дБ
    kk = int(.25 * FPS); r = db(np.convolve(f["rms"].astype(float) ** 2, np.ones(kk) / kk, "same")); med = np.median(r)
    low = r < med - 6; low[-int(10 * FPS):] = False; low[:int(3 * FPS)] = False
    st = np.flatnonzero(np.diff(low.astype(int)) == 1)
    results.setdefault("Провал / пауза (−6 дБ, ≥0.25 с)", {})[k] = [ev(s / L, s / FPS, r[min(s + 5, n - 1)] - med) for s in st]

    # акценты: одиночные удары, поток > медиана + 8·MAD
    fl = f["flux"].astype(float); z = (fl - np.median(fl)) / (1.4826 * np.median(np.abs(fl - np.median(fl))) + 1e-9)
    pk = [i for i in np.flatnonzero(z > 8) if z[i] == z[max(0, i - 20):i + 21].max()]
    pk2 = []
    for i in pk:
        if not pk2 or i - pk2[-1] > FPS * 0.5: pk2.append(i)
    results.setdefault("Акцент: одиночный сильный удар", {})[k] = [ev(i / L, i / FPS, z[i]) for i in pk2]

    # нарастания: значимый линейный рост за 8 тактов
    for name in ["Яркость (центроид), log2 Гц", "Верх 6–16 кГц, дБ", "Шумность (плоскостность), log"]:
        x = bf[name]; ts = np.zeros(nb); ok = np.zeros(nb, bool); sl = np.zeros(nb)
        t_ = np.arange(8.0); sxx = ((t_ - t_.mean()) ** 2).sum()
        for i in range(0, nb - 8):
            y = x[i:i + 8]; b = np.polyfit(t_, y, 1); res = y - np.polyval(b, t_)
            se = math.sqrt((res @ res) / 6 / sxx) + 1e-12; tt = b[0] / se
            ts[i] = tt; sl[i] = b[0] * 8
            ok[i] = tt > 0 and p_two(tt, 6) < 0.01 / max(nb, 1) and b[0] * 8 >= 2 * jnd(name)
        results.setdefault(f"Нарастание: {name.split(',')[0]}", {})[k] = [ev(i, edges[i] / FPS, sl[i]) for i in peaks_sep(ts, ok, 8)]

json.dump({"results": results, "tracks": per_track}, open(os.path.join(OUT, "changes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

mins = sum(v["dur"] for v in per_track.values()) / 60
rows = []
for name, tr in results.items():
    cnt = [len(tr.get(k, [])) for k in "1234"]; allev = [e for k in "1234" for e in tr.get(k, [])]
    ds = [abs(e["d"]) for e in allev if e["d"]]
    rows.append((name, cnt, sum(cnt), sum(c > 0 for c in cnt), np.median(ds) if ds else float("nan"),
                 np.median([abs(e["delta"]) for e in allev]) if allev else float("nan")))
rows.sort(key=lambda r: (-r[3], -r[2]))
print(f"Всего {mins:.1f} мин. Тактов:", {k: v["bars"] for k, v in per_track.items()})
for r in rows:
    print(f"{r[0]:45s} {str(r[1]):16s} всего {r[2]:3d}  треков {r[3]}  |d| {r[4]:.1f}  |Δ| {r[5]:.2f}")
