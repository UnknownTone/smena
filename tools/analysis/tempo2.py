import os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
FPS = 44100 / 512
def hp(x, s=0.4):
    k = int(FPS * s); return x - np.convolve(x, np.ones(k) / k, "same")
def acf(x):
    n = len(x); x = x - x.mean(); F = np.fft.rfft(x, 2 * n); a = np.fft.irfft(F * np.abs(F) ** 0 * np.conj(F))[:n]; return a / a[0]
def peaks(x, lo=50, hi=200, k=5):
    a = acf(x); lags = np.arange(int(FPS*60/hi), int(FPS*60/lo)+1); s = a[lags]
    loc = [i for i in range(1, len(s)-1) if s[i] > s[i-1] and s[i] >= s[i+1]]
    loc.sort(key=lambda i: -s[i]); return [(round(60*FPS/lags[i], 1), round(float(s[i]), 3)) for i in loc[:k]]
for k in "1234":
    f = np.load(os.path.join(OUT, f"feat_{k}.npz")); n = len(f["rms"]); sl = slice(int(10*FPS), n - int(15*FPS))
    print(f"\nТрек {k}")
    for name in ["flux", "flux_sub", "flux_bass", "flux_lowmid", "flux_mid", "flux_himid", "flux_high"]:
        x = np.maximum(hp(f[name].astype(float)), 0)[sl]; print(f"  {name:12s}", peaks(x))
    for name in ["e_bass", "e_mid", "e_himid", "e_high", "rms", "centroid"]:
        x = hp(np.log(f[name].astype(float) + 1e-10), 1.5)[sl]; print(f"  ~{name:11s}", peaks(x))
