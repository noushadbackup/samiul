"""Figures for the ICEEICT paper. Every value is taken from the thesis or from the cited papers.

Palette: validated categorical slots 1-3 (blue, orange, aqua) from the dataviz reference
palette; marker shape is a second encoding so the figures survive grayscale print.
Run:  python3 make_figures.py   (writes PDFs into ../figures/)
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "figures")
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.family": "serif", "font.size": 7.5, "axes.titlesize": 8, "axes.labelsize": 7.5,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.8,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "pdf.fonttype": 42,
})


def leakage_gap():
    """Fig. 1: reported accuracy grouped by evaluation protocol."""
    # (label, accuracy %, task) - task: 'b' binary, 'm' multi-class. Values as reported in the cited papers.
    slice_level = [
        ("[Kurniasari]", 98.19, "m"), ("[Mahim]", 99.69, "b"), ("[Mahim]", 99.53, "m"), ("[Mahim]", 99.26, "m"),
        ("[AlSaeed]", 99.0, "b"), ("[AlSaeed]", 96.0, "b"), ("[Alshayeji]", 99.83, "m"),
        ("[El-Assy]", 99.43, "m"), ("[Mora]", 97.08, "m"), ("[Velu]", 95.34, "m"), ("[Pandey]", 72.0, "m"),
    ]
    subject_level = [("[Wen]", 86.5, "b"), ("[Saoud]", 90.0, "b"), ("[Saoud]", 60.0, "m")]
    ours = [("CNN--ViT", 82.2, "b"), ("DenseNet", 81.0, "b"), ("Swin", 57.7, "m")]
    yagis_slice, yagis_subj = (95.2, 96.9), (66.5, 70.1)

    fig, ax = plt.subplots(figsize=(3.45, 2.35))
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    jit = [-0.16, -0.08, 0.0, 0.08, 0.16]

    def draw(x0, pts, color, edge, size):
        for i, (_, acc, task) in enumerate(pts):
            ax.scatter(x0 + jit[i % len(jit)], acc, s=size, marker="o" if task == "b" else "^",
                       facecolor=color, edgecolor=edge, linewidth=0.8, zorder=3)

    draw(0, slice_level, BLUE, "white", 26)
    draw(1, subject_level, BLUE, "white", 26)
    for i, (name, acc, task) in enumerate(ours):
        ax.scatter(2 + [-0.08, 0.08, 0.0][i], acc, s=40, marker="o" if task == "b" else "^",
                   facecolor=ORANGE, edgecolor="white", linewidth=0.8, zorder=4)
    ax.text(2.2, 82.2, "CNN–ViT 82.2\nDenseNet 81.0", va="center", fontsize=6.3, color=INK)
    ax.text(2.2, 57.7, "Swin 57.7\n(3-class)", va="center", fontsize=6.3, color=INK)
    # Yagis et al.: identical data and model, only the split changes.
    ys, yt = sum(yagis_slice) / 2, sum(yagis_subj) / 2
    ax.errorbar([0.30], [ys], yerr=[[ys - yagis_slice[0]], [yagis_slice[1] - ys]], fmt="s", ms=4,
                color=INK2, mfc="white", lw=0.8, zorder=3)
    ax.errorbar([0.70], [yt], yerr=[[yt - yagis_subj[0]], [yagis_subj[1] - yt]], fmt="s", ms=4,
                color=INK2, mfc="white", lw=0.8, zorder=3)
    ax.annotate("", xy=(0.70, yt + 2.2), xytext=(0.30, ys - 1.4),
                arrowprops=dict(arrowstyle="->", color=INK2, lw=0.8, linestyle="--"))
    ax.text(0.52, 80.5, "same data,\nsubject split:\n$-$28 pts", ha="center", fontsize=6.0, color=INK2)
    ax.axhline(65.4, color=INK2, lw=0.7, ls=":", zorder=1)
    ax.text(-0.42, 66.2, "majority baseline, binary (ADNI, this work)", fontsize=5.8, color=INK2)
    ax.set_xticks([0, 1, 2])
    ax.set_xticklabels(["2D slice/image-\nlevel split", "Subject-level\nsplit", "This work\n(subject-level)"])
    ax.set_xlim(-0.45, 2.75)
    ax.set_ylim(50, 102)
    ax.set_ylabel("Reported accuracy (%)")
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker="o", ls="", mfc=INK2, mec="white", ms=5, label="binary"),
               Line2D([], [], marker="^", ls="", mfc=INK2, mec="white", ms=5, label="multi-class"),
               Line2D([], [], marker="s", ls="", mfc="white", mec=INK2, ms=4, label="Yagis et al. (range)")]
    ax.legend(handles=handles, loc="lower left", frameon=False, ncol=1, bbox_to_anchor=(0.0, 0.0))
    fig.tight_layout(pad=0.3)
    fig.savefig(os.path.join(OUT, "fig_leakage_gap.pdf"))
    plt.close(fig)


def folds_and_confusion():
    """Fig. 3: (a) per-fold macro-F1, (b-d) three-class confusion counts."""
    folds = [1, 2, 3, 4, 5]
    series = [("CNN–ViT", [0.716, 0.857, 0.743, 0.821, 0.873], BLUE, "o"),
              ("DenseNet", [0.768, 0.810, 0.678, 0.834, 0.850], ORANGE, "s"),
              ("Swin–ViT", [0.672, 0.723, 0.700, 0.750, 0.466], AQUA, "^")]
    cms = [("Swin (3-class)", [[126, 39, 41], [34, 30, 16], [24, 13, 72]]),
           ("DenseNet (3-class)", [[132, 34, 40], [34, 32, 14], [36, 11, 62]]),
           ("ViT (3-class)", [[0, 107, 99], [0, 57, 23], [0, 53, 56]])]
    seq = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#9cc2ee", BLUE, "#16427a"])

    fig = plt.figure(figsize=(7.16, 1.95))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.45, 1, 1, 1], wspace=0.42)
    ax = fig.add_subplot(gs[0])
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    for name, vals, color, mk in series:
        ax.plot(folds, vals, color=color, lw=1.4, marker=mk, ms=4.5, mec="white", mew=0.6, zorder=3)
    ax.text(5.15, 0.885, "CNN–ViT", color=INK, fontsize=6.3, va="center")
    ax.text(5.15, 0.835, "DenseNet", color=INK, fontsize=6.3, va="center")
    ax.text(5.15, 0.466, "Swin–ViT", color=INK, fontsize=6.3, va="center")
    ax.axhline(0.395, color=INK2, lw=0.7, ls=":")
    ax.text(1.0, 0.41, "majority baseline", fontsize=5.8, color=INK2)
    ax.set_xticks(folds)
    ax.set_xlim(0.7, 6.1)
    ax.set_ylim(0.35, 0.92)
    ax.set_xlabel("Cross-validation fold")
    ax.set_ylabel("Macro-F1 (binary)")
    ax.set_title("(a) Per-fold binary macro-F1", loc="left")

    labels = ["CN", "MCI", "AD"]
    for k, (title, cm) in enumerate(cms):
        axc = fig.add_subplot(gs[k + 1])
        rown = [[c / sum(row) for c in row] for row in cm]
        axc.imshow(rown, cmap=seq, vmin=0, vmax=0.75)
        for i in range(3):
            for j in range(3):
                axc.text(j, i, str(cm[i][j]), ha="center", va="center", fontsize=7,
                         color="white" if rown[i][j] > 0.45 else INK)
        axc.set_xticks(range(3))
        axc.set_xticklabels(labels)
        axc.set_yticks(range(3))
        axc.set_yticklabels(labels if k == 0 else [])
        axc.set_xlabel("Predicted")
        if k == 0:
            axc.set_ylabel("True")
        axc.set_title(f"({'bcd'[k]}) {title}", loc="left")
        for s in axc.spines.values():
            s.set_visible(False)
        axc.tick_params(length=0)
    fig.subplots_adjust(left=0.06, right=0.995, bottom=0.2, top=0.87)
    fig.savefig(os.path.join(OUT, "fig_folds_confusion.pdf"))
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    leakage_gap()
    folds_and_confusion()
    print("written to", os.path.abspath(OUT))
