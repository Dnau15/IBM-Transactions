"""Render matplotlib backups for the 9 Stage II EDA queries.

Reads output/qN.csv files (produced by scripts/run_eda.sh) and writes
output/qN_mpl.jpg. Intended as a reproducible fallback for the manual
Superset export expected at output/qN.jpg.

Each query gets a tailored chart matching the spec in
project_reqs/eda.md. Missing CSV files are skipped with a warning.

Run:
    python scripts/eda_plot.py             # all queries
    python scripts/eda_plot.py q1 q4 q9    # subset
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

LAUNDER_COLOR = "#c33"
LEGIT_COLOR = "#5b8def"
NEUTRAL = "#666"


def _save(fig: plt.Figure, name: str) -> Path:
    out = OUT_DIR / f"{name}_mpl.jpg"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")
    return out


def plot_q1(df: pd.DataFrame) -> plt.Figure:
    df = df.copy()
    df["day"] = pd.to_datetime(df["day"])
    df = df.sort_values("day")
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["day"], df["rate"] * 100, marker="o", color=LAUNDER_COLOR)
    ax.set_xlabel("Date")
    ax.set_ylabel("Laundering rate (%)")
    ax.set_title("q1 — Daily laundering rate over the 28-day window")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    return fig


def plot_q2(df: pd.DataFrame) -> plt.Figure:
    pivot = (df.pivot_table(index="payment_format", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"}))
    pivot = pivot.assign(total=pivot.sum(axis=1)).sort_values("total", ascending=False).drop(columns="total")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    pivot.plot(kind="bar", stacked=True, ax=ax,
               color=[LEGIT_COLOR, LAUNDER_COLOR])
    ax.set_yscale("log")
    ax.set_xlabel("Payment format")
    ax.set_ylabel("Transactions (log scale)")
    ax.set_title("q2 — Payment format × is_laundering")
    ax.legend(title=None)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    return fig


def plot_q3(df: pd.DataFrame) -> plt.Figure:
    df = df.copy().sort_values("tx_count", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["rank"], df["tx_count"], s=8, alpha=0.6, color=NEUTRAL)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Bank rank (by tx volume)")
    ax.set_ylabel("Transactions per bank")
    ax.set_title(f"q3 — Bank size distribution (n={len(df)} banks)")
    ax.grid(True, which="both", alpha=0.3)
    return fig


def plot_q4(df: pd.DataFrame) -> plt.Figure:
    pivot = (df.pivot_table(index="scope", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .reindex(["intra", "inter"]))
    norm = pivot.div(pivot.sum(axis=0), axis=1) * 100
    fig, ax = plt.subplots(figsize=(7, 4.5))
    norm.T.plot(kind="bar", stacked=True, ax=ax,
                color=[NEUTRAL, "#f08b3a"])
    ax.set_ylabel("% of transactions")
    ax.set_title("q4 — Cross-bank vs intra-bank, by class")
    ax.legend(title=None)
    plt.setp(ax.get_xticklabels(), rotation=0)
    return fig


def plot_q5(df: pd.DataFrame) -> plt.Figure:
    df = df.copy()
    if len(df) > 50_000:
        df = df.sample(50_000, random_state=0)
    fig, ax = plt.subplots(figsize=(7, 7))
    legit = df[df["ever_laundering"] == 0]
    dirty = df[df["ever_laundering"] == 1]
    ax.scatter(legit["out_deg"].clip(lower=0.5),
               legit["in_deg"].clip(lower=0.5),
               s=4, alpha=0.2, color=LEGIT_COLOR, label="Legit")
    ax.scatter(dirty["out_deg"].clip(lower=0.5),
               dirty["in_deg"].clip(lower=0.5),
               s=8, alpha=0.4, color=LAUNDER_COLOR, label="Laundering")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Out-degree (transactions sent)")
    ax.set_ylabel("In-degree (transactions received)")
    ax.set_title("q5 — Account in/out-degree by laundering involvement")
    ax.legend()
    ax.grid(True, which="both", alpha=0.2)
    return fig


def plot_q6(df: pd.DataFrame) -> plt.Figure:
    df = df.copy().sort_values("n_transactions", ascending=False).head(20)
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(df))
    width = 0.4
    ax.bar(x - width / 2, df["n_patterns"], width, label="Pattern groups",
           color=NEUTRAL)
    ax.bar(x + width / 2, df["n_transactions"], width, label="Transactions",
           color=LAUNDER_COLOR)
    ax.set_xticks(x)
    ax.set_xticklabels(df["pattern_type"], rotation=45, ha="right")
    ax.set_yscale("log")
    ax.set_ylabel("Count (log scale)")
    ax.set_title("q6 — Pattern types (top 20 by transaction count)")
    ax.legend()
    return fig


def plot_q7(df: pd.DataFrame) -> plt.Figure:
    banks = sorted(set(df["from_bank"]).union(df["to_bank"]))
    idx = {b: i for i, b in enumerate(banks)}
    grid = np.zeros((len(banks), len(banks)))
    for _, r in df.iterrows():
        grid[idx[r["from_bank"]], idx[r["to_bank"]]] = r["n"]
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(np.log10(grid + 1), cmap="magma", aspect="auto")
    ax.set_xticks(range(len(banks)))
    ax.set_xticklabels(banks, rotation=90, fontsize=7)
    ax.set_yticks(range(len(banks)))
    ax.set_yticklabels(banks, fontsize=7)
    ax.set_xlabel("To bank")
    ax.set_ylabel("From bank")
    ax.set_title("q7 — Bank-pair flow (top 20×20, log10 transaction count)")
    fig.colorbar(im, ax=ax, label="log10(n + 1)")
    return fig


def plot_q8(df: pd.DataFrame) -> plt.Figure:
    df = df.copy().sort_values("k")
    df["tx_coverage"] = df["tx_in_consortium"] / df["tx_total"]
    df["laundering_coverage"] = df["laundering_in_consortium"] / df["laundering_total"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(df["k"], df["tx_coverage"] * 100, marker="o",
            color=NEUTRAL, label="Transaction coverage")
    ax.plot(df["k"], df["laundering_coverage"] * 100, marker="s",
            color=LAUNDER_COLOR, label="Laundering coverage")
    ax.set_xticks(df["k"])
    ax.set_xlabel("Consortium size K (top-K banks by volume)")
    ax.set_ylabel("Coverage (%)")
    ax.set_title("q8 — Consortium coverage curve")
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)
    ax.legend()
    return fig


def plot_q9(df: pd.DataFrame) -> plt.Figure:
    df = df.copy().sort_values("n_banks")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(df["n_banks"], df["n_patterns"], color=LAUNDER_COLOR)
    ax.set_xlabel("Distinct banks per laundering pattern")
    ax.set_ylabel("Number of pattern instances")
    ax.set_title("q9 — Banks per laundering pattern (multi-bank distribution)")
    ax.grid(True, alpha=0.3, axis="y")
    return fig


PLOTS = {
    "q1": plot_q1,
    "q2": plot_q2,
    "q3": plot_q3,
    "q4": plot_q4,
    "q5": plot_q5,
    "q6": plot_q6,
    "q7": plot_q7,
    "q8": plot_q8,
    "q9": plot_q9,
}


def main():
    targets = sys.argv[1:] or list(PLOTS.keys())
    for name in targets:
        if name not in PLOTS:
            print(f"  unknown chart: {name}")
            continue
        csv = OUT_DIR / f"{name}.csv"
        if not csv.exists():
            print(f"  missing {csv} — skipping {name}")
            continue
        print(f"plotting {name} ...")
        df = pd.read_csv(csv)
        fig = PLOTS[name](df)
        _save(fig, name)


if __name__ == "__main__":
    main()
