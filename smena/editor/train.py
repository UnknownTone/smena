"""Обучение модели выбора элементов по разметке автора (06_LABELING_TOOL.yaml → training_later, первая версия).

Логистическая регрессия (numpy) на признаках кандидата — тех же, что видят правила auto_select.py.
Данные — data/labels/labels.jsonl: для каждого (набор, фото, кандидат/маска) берётся последнее решение.
Качество — перекрёстная проверка по фото (фото целиком в обучении или в проверке), сравнение с правилами
(поле auto — был ли кандидат в авто-выборе). Модель — data/labels/model.json; её читает auto_select.py --model.
"""
import datetime
import json
import math

import numpy as np

from smena.editor.data import LABELS_PATH, atomic_write

MODEL_PATH = LABELS_PATH.parent / "model.json"
FEATS = ["score", "area", "edges", "fill", "made", "detail", "orient", "axis", "log_ratio", "rect_fill",
         "straight", "contrast", "color", "alone", "base", "cx", "cy", "w_rel", "h_rel"]
MIN_LABELS = 30


def vec(f, names):
    return [float(f.get(n, 0.0) or 0.0) for n in names]


def proba(f, m):
    x = (np.array(vec(f, m["features"])) - np.array(m["mean"])) / np.array(m["std"])
    z = float(m["bias"] + x @ np.array(m["weights"]))
    return 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))


def load_model(path=MODEL_PATH):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except Exception:
        return None


def describe(m):
    cv, rules = m["cv"], m.get("rules", {})
    s = (f"модель от {m['date']}: {m['n']} меток ({m['n_pos']} «элемент»), {m['n_photos']} фото\n"
         f"проверка по фото: точность {cv['acc']:.0%}, F1 {cv['f1']:.2f}, порог {m['threshold']:.2f}")
    if rules:
        s += f"\nправила на тех же метках: точность {rules['acc']:.0%}, F1 {rules['f1']:.2f}"
    return s


def load_labels(path=LABELS_PATH):
    """Последнее решение по каждому кандидату/маске."""
    last = {}
    if not path.is_file():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("features") is None or r.get("label") is None:
            continue
        key = (r.get("set"), r.get("photo"), r.get("cand"), r.get("mask"))
        last[key] = r
    return list(last.values())


def fit(X, y, lam=0.01, iters=3000, lr=0.2):
    """Логистическая регрессия с L2 и балансом классов (градиентный спуск)."""
    n, d = X.shape
    w, b = np.zeros(d), 0.0
    pos = max(y.sum(), 1)
    wt = np.where(y == 1, n / (2 * pos), n / (2 * max(n - pos, 1)))
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = (p - y) * wt
        w -= lr * (X.T @ g / n + lam * w)
        b -= lr * g.mean()
    return w, b


def scores(y, yhat):
    tp = int(((yhat == 1) & (y == 1)).sum())
    fp = int(((yhat == 1) & (y == 0)).sum())
    fn = int(((yhat == 0) & (y == 1)).sum())
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    return {"acc": float((yhat == y).mean()), "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / max(prec + rec, 1e-9)}


def train(labels_path=LABELS_PATH, model_path=MODEL_PATH, folds=5):
    recs = load_labels(labels_path)
    if len(recs) < MIN_LABELS:
        raise ValueError(f"мало меток: {len(recs)} (нужно ≥ {MIN_LABELS}). Разметьте ещё фото: выбор + Space.")
    y = np.array([int(r["label"]) for r in recs])
    if y.min() == y.max():
        raise ValueError("все метки одного класса — нужны и «элемент», и «не элемент» (Space на проверенных фото)")
    X = np.array([vec(r["features"], FEATS) for r in recs])
    mean, std = X.mean(0), X.std(0) + 1e-6
    Xs = (X - mean) / std
    photos = sorted({(r.get("set"), r.get("photo")) for r in recs})
    fold_of = {p: i % folds for i, p in enumerate(photos)}
    fid = np.array([fold_of[(r.get("set"), r.get("photo"))] for r in recs])
    oof = np.zeros(len(y))
    k = min(folds, len(photos))
    for f in range(k):
        tr, te = fid != f, fid == f
        if te.sum() == 0 or len(set(y[tr])) < 2:
            continue
        w, b = fit(Xs[tr], y[tr])
        oof[te] = 1 / (1 + np.exp(-(Xs[te] @ w + b)))
    thr = max(np.arange(0.2, 0.81, 0.05), key=lambda t: scores(y, (oof >= t).astype(int))["f1"])
    cv = scores(y, (oof >= thr).astype(int))
    rules = scores(y, np.array([int(r.get("auto", 0)) for r in recs]))
    w, b = fit(Xs, y)
    model = {"version": 1, "date": datetime.date.today().isoformat(), "features": FEATS,
             "mean": mean.tolist(), "std": std.tolist(), "weights": w.tolist(), "bias": float(b),
             "threshold": float(round(thr, 2)), "n": int(len(y)), "n_pos": int(y.sum()), "n_photos": len(photos),
             "cv": cv, "rules": rules,
             "top_features": sorted(zip(FEATS, w.tolist()), key=lambda t: -abs(t[1]))[:6]}
    atomic_write(model_path, json.dumps(model, ensure_ascii=False, indent=1))
    return model
