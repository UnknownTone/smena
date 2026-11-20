import os, json, math, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
J = json.load(open(os.path.join(OUT, "changes2.json"), encoding="utf-8")); R, TR = J["results"], J["tracks"]
src = open(os.path.join(HERE, "changes.py"), encoding="utf-8").read().split("\nW = 8\n")[0]
ns = {"__file__": os.path.join(HERE, "changes.py")}; exec(src, ns)
p_two = ns["p_two"]


def acf(x):
    n = len(x); x = x - x.mean(); F = np.fft.rfft(x, 2 * n); a = np.fft.irfft(F * np.conj(F))[:n]; return a / (a[0] + 1e-12)


print("Ясность пульса: среднее по треку и значимые смены (окна 8 с, шаг 2 с; 6 окон до/после)")
R["Ритмичность (ясность пульса)"] = {}
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); fl = f["flux"].astype(float)
    kk = int(.4 * FPS); env = np.maximum(fl - np.convolve(fl, np.ones(kk) / kk, "same"), 0)
    W8, H = int(8 * FPS), int(2 * FPS); lo, hi = int(FPS * 60 / 200), int(FPS * 60 / 50)
    pc = np.array([acf(env[s:s + W8])[lo:hi].max() for s in range(0, len(env) - W8, H)])
    t0 = np.arange(len(pc)) * 2 + 4
    ev = []; Wn = 6; best = []
    for i in range(Wn, len(pc) - Wn):
        a, b = pc[i - Wn:i], pc[i:i + Wn]; va, vb = a.var(ddof=1), b.var(ddof=1)
        t = (b.mean() - a.mean()) / (math.sqrt(va / Wn + vb / Wn) + 1e-12)
        df = (va / Wn + vb / Wn) ** 2 / ((va / Wn) ** 2 / (Wn - 1) + (vb / Wn) ** 2 / (Wn - 1) + 1e-30)
        d = (b.mean() - a.mean()) / math.sqrt((va + vb) / 2 + 1e-12)
        if p_two(abs(t), max(df, 1)) < 0.01 / len(pc) and abs(b.mean() - a.mean()) > 0.1 and abs(d) > 2:
            best.append((abs(t), i, b.mean() - a.mean(), d))
    keep = []
    for s in sorted(best, reverse=True):
        if all(abs(s[1] - j[1]) >= Wn for j in keep): keep.append(s)
    keep.sort(key=lambda s: s[1])
    R["Ритмичность (ясность пульса)"][k] = [{"bar": 0, "t": float(t0[i]), "delta": round(float(dl), 3), "d": round(float(d), 2), "p": 0} for _, i, dl, d in keep]
    print(f"  трек {k}: средняя {pc.mean():.2f}, 10–90% [{np.percentile(pc,10):.2f}..{np.percentile(pc,90):.2f}]; смены: " +
          ", ".join(f"{int(t0[i]//60)}:{int(t0[i]%60):02d} ({dl:+.2f})" for _, i, dl, d in keep))

print("\nПровалы по трекам (время):")
for k in "1234":
    print(f"  трек {k}: " + ", ".join(f"{int(e['t']//60)}:{int(e['t']%60):02d}" for e in R["Провал / пауза (−6 дБ, ≥0.25 с)"][k]))
print("\nСмена гармонии:")
for k in "1234":
    print(f"  трек {k}: " + ", ".join(f"{int(e['t']//60)}:{int(e['t']%60):02d} (z={e['d']})" for e in R["Смена гармонии / тонального центра"][k]))
print("\nАкценты: интервалы между соседними (медиана, с) и доля в 'кластерах' (<4 с):")
for k in "1234":
    t = np.array([e["t"] for e in R["Акцент: удар выше локального фона"][k]])
    if len(t) > 1:
        d = np.diff(t); print(f"  трек {k}: n={len(t)}, медиана {np.median(d):.1f} с, кластеры {np.mean(d < 4)*100:.0f}%")
print("\nПримеры уровней (бас, суббас, верх, центроид) — величины значимых смен:")
for nm in ["Бас 60–150, дБ", "Суббас 20–60, дБ", "Верх 6–16 кГц, дБ", "Яркость (центроид), log2 Гц", "Стерео-ширина S/M", "Доля ударного (HPSS)"]:
    vals = [e["delta"] for k in "1234" for e in R[nm][k]]
    print(f"  {nm:30s} вверх {sum(v>0 for v in vals)}, вниз {sum(v<0 for v in vals)}, медиана |Δ| {np.median(np.abs(vals)):.2f}, макс {np.max(np.abs(vals)):.2f}")
json.dump({"results": R, "tracks": TR}, open(os.path.join(OUT, "changes3.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
