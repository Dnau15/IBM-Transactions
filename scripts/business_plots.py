"""Business-understanding plots that don't need a Hive query.

Only b8 (headline AML fines, from a static reference CSV) lives here.
b10 (eight canonical pattern schematics) is produced by
scripts/pattern_schematics.py. All other business plots (b1, b4, b5,
b6, b14, b15, b16) are Hive-driven and live in scripts/eda_plot.py.

Run:
    python scripts/business_plots.py
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output"
REFS_DIR = REPO / "scripts" / "refs"

LAUNDER_COLOR = "#c33"
NEUTRAL = "#666"


def _save(fig: plt.Figure, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}_mpl.jpg"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")
    return out


def plot_b8() -> None:
    """Headline AML fines bar chart, log $-axis."""
    df = pd.read_csv(REFS_DIR / "aml_fines.csv")
    df = df.sort_values("fine_usd_billion", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    y = np.arange(len(df))
    ax.barh(y, df["fine_usd_billion"], color=LAUNDER_COLOR)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{r.institution} ({r.year})" for r in df.itertuples()],
        fontsize=9,
    )
    ax.set_xscale("log")
    ax.set_xlabel("Fine (USD billions, log scale)")
    ax.set_title("b8 — Headline AML enforcement fines (selected)")
    ax.set_xlim(right=df["fine_usd_billion"].max() * 2.2)   # room for $-labels
    for i, r in df.iterrows():
        ax.text(r["fine_usd_billion"], i, f"  ${r['fine_usd_billion']:.2f}B",
                va="center", fontsize=9, color=NEUTRAL)
    ax.grid(True, axis="x", which="both", alpha=0.3)
    _save(fig, "b8")


PLOTS = {"b8": plot_b8}


def main():
    targets = sys.argv[1:] or list(PLOTS.keys())
    for name in targets:
        if name not in PLOTS:
            print(f"  unknown chart: {name}")
            continue
        print(f"plotting {name} ...")
        PLOTS[name]()


if __name__ == "__main__":
    main()
