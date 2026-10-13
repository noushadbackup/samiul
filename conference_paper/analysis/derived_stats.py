"""Derived statistics for the ICEEICT paper, computed only from results already reported in the thesis.

Inputs are (a) per-fold subject-level macro-F1 (thesis Tables 5.3/5.4) and (b) pooled
subject-level confusion matrices (thesis Tables 5.5/5.6 and the confusion-matrix figures).
Counts marked APPROX were reconstructed from row-normalised matrices printed to two
decimals and may be off by one subject; replace them with counts from the saved
predictions before camera-ready.

Run:  python3 derived_stats.py   (writes stats.json next to this file)
"""
import json
import math
import os
import random

# Per-fold subject-level macro-F1 (same subject-level folds for every model).
FOLDS = {
    "binary": {
        "CNN-ViT": [0.716, 0.857, 0.743, 0.821, 0.873],
        "DenseNet": [0.768, 0.810, 0.678, 0.834, 0.850],
        "Swin-ViT": [0.672, 0.723, 0.700, 0.750, 0.466],
        "ResNet-18": [0.775, 0.449, 0.449, 0.779, 0.816],
    },
    "3class": {
        "Swin": [0.564, 0.471, 0.457, 0.675, 0.518],
        "DenseNet": [0.592, 0.433, 0.489, 0.622, 0.487],
        "ViT": [0.261, 0.238, 0.254, 0.273, 0.253],
    },
}

# Pooled subject-level confusion matrices, rows = true class, cols = predicted.
# Binary order: [CN, AD]; three-class order: [CN, MCI, AD].
CONFUSION = {
    "binary": {
        "CNN-ViT": [[177, 29], [27, 82]],      # exact (from per-class table)
        "DenseNet": [[171, 35], [25, 84]],     # exact
        "Swin-ViT": [[159, 47], [47, 62]],     # APPROX (row-normalised 0.77/0.23, 0.43/0.57)
        "ResNet-18": [[146, 60], [36, 73]],    # APPROX (0.71/0.29, 0.33/0.67)
    },
    "3class": {
        "Swin": [[126, 39, 41], [34, 30, 16], [24, 13, 72]],   # matches per-class table
        "DenseNet": [[132, 34, 40], [34, 32, 14], [36, 11, 62]],  # exact (figure counts)
        "ViT": [[0, 107, 99], [0, 57, 23], [0, 53, 56]],        # APPROX
    },
}


def metrics(cm):
    k = len(cm)
    n = sum(map(sum, cm))
    correct = sum(cm[i][i] for i in range(k))
    recalls, f1s = [], []
    for i in range(k):
        tp = cm[i][i]
        row = sum(cm[i])
        col = sum(cm[r][i] for r in range(k))
        rec = tp / row if row else 0.0
        prec = tp / col if col else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        recalls.append(rec)
        f1s.append(f1)
    out = {"acc": correct / n, "bacc": sum(recalls) / k, "macro_f1": sum(f1s) / k, "recall": recalls}
    if k == 2:  # AD is the positive class
        out["sens"] = recalls[1]
        out["spec"] = recalls[0]
    return out


def bootstrap_ci(cm, key, b=10000, seed=0):
    """Subject-level bootstrap: resample (true, pred) pairs with replacement."""
    rng = random.Random(seed)
    pairs = [(i, j) for i, row in enumerate(cm) for j, c in enumerate(row) for _ in range(c)]
    k = len(cm)
    vals = []
    for _ in range(b):
        boot = [[0] * k for _ in range(k)]
        for _ in range(len(pairs)):
            i, j = pairs[rng.randrange(len(pairs))]
            boot[i][j] += 1
        vals.append(metrics(boot)[key])
    vals.sort()
    return vals[int(0.025 * b)], vals[int(0.975 * b) - 1]


def t_two_sided_p(t, df):
    """Two-sided p-value of Student's t via numerical integration of the density."""
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    n, a = 20000, abs(t)
    h = a / n
    area = sum(c * (1 + ((i + 0.5) * h) ** 2 / df) ** (-(df + 1) / 2) for i in range(n)) * h
    return 2 * (0.5 - area)


def paired(a, b):
    d = [x - y for x, y in zip(a, b)]
    m = sum(d) / len(d)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1))
    t = m / (sd / math.sqrt(len(d)))
    return {"diffs": d, "mean_diff": m, "t": t, "p": t_two_sided_p(t, len(d) - 1),
            "wins": sum(x > 0 for x in d)}


def main():
    out = {"pooled": {}, "paired": {}}
    for task, models in CONFUSION.items():
        for name, cm in models.items():
            m = metrics(cm)
            m["bacc_ci"] = bootstrap_ci(cm, "bacc")
            m["macro_f1_ci"] = bootstrap_ci(cm, "macro_f1")
            out["pooled"][f"{task}/{name}"] = m
    out["paired"]["binary: CNN-ViT vs DenseNet (add ViT branch)"] = paired(FOLDS["binary"]["CNN-ViT"], FOLDS["binary"]["DenseNet"])
    out["paired"]["binary: CNN-ViT vs Swin-ViT (replace CNN branch)"] = paired(FOLDS["binary"]["CNN-ViT"], FOLDS["binary"]["Swin-ViT"])
    out["paired"]["binary: DenseNet vs ResNet-18 (pretrained)"] = paired(FOLDS["binary"]["DenseNet"], FOLDS["binary"]["ResNet-18"])
    out["paired"]["3class: Swin vs DenseNet"] = paired(FOLDS["3class"]["Swin"], FOLDS["3class"]["DenseNet"])
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    for k, v in out["pooled"].items():
        extra = f" sens={v['sens']:.3f} spec={v['spec']:.3f}" if "sens" in v else ""
        print(f"{k:22s} acc={v['acc']:.3f} bacc={v['bacc']:.3f} [{v['bacc_ci'][0]:.3f},{v['bacc_ci'][1]:.3f}] "
              f"mF1={v['macro_f1']:.3f} [{v['macro_f1_ci'][0]:.3f},{v['macro_f1_ci'][1]:.3f}]{extra}")
    for k, v in out["paired"].items():
        print(f"{k:50s} mean={v['mean_diff']:+.3f} t={v['t']:.2f} p={v['p']:.3f} wins={v['wins']}/5")


if __name__ == "__main__":
    main()
