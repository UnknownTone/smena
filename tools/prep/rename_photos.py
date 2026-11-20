"""SMENA — переименование фото под порядок показа (data/photo_order.json) вместе с кешами.

Фото: «старое имя.jpg» → «NN - старое имя.jpg» (номер задаёт порядок в программе; прежний «NN - » заменяется).
Синхронно: папки кешей (кандидаты SAM, элементы) и их photo.json / cands.json, ключи в selection*.json.
Лог «переименование_<дата>.csv» кладётся в папку фото; откат — --undo этим логом.

Запуск (любое окружение с Python 3):
    python tools/prep/rename_photos.py data/photo_order.json ПАПКА_ФОТО --caches cache/sel54 cache/sel56 cache/sel56v2
        --selections data/selection_56.json data/selection_56_v2.json [--apply]
    python tools/prep/rename_photos.py --undo ПАПКА_ФОТО/переименование_2026-10-16.csv ПАПКА_ФОТО --caches … --selections … --apply
Без --apply — только показать, что будет сделано.
"""
import argparse
import csv
import datetime
import json
import re
from pathlib import Path


def plan_from_order(order_json):
    plan = json.loads(Path(order_json).read_text(encoding="utf-8"))["plan"]
    return [(p["track"], p["name"], p["new"], p["file"]) for p in plan]


def plan_from_log(log):
    rows = list(csv.reader(Path(log).open(encoding="utf-8-sig"), delimiter=";"))[1:]
    # откат: Стало → Было
    return [(r[0], Path(r[2]).stem, Path(r[1]).stem, r[2]) for r in rows]


def rename_json_keys(path, mapping, apply):
    p = Path(path)
    if not p.exists():
        return 0
    d = json.loads(p.read_text(encoding="utf-8"))
    n = sum(k in mapping for k in d)
    if apply and n:
        d = {mapping.get(k, k): v for k, v in d.items()}
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def fix_meta(folder, old, new, ext):
    for name, keys in (("photo.json", ("source", "order")), ("cands.json", ("source",))):
        f = folder / name
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            if "source" in keys and "source" in d:
                d["source"] = new + ext
            if "order" in keys and "order" in d:
                d["order"] = new
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("order", nargs="?")
    ap.add_argument("photos")
    ap.add_argument("--undo", default=None)
    ap.add_argument("--caches", nargs="*", default=[])
    ap.add_argument("--selections", nargs="*", default=[])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    photos = Path(a.photos)
    plan = plan_from_log(a.undo) if a.undo else plan_from_order(a.order)

    # проверки до любых изменений
    problems = []
    srcs = {}
    for track, old, new, _ in plan:
        src = next((p for p in photos.iterdir() if p.is_file() and p.stem == old), None)
        if src is None:
            problems.append(f"нет фото: {old}")
            continue
        srcs[old] = src
        dst = photos / (new + src.suffix)
        if dst.exists() and new != old and new not in {o for _, o, _, _ in plan}:
            problems.append(f"уже существует: {dst.name}")
    if len({n for _, _, n, _ in plan}) != len(plan):
        problems.append("повторяющиеся новые имена")
    if problems:
        print("ОСТАНОВЛЕНО:\n  " + "\n  ".join(problems))
        return

    mapping = {old: new for _, old, new, _ in plan}
    for track, old, new, _ in plan[:5]:
        print(f"  трек {track}: {old}  →  {new}")
    print(f"  … всего {len(plan)} фото")
    for c in a.caches:
        n = sum((Path(c) / o).is_dir() for o in mapping)
        print(f"  кеш {c}: папок к переименованию {n}")
    for s in a.selections:
        print(f"  {s}: ключей {rename_json_keys(s, mapping, False)}")
    if not a.apply:
        print("сухой прогон — ничего не изменено (добавьте --apply)")
        return

    # в два шага через временные имена — на случай пересечения старых и новых имён
    tmp = {}
    for old, src in srcs.items():
        t = src.with_name(f"__tmp_{len(tmp):03d}{src.suffix}")
        src.rename(t)
        tmp[old] = t
    for old, t in tmp.items():
        t.rename(photos / (mapping[old] + t.suffix))
    for c in a.caches:
        root = Path(c)
        moved = {}
        for old in mapping:
            if (root / old).is_dir():
                t = root / f"__tmp_{len(moved):03d}"
                (root / old).rename(t)
                moved[old] = t
        for old, t in moved.items():
            dst = root / mapping[old]
            t.rename(dst)
            fix_meta(dst, old, mapping[old], srcs[old].suffix)
    for s in a.selections:
        rename_json_keys(s, mapping, True)

    if not a.undo:
        log = photos / f"переименование_{datetime.date.today():%Y-%m-%d}.csv"
        with log.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
            w.writerow(["Трек", "Было", "Стало"])
            for track, old, new, _ in plan:
                w.writerow([track, old + srcs[old].suffix, new + srcs[old].suffix])
        print("лог:", log)
    print("готово")


if __name__ == "__main__":
    main()
