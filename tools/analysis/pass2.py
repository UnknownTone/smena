"""Второй проход: секции/гармония с робастным порогом, локальные акценты,
положение событий (вступление/концовка), выравнивание по фразам 4/8/16 тактов."""
import os, json, math, numpy as np
import importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
spec = importlib.util.spec_from_file_location("ch", os.path.join(HERE, "changes.py"))
J = json.load(open(os.path.join(OUT, "changes.json"), encoding="utf-8"))
R, TR = J["results"], J["tracks"]

# переиспользуем функции без повторного запуска основного цикла
src = open(os.path.join(HERE, "changes.py"), encoding="utf-8").read().split("\nW = 8\n")[0]
ns = {"__file__": os.path.join(HERE, "changes.py")}; exec(src, ns)
bar_edges, bar_features = ns["bar_edges"], ns["bar_features"]
TEMPO = ns["TEMPO"]


def rz(x):
    m = np.median(x); s = 1.4826 * np.median(np.abs(x - m)) + 1e-12; return (x - m) / s


def peaks_sep(score, mask, sep):
    keep = []
    for i in np.argsort(-score):
        if mask[i] and all(abs(i - j) >= sep for j in keep): keep.append(int(i))
    return sorted(keep)


W = 8
new = {"Смена части (новизна по всем признакам)": {}, "Смена гармонии / тонального центра": {},
       "Акцент: удар выше локального фона": {}, "Одновременная смена ≥3 признаков": {}}
level_feats = [n for n in R if not n.startswith(("Акцент", "Провал", "Нарастание", "Смена"))]
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); n = len(f["rms"])
    edges, L = bar_edges(f, TEMPO[k], n); bf = bar_features(f, edges); nb = len(edges) - 1
    cb = bf["_chroma"]
    hs = np.zeros(nb)
    for i in range(W, nb - W + 1):
        a, b = cb[i - W:i].mean(0), cb[i:i + W].mean(0); hs[i] = 1 - a @ b / np.linalg.norm(a) / np.linalg.norm(b)
    z = rz(hs[W:nb - W + 1]); zz = np.zeros(nb); zz[W:nb - W + 1] = z
    new["Смена гармонии / тонального центра"][k] = [
        {"bar": i, "t": round(edges[i] / FPS, 1), "delta": round(float(hs[i]), 4), "d": round(float(zz[i]), 1), "p": 0}
        for i in peaks_sep(zz, (zz > 5) & (hs > 0.01), W)]

    X = np.column_stack([(v - v.mean()) / (v.std() + 1e-9) for nm, v in bf.items() if not nm.startswith("_")])
    S = X @ X.T / X.shape[1]; Wk = 8; sg = np.r_[-np.ones(Wk), np.ones(Wk)]; g = np.outer(sg, sg)
    nov = np.zeros(nb)
    for i in range(Wk, nb - Wk): nov[i] = -(S[i - Wk:i + Wk, i - Wk:i + Wk] * g).sum() / (2 * Wk) ** 2
    zn = np.zeros(nb); zn[Wk:nb - Wk] = rz(nov[Wk:nb - Wk])
    new["Смена части (новизна по всем признакам)"][k] = [
        {"bar": i, "t": round(edges[i] / FPS, 1), "delta": round(float(nov[i]), 3), "d": round(float(zn[i]), 1), "p": 0}
        for i in peaks_sep(zn, zn > 4, Wk)]

    # одновременная значимая смена ≥3 разных признаков в пределах ±1 такта
    marks = np.zeros(nb + 2, int)
    for nm in level_feats:
        hit = np.zeros(nb + 2, bool)
        for e in R[nm].get(k, []):
            hit[max(0, e["bar"] - 1):e["bar"] + 2] = True
        marks += hit
    new["Одновременная смена ≥3 признаков"][k] = [
        {"bar": i, "t": round(edges[min(i, nb)] / FPS, 1), "delta": int(marks[i]), "d": 0, "p": 0}
        for i in peaks_sep(marks.astype(float), marks >= 3, 4)]

    # акценты: поток выше локального фона (медиана/MAD за 4 с) на 6 MAD и выше глобального 95-го перцентиля
    fl = f["flux"].astype(float); w = int(4 * FPS); h = w // 2
    loc_med = np.array([np.median(fl[max(0, i - h):i + h]) for i in range(0, n, 16)])
    loc_mad = np.array([np.median(np.abs(fl[max(0, i - h):i + h] - np.median(fl[max(0, i - h):i + h]))) for i in range(0, n, 16)])
    lm = np.repeat(loc_med, 16)[:n]; ld = np.repeat(loc_mad, 16)[:n] * 1.4826 + 1e-9
    zl = (fl - lm) / ld; g95 = np.percentile(fl, 99)
    cand = np.flatnonzero((zl > 6) & (fl > g95))
    pk = []
    for i in cand:
        if zl[i] == zl[max(0, i - 20):i + 21].max() and (not pk or i - pk[-1] > FPS * 1.0): pk.append(int(i))
    new["Акцент: удар выше локального фона"][k] = [
        {"bar": int(i / L), "t": round(i / FPS, 1), "delta": round(float(zl[i]), 1), "d": 0, "p": 0} for i in pk]

