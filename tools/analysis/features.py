"""Покадровые признаки для 4 треков -> npz."""
import os, sys, numpy as np
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame
from numpy.lib.stride_tricks import sliding_window_view as swv
SR, NFFT, HOP = 44100, 2048, 512
D = sys.argv[1]   # папка с треками альбома: "1. Name.flac", "2. Name.mp3", ...
# один файл на номер трека, FLAC предпочтительнее MP3
_by = {}
for _f in sorted(os.listdir(D)):
    if _f[:1].isdigit() and _f.lower().endswith((".flac", ".mp3", ".wav")):
        _k = _f.split(".")[0]
        if _k not in _by or _f.lower().endswith(".flac"):
            _by[_k] = _f
TRACKS = [_by[k] for k in sorted(_by, key=int)]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PHOTOVJ_WORK", os.path.join(HERE, "..", "..", "data", "analysis", "work"))
os.makedirs(OUT, exist_ok=True)
pygame.mixer.init(frequency=SR, size=-16, channels=2)
freqs = np.fft.rfftfreq(NFFT, 1 / SR)
BANDS = {"sub": (20, 60), "bass": (60, 150), "lowmid": (150, 500), "mid": (500, 2000),
         "himid": (2000, 6000), "high": (6000, 16000)}
bmask = {k: (freqs >= a) & (freqs < b) for k, (a, b) in BANDS.items()}
# 96 лог-полос для HPSS
edges = np.geomspace(30, 16000, 97)
lb = np.clip(np.digitize(freqs, edges) - 1, -1, 96); lb[(freqs < 30) | (freqs >= 16000)] = -1
M = np.zeros((96, len(freqs)), np.float32)
for i in range(96): M[i, lb == i] = 1
M /= np.maximum(M.sum(1, keepdims=True), 1)
# хрома
cm = (freqs >= 55) & (freqs < 4200)
pc = np.zeros(len(freqs), int); pc[cm] = np.round(69 + 12 * np.log2(freqs[cm] / 440)).astype(int) % 12
C = np.zeros((12, len(freqs)), np.float32)
for i in range(12): C[i, cm & (pc == i)] = 1
win = np.hanning(NFFT).astype(np.float32)

for name in TRACKS:
    a = pygame.sndarray.array(pygame.mixer.Sound(os.path.join(D, name))).astype(np.float32) / 32768
    L, R = a[:, 0], a[:, 1]; mono = (L + R) / 2; side = (L - R) / 2
    n = (len(mono) - NFFT) // HOP + 1
    feats = {k: np.zeros(n, np.float32) for k in
             ["rms", "side_ratio", "centroid", "rolloff", "flatness", "flux", "peak"] +
             [f"e_{b}" for b in BANDS] + [f"flux_{b}" for b in BANDS]}
    chroma = np.zeros((n, 12), np.float32); logb = np.zeros((n, 96), np.float32)
    prev = None
    for s in range(0, n, 4096):
        idx = np.arange(s, min(n, s + 4096))
        fr = swv(mono, NFFT)[::HOP][idx] * win
        frs = swv(side, NFFT)[::HOP][idx]
        P = np.abs(np.fft.rfft(fr, axis=1)) ** 2 + 1e-12
        feats["rms"][idx] = np.sqrt((swv(mono, NFFT)[::HOP][idx] ** 2).mean(1))
        feats["peak"][idx] = np.abs(swv(mono, NFFT)[::HOP][idx]).max(1)
        feats["side_ratio"][idx] = np.sqrt((frs ** 2).mean(1)) / (feats["rms"][idx] + 1e-6)
        tot = P.sum(1)
        feats["centroid"][idx] = (P * freqs).sum(1) / tot
        cs = np.cumsum(P, 1); feats["rolloff"][idx] = freqs[(cs < 0.85 * tot[:, None]).sum(1)]
        Pm = P[:, (freqs > 50) & (freqs < 16000)]
        feats["flatness"][idx] = np.exp(np.log(Pm).mean(1)) / Pm.mean(1)
        for b, m in bmask.items(): feats[f"e_{b}"][idx] = P[:, m].sum(1)
        lg = np.log1p(np.sqrt(P) * 100)
        d = np.diff(np.vstack([lg[:1] if prev is None else prev, lg]), axis=0).clip(0)
        prev = lg[-1:]
        feats["flux"][idx] = d[:, freqs < 16000].sum(1)
        for b, m in bmask.items(): feats[f"flux_{b}"][idx] = d[:, m].sum(1)
        chroma[idx] = P @ C.T; logb[idx] = P @ M.T
    # HPSS по 96 полосам: гармоническое = медиана по времени, ударное = по частоте
    H = np.median(swv(np.pad(logb, ((15, 15), (0, 0)), mode="edge"), 31, axis=0), axis=-1)
    Pp = np.median(swv(np.pad(logb, ((0, 0), (4, 4)), mode="edge"), 9, axis=1), axis=-1)
    feats["perc_ratio"] = (Pp.sum(1) / (Pp.sum(1) + H.sum(1) + 1e-12)).astype(np.float32)
    chroma /= chroma.sum(1, keepdims=True) + 1e-12
    np.savez_compressed(os.path.join(OUT, f"feat_{name[0]}.npz"), chroma=chroma, **feats)
    print(name, n, "кадров", f"{len(mono)/SR/60:.2f} мин", flush=True)
