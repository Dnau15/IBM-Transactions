"""Generate report figures from the evaluation CSVs.

Inputs:
    output/eval_threshold_sweep.csv -- (model, threshold, P, R, F1, alerts)
    output/eval_value_sweep.csv     -- per-currency dollar recovery

Outputs (PNGs into report/images/):
    pr_curve.png             precision-recall curves, both learned models
    value_recall_usd.png     value-recall vs alert volume on US-dollar segment
"""
import csv
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "report" / "images"
IMG.mkdir(exist_ok=True)

LR_NAME = "model1_LogisticRegression"
GBT_NAME = "model2_GBTClassifier"
RULE_NAME = "rule_baseline_R1_R2_R5"
LR_COLOR = "#1f77b4"
GBT_COLOR = "#d62728"
RULE_COLOR = "#2ca02c"
LR_LABEL = "Logistic Regression"
GBT_LABEL = "Gradient-Boosted Trees"
RULE_LABEL = "Rule baseline (single point)"


def _read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def plot_pr_curve():
    rows = _read(ROOT / "output" / "eval_threshold_sweep.csv")
    lr = sorted(
        ((float(r["recall"]), float(r["precision"]))
         for r in rows if r["model"] == LR_NAME),
        key=lambda rp: rp[0],
    )
    gbt = sorted(
        ((float(r["recall"]), float(r["precision"]))
         for r in rows if r["model"] == GBT_NAME),
        key=lambda rp: rp[0],
    )

    fig, ax = plt.subplots(figsize=(7, 4.3))
    ax.plot([r for r, _ in lr], [p for _, p in lr],
            "o-", label=LR_LABEL, color=LR_COLOR, linewidth=1.7)
    ax.plot([r for r, _ in gbt], [p for _, p in gbt],
            "o-", label=GBT_LABEL, color=GBT_COLOR, linewidth=1.7)
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision vs recall on the test slice")
    ax.set_xlim(0, 1)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right")
    fig.tight_layout()
    out = IMG / "pr_curve.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def plot_value_recall_usd():
    rows = _read(ROOT / "output" / "eval_value_sweep.csv")
    usd_rows = [r for r in rows if r["currency"] == "US Dollar"]
    lr = sorted(
        ((int(r["alerts"]), float(r["value_recall"]))
         for r in usd_rows if r["model"] == LR_NAME),
        key=lambda av: av[0],
    )
    gbt = sorted(
        ((int(r["alerts"]), float(r["value_recall"]))
         for r in usd_rows if r["model"] == GBT_NAME),
        key=lambda av: av[0],
    )
    # Rule baseline: single operating point (threshold sentinel = 1.0).
    rule = [(int(r["alerts"]), float(r["value_recall"]))
            for r in usd_rows if r["model"] == RULE_NAME]

    fig, ax = plt.subplots(figsize=(7, 4.3))
    ax.plot([a for a, _ in lr], [v for _, v in lr],
            "o-", label=LR_LABEL, color=LR_COLOR, linewidth=1.7)
    ax.plot([a for a, _ in gbt], [v for _, v in gbt],
            "o-", label=GBT_LABEL, color=GBT_COLOR, linewidth=1.7)
    if rule:
        ra, rv = rule[0]
        ax.scatter([ra], [rv], marker="X", s=120, color=RULE_COLOR,
                   label=RULE_LABEL, zorder=5, edgecolors="black",
                   linewidths=0.6)
    ax.set_xscale("log")
    ax.set_xlabel("Alert volume (log scale)")
    ax.set_ylabel("US-dollar laundering value recovered (fraction)")
    ax.set_title("Dollar-recovery vs alert volume on US-dollar laundering")
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3, which="both")
    ax.legend(loc="lower right")
    fig.tight_layout()
    out = IMG / "value_recall_usd.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    plot_pr_curve()
    plot_value_recall_usd()