R.update(new)
R.pop("Акцент: одиночный сильный удар", None)
json.dump({"results": R, "tracks": TR}, open(os.path.join(OUT, "changes2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---------- сводка ----------
mins = sum(v["dur"] for v in TR.values()) / 60
print(f"{'признак':45s} {'по трекам':16s} всего  /мин  треков |d|   |Δ|   вступл/конц  в теле")
rows = []
for name, tr in R.items():
    cnt = [len(tr.get(k, [])) for k in "1234"]; allev = []
    edge = 0
    for k in "1234":
        for e in tr.get(k, []):
            allev.append(e)
            if e["t"] < 20 or e["t"] > TR[k]["dur"] - 25: edge += 1
    ds = [abs(e["d"]) for e in allev if e["d"]]
    rows.append((name, cnt, sum(cnt), sum(c > 0 for c in cnt), np.median(ds) if ds else float("nan"),
                 np.median([abs(e["delta"]) for e in allev]) if allev else float("nan"), edge))
rows.sort(key=lambda r: (-r[3], -(r[2] - r[6])))
for r in rows:
    print(f"{r[0]:45s} {str(r[1]):16s} {r[2]:4d} {r[2]/mins:5.2f}   {r[3]}   {r[4]:4.1f} {r[5]:6.2f}   {r[6]:3d}        {r[2]-r[6]:3d}")

# ---------- выравнивание по фразам (только треки с сеткой) ----------
print("\nПоложение значимых смен уровня внутри фраз (треки 2, 3):")
for k in "23":
    bars = sorted({e["bar"] for nm in level_feats + ["Одновременная смена ≥3 признаков"] for e in R[nm].get(k, [])})
    for M in (4, 8, 16):
        ph = np.array(bars) % M
        ang = 2 * np.pi * ph / M; Rb = abs(np.exp(1j * ang).mean()); nn = len(ang)
        p = math.exp(-nn * Rb * Rb) * (1 + (2 * nn * Rb * Rb - (nn * Rb * Rb) ** 2) / (4 * nn) - (24 * nn * Rb * Rb - 132 * (nn * Rb * Rb) ** 2 + 76 * (nn * Rb * Rb) ** 3 - 9 * (nn * Rb * Rb) ** 4) / (288 * nn * nn))
        u, c = np.unique(ph, return_counts=True)
        print(f"  трек {k}, mod {M:2d}: n={nn}, Рэлей p={max(p,0):.3g}, чаще всего: {dict(sorted(zip(u.tolist(), c.tolist()), key=lambda x: -x[1])[:4])}")

# ---------- хронология по трекам ----------
for k in "1234":
    print(f"\nТрек {k} ({TR[k]['dur']/60:.1f} мин): крупные события")
    for nm in ["Смена части (новизна по всем признакам)", "Одновременная смена ≥3 признаков"]:
        print(f"  {nm}: " + ", ".join(f"{int(e['t']//60)}:{int(e['t']%60):02d}" for e in R[nm].get(k, [])))
