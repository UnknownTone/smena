"""SMENA — отрывки по N секунд из каждого трека альбома на отобранных фото, по нумерации.

Фото (отсортированные по имени папки кеша) делятся между треками диапазонами (--ranges 16,13,16,11).
В каждом треке: самое насыщенное окно → ближайшая к его середине смена фото (граница цикла 16 тактов) →
отрывок: половина до смены, половина после. Фото — те, что по нумерации стоят в этот момент трека.

Запуск (.venv-prep):
    .venv-prep\\Scripts\\python.exe tools\\render\\album_clips.py КЕШ ВЫХОД.mp4 ТРЕК1 ТРЕК2 ТРЕК3 ТРЕК4
        [--bpms 120,139.6,120.2,120] [--ranges 16,13,16,11] [--clip 25]
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_demo as rd   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cache")
    ap.add_argument("out")
    ap.add_argument("tracks", nargs="+")
    ap.add_argument("--bpms", default="120,139.6,120.2,120")
    ap.add_argument("--ranges", default="16,13,16,11")
    ap.add_argument("--clip", type=float, default=25.0)
    a = ap.parse_args()
    names = [d.name for d in sorted(Path(a.cache).iterdir()) if (d / "photo.json").exists()]
    sizes = [int(x) for x in a.ranges.split(",")]
    bpms = [float(x) for x in a.bpms.split(",")]
    starts = np.cumsum([0] + sizes)
    out = Path(a.out)
    parts = {"": [], "_hud": []}
    half = a.clip / 2
    for i, track in enumerate(a.tracks):
        rng = names[starts[i]:starts[i + 1]]
        audio = rd.load_audio(track)
        F = rd.features(audio)
        L = len(audio) / rd.SR
        beat0, beat = rd.beat_grid(F, bpms[i], L)
        T = 64 * beat
        ev = rd.detect_events(F, beat)
        t_act = rd.choose_start(ev, F, a.clip, beat0, beat, L)
        ks = [k for k in range(1, len(rng)) if beat0 + k * T - half >= 0 and beat0 + k * T + half <= L - 1]
        k = min(ks, key=lambda k: abs(beat0 + k * T - (t_act + half)))
        b = beat0 + k * T
        A, B = rng[k - 1], rng[k]
        print(f"трек {i + 1}: {bpms[i]} BPM, T={T:.1f} с, смена фото в {int(b // 60)}:{b % 60:04.1f} — "
              f"фото №{starts[i] + k} «{A}» → №{starts[i] + k + 1} «{B}»", flush=True)
        clip = out.with_name(f"{out.stem}_track{i + 1}.mp4")
        subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).with_name("render_demo.py")), track, a.cache,
                        str(clip), "--photos", f"{A},{B}", "--bpm", str(bpms[i]), "--tbars", "16",
                        "--start", f"{b - T:.3f}", "--dur", f"{T + half:.3f}", "--skip", f"{T - half:.3f}"],
                       check=True, stdout=subprocess.DEVNULL)
        parts[""].append(clip)
        parts["_hud"].append(clip.with_name(clip.stem + "_hud.mp4"))
    for tag, files in parts.items():
        lst = out.with_name(f"{out.stem}{tag}_list.txt")
        lst.write_text("".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8")
        subprocess.run([rd.FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out.with_name(out.stem + tag + ".mp4"))], check=True)
        lst.unlink()
    print("готово:", out, out.with_name(out.stem + "_hud.mp4"))


if __name__ == "__main__":
    main()
