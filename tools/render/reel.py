r"""Ролик для Instagram Reels (1080×1920): заставка SMENA (intro_vhs, вертикаль) → шумовой VHS-переход →
запись SMENA (REC, 1920×1080: вырез 9:16 с медленным сдвигом вбок) → шумовое затухание. Всё — через ту же
VHS-плёнку; звук — трек с самого начала, плавный уход в конце.

Запуск: .venv-prep\Scripts\python.exe tools\render\reel.py <кадры интерфейса> <запись.mp4> <трек> <выход.mp4>
"""
import math
import subprocess
import sys

import cv2
import numpy as np

import intro_vhs as IV

XF = 0.7                    # длительность шумового перехода, с
END = 1.2                   # шумовое затухание в конце, с


def probe(path):
    r = subprocess.run([IV.B.ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def noise_mix(a, b, u, tt):
    """Переход «плёнка дёрнулась»: снег, прокрутка кадра, рваные строки; посередине — почти только шум."""
    H, W = a.shape[:2]
    amt = math.sin(math.pi * u) ** 0.8
    rng = np.random.default_rng(int(tt * 1000) + 7)
    base = a * (1 - u) + b * u
    roll = int(amt * H * 0.12 * math.sin(tt * 23.0))
    base = np.roll(base, roll, axis=0)
    rows = rng.random(H) < 0.08 * amt                                              # рваные строки
    shift = rng.integers(-80, 80, H) * rows
    idx = (np.arange(W)[None, :] - shift[:, None]) % W
    base = np.take_along_axis(base, np.repeat(idx[..., None], 3, axis=2), axis=1)
    snow = rng.random((H // 2, W // 2, 1)).astype(np.float32) * 255
    snow = cv2.resize(snow, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
    k = 0.65 * amt
    return base * (1 - k) + snow * k


def user_frames(path, fps):
    """Кадры записи (1920×1080 → вырез 9:16, мягкий сдвиг вбок) как float BGR 1080×1920."""
    p = subprocess.Popen([IV.B.ffmpeg(), "-v", "error", "-i", path, "-r", str(fps), "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    n = 0
    while True:
        raw = p.stdout.read(1920 * 1080 * 3)
        if len(raw) < 1920 * 1080 * 3:
            break
        f = np.frombuffer(raw, np.uint8).reshape(1080, 1920, 3)
        t = n / fps
        cw = 608
        cx = 960 + 520 * math.sin(2 * math.pi * t / 46.0)                      # медленная панорама
        x0 = int(min(max(cx - cw / 2, 0), 1920 - cw))
        crop = f[:, x0:x0 + cw]
        yield cv2.resize(crop, (IV.W, IV.H), interpolation=cv2.INTER_CUBIC).astype(np.float32)
        n += 1
    p.wait()


def main():
    cap_dir, rec, track, out = sys.argv[1:5]
    IV.configure(True)
    W, H, FPS = IV.W, IV.H, IV.FPS
    vhs = IV.VHS()
    t_user = probe(rec)
    intro_len = IV.DUR
    total = intro_len - XF + t_user
    n_total = int(total * FPS)
    proc = subprocess.Popen(
        [IV.B.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-ss", "0", "-t", f"{total:.3f}", "-i", track,
         "-af", f"afade=t=in:st=0:d=0.15,afade=t=out:st={total - 2.5:.3f}:d=2.5",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "25M",
         "-bufsize", "50M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest",
         "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    times = [i / FPS for i in range(int(intro_len * FPS))]
    intro = IV.scene(cap_dir, times)
    user = user_frames(rec, FPS)
    xf_start = intro_len - XF
    pending_user = None
    fi = 0
    for tt, frame in zip(times, intro):                                     # заставка (+ начало перехода)
        if tt >= xf_start:
            pending_user = next(user)
            frame = noise_mix(frame, pending_user, (tt - xf_start) / XF, tt)
        proc.stdin.write(vhs(frame, tt).tobytes())
        fi += 1
        if fi % 150 == 0:
            print(f"кадр {fi}/{n_total}", flush=True)
    for frame in user:                                                      # запись SMENA
        tt = fi / FPS
        if tt > total - END:                                                # шумовое затухание
            u = (tt - (total - END)) / END
            frame = noise_mix(frame, np.zeros_like(frame), min(u, 1.0), tt)
        proc.stdin.write(vhs(frame, tt).tobytes())
        fi += 1
        if fi % 150 == 0:
            print(f"кадр {fi}/{n_total}", flush=True)
        if fi >= n_total:
            break
    proc.stdin.close()
    proc.wait()
    print("готово:", out, f"{total:.1f} с")


if __name__ == "__main__":
    sys.path.insert(0, str(IV.ROOT / "tools" / "render"))
    main()
