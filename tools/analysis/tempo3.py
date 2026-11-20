import os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
def hp(x, s=0.4): k = int(FPS*s); return x - np.convolve(x, np.ones(k)/k, "same")
def acf(x):
    n = len(x); x = x - x.mean(); F = np.fft.rfft(x, 2*n); a = np.fft.irfft(F*np.conj(F))[:n]; return a/a[0]
def comb(a, bpm, K=32):
    p = 60*FPS/bpm; ks = np.arange(1, K+1)*p; i = ks.astype(int); fr = ks - i
    ok = i+1 < len(a); return float(np.mean(a[i[ok]]*(1-fr[ok]) + a[i[ok]+1]*fr[ok]))
grid = np.arange(100, 160, 0.05)
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); n = len(f["rms"]); sl = slice(int(10*FPS), n-int(15*FPS))
    env = sum(np.maximum(hp(f[b].astype(float)), 0)[sl] / (np.maximum(hp(f[b].astype(float)), 0)[sl].std()+1e-9)
              for b in ["flux","flux_bass","flux_mid","flux_high","flux_lowmid","flux_himid"])
    a = acf(env)
    s = np.array([comb(a, b, 64) for b in grid])   # 64 доли ~ 32 с при 120
    z = (s - np.median(s)) / (1.4826*np.median(np.abs(s-np.median(s))) + 1e-12)
    top = np.argsort(-s)[:5]
    print(f"Трек {k}: лучшие BPM (гребёнка 64 доли):", ", ".join(f"{grid[i]:.2f} z={z[i]:.1f}" for i in top))
