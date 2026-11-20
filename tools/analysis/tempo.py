import os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
def onset_env(f):
    e = f["flux"].astype(np.float64)
    k = int(FPS * 0.4); e = np.maximum(e - np.convolve(e, np.ones(k) / k, "same"), 0)
    return e / (e.std() + 1e-9)
def acf(x):
    n = len(x); F = np.fft.rfft(x - x.mean(), 2 * n); a = np.fft.irfft(F * np.conj(F))[:n]; return a / a[0]
def tempo_candidates(env, lo=60, hi=200):
    a = acf(env); lags = np.arange(int(FPS * 60 / hi), int(FPS * 60 / lo) + 1)
    s = a[lags]; order = np.argsort(s)[::-1]; out = []
    for i in order:
        if all(abs(lags[i] - lags[j]) > 2 for j, _ in out): out.append((i, s[i]))
        if len(out) == 4: break
    res = []
    for i, v in out:
        l = float(lags[i])
        if 0 < i < len(s) - 1:
            y0, y1, y2 = s[i-1], s[i], s[i+1]; den = y0 - 2*y1 + y2
            if den: l += 0.5 * (y0 - y2) / den
        res.append((60 * FPS / l, float(v)))
    return res
def beat_track(env, bpm, tight=100):
    """Ellis DP beat tracking."""
    period = 60 * FPS / bpm; n = len(env)
    score = env.copy(); back = -np.ones(n, int)
    lo, hi = int(round(period / 2)), int(round(period * 2))
    prange = np.arange(-hi, -lo + 1)
    pen = -tight * np.log(-prange / period) ** 2
    for t in range(hi, n):
        cand = score[t + prange] + pen; j = int(np.argmax(cand))
        score[t] = env[t] + cand[j]; back[t] = t + prange[j]
    t = int(np.argmax(score[-int(period * 2):])) + n - int(period * 2)
    beats = [t]
    while back[t] >= 0: t = back[t]; beats.append(t)
    return np.array(beats[::-1])
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); env = onset_env(f)
    cands = tempo_candidates(env)
    # локальный темп и «ясность пульса» в окнах 16 с
    W, H = int(16 * FPS), int(4 * FPS); loc = []
    for s in range(0, len(env) - W, H):
        c = tempo_candidates(env[s:s + W])[0]; loc.append((s / FPS, c[0], c[1]))
    loc = np.array(loc)
    strong = loc[loc[:, 2] > 0.3]
    print(f"\nТрек {k}: глобальные кандидаты BPM:", ", ".join(f"{b:.2f} ({v:.2f})" for b, v in cands))
    print(f"  локально (16с окна): медиана BPM {np.median(strong[:,1]) if len(strong) else 0:.2f}, "
          f"ясность пульса медиана {np.median(loc[:,2]):.2f}, доля окон с ясным пульсом {len(strong)/len(loc)*100:.0f}%")
    hist = np.round(strong[:, 1]).astype(int) if len(strong) else []
    if len(hist): u, c = np.unique(hist, return_counts=True); print("  распределение локальных BPM:", dict(zip(u[np.argsort(-c)][:6].tolist(), np.sort(c)[::-1][:6].tolist())))
    np.save(os.path.join(OUT, f"loc_{k}.npy"), loc)
