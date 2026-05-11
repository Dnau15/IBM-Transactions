"""Render matplotlib backups for the 9 Stage II EDA queries.

Reads output/qN.csv files (produced by scripts/run_eda.sh) and writes
output/qN_mpl.jpg (or qN_a_mpl.jpg / qN_b_mpl.jpg for queries with
multi-panel output). Intended as a reproducible fallback for the manual
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


def plot_q1(df: pd.DataFrame, name: str) -> None:
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
    _save(fig, name)


def plot_q2(df: pd.DataFrame, name: str) -> None:
    """Stacked bar of laundering % per payment_format."""
    pivot = (df.pivot_table(index="payment_format", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"}))
    pct = pivot.div(pivot.sum(axis=1), axis=0) * 100
    pct = pct.assign(_total=pivot.sum(axis=1)).sort_values("_total", ascending=False).drop(columns="_total")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    pct.plot(kind="bar", stacked=True, ax=ax,
             color=[LEGIT_COLOR, LAUNDER_COLOR])
    ax.set_xlabel("Payment format (ordered by total volume)")
    ax.set_ylabel("Share of transactions (%)")
    ax.set_title("q2 — Laundering share by payment format")
    ax.set_ylim(0, 100)
    ax.legend(title=None)
    for c in pct.index:
        share = pct.loc[c, "Laundering"]
        ax.annotate(f"{share:.2f}%",
                    xy=(list(pct.index).index(c), 100),
                    xytext=(0, 2), textcoords="offset points",
                    ha="center", fontsize=8, color=LAUNDER_COLOR)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    _save(fig, name)


def plot_q3(df: pd.DataFrame, name: str) -> None:
    df = df.copy().sort_values("tx_count", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["rank"], df["tx_count"], s=8, alpha=0.6, color=NEUTRAL)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Bank rank (banks sorted by transaction count, descending)")
    ax.set_ylabel("Transaction count (incoming + outgoing)")
    ax.set_title(f"q3 — Bank size distribution (n={len(df)} banks)")
    ax.grid(True, which="both", alpha=0.3)
    _save(fig, name)


def plot_q4(df: pd.DataFrame, name: str) -> None:
    df = df.copy()
    df["scope"] = df["scope"].map({"intra": "intra-bank", "inter": "cross-bank"})
    pivot = (df.pivot_table(index="scope", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .reindex(["intra-bank", "cross-bank"]))
    norm = pivot.div(pivot.sum(axis=0), axis=1) * 100
    fig, ax = plt.subplots(figsize=(7, 4.5))
    norm.T.plot(kind="bar", stacked=True, ax=ax,
                color=[NEUTRAL, "#f08b3a"])
    ax.set_ylabel("% of transactions")
    ax.set_title("q4 — Cross-bank vs intra-bank, by class")
    ax.legend(title=None)
    plt.setp(ax.get_xticklabels(), rotation=0)
    _save(fig, name)


def plot_q5(df: pd.DataFrame, name: str) -> None:
    """Account in/out-degree, linear axes."""
    df = df.copy()
    if len(df) > 50_000:
        df = df.sample(50_000, random_state=0)
    fig, ax = plt.subplots(figsize=(7, 7))
    legit = df[df["ever_laundering"] == 0]
    dirty = df[df["ever_laundering"] == 1]
    ax.scatter(legit["out_deg"], legit["in_deg"],
               s=4, alpha=0.2, color=LEGIT_COLOR, label="Legit")
    ax.scatter(dirty["out_deg"], dirty["in_deg"],
               s=8, alpha=0.4, color=LAUNDER_COLOR, label="Laundering")
    ax.set_xlabel("Out-degree (transactions sent)")
    ax.set_ylabel("In-degree (transactions received)")
    ax.set_title("q5 — Account in/out-degree by laundering involvement")
    ax.legend()
    ax.grid(True, alpha=0.2)
    _save(fig, name)


CANONICAL_PATTERNS = [
    "FAN-IN", "FAN-OUT", "GATHER-SCATTER", "SCATTER-GATHER",
    "CYCLE", "RANDOM", "BIPARTITE", "STACK",
]


def _canonicalize_pattern(raw: str) -> str:
    """Map AMLworld's verbose pattern_type strings (e.g.
    'GATHER-SCATTER: MAX 16-DEGREE FAN-IN') to the paper's 8 canonical
    types. Prefix match against the longest canonical name first so
    'GATHER-SCATTER' isn't shadowed by a shorter prefix."""
    up = raw.upper()
    for c in sorted(CANONICAL_PATTERNS, key=len, reverse=True):
        if up.startswith(c):
            return c
    return "OTHER"


def plot_q6(df: pd.DataFrame, name: str) -> None:
    """Per *canonical* pattern type (8 from the paper, rolled up from the
    75 raw labels in HI-Medium): number of pattern instances vs total
    transactions; ratio = typical pattern size."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    rolled = (df.groupby("canonical", as_index=False)
                .agg(n_patterns=("n_patterns", "sum"),
                     n_transactions=("n_transactions", "sum"))
                .sort_values("n_transactions", ascending=False))
    rolled["avg_tx_per_pattern"] = (
        rolled["n_transactions"] / rolled["n_patterns"]).round(1)

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(rolled))
    width = 0.4
    ax.bar(x - width / 2, rolled["n_patterns"], width,
           label="Pattern instances (count of distinct pattern_group values)",
           color=NEUTRAL)
    ax.bar(x + width / 2, rolled["n_transactions"], width,
           label="Transactions in those instances",
           color=LAUNDER_COLOR)
    for i, r in enumerate(rolled.itertuples()):
        ax.text(i, max(r.n_patterns, r.n_transactions) * 1.1,
                f"avg {r.avg_tx_per_pattern} tx",
                ha="center", fontsize=8, color=NEUTRAL)
    ax.set_xticks(x)
    ax.set_xticklabels(rolled["canonical"], rotation=30, ha="right")
    ax.set_yscale("log")
    ax.set_ylabel("Count (log scale)")
    ax.set_title("q6 — Pattern types (rolled up to 8 canonical, "
                 "from laundering_patterns)")
    ax.legend(fontsize=9, loc="upper right")
    _save(fig, name)


def plot_q7(df: pd.DataFrame, name: str) -> None:
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
    _save(fig, name)


def plot_q8(df: pd.DataFrame, name: str) -> None:
    """Two panels: highest- and lowest-laundering-ratio banks. Filter to
    banks with >= 100 total transactions so the ratio is meaningful."""
    df = df.copy()
    df["total_tx"] = df["in_transactions"] + df["out_transactions"]
    df = df[df["total_tx"] >= 100].copy()
    df["label"] = df.apply(
        lambda r: f'{r["bank_id"]} — {r["name"]}' if pd.notna(r["name"]) else str(r["bank_id"]),
        axis=1,
    )

    def _bars(panel_df, title, suffix):
        panel_df = panel_df.copy().reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(10, 6))
        y = np.arange(len(panel_df))
        ax.barh(y, panel_df["laundering_ratio"] * 100, color=LAUNDER_COLOR)
        ax.set_yticks(y)
        ax.set_yticklabels(panel_df["label"], fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Laundering ratio (% of bank's total transactions)")
        ax.set_title(title)
        for i, r in panel_df.iterrows():
            ax.text(r["laundering_ratio"] * 100, i,
                    f"  {r['total_tx']:,} tx",
                    va="center", fontsize=7, color=NEUTRAL)
        ax.grid(True, axis="x", alpha=0.3)
        _save(fig, suffix)

    top_n = 20
    desc = df.nlargest(top_n, "laundering_ratio")
    # q8b: high-volume banks (sort by incoming tx desc, ties broken by
    # outgoing tx). Bars still show their laundering ratio so the chart
    # answers "do the busiest banks have low or high laundering rates?"
    busiest = (df.sort_values(["in_transactions", "out_transactions"],
                              ascending=[False, False])
                  .head(top_n))
    _bars(desc, f"q8a — Top {top_n} banks by laundering ratio (≥100 tx)",
          f"{name}_a")
    _bars(busiest,
          f"q8b — Top {top_n} banks by volume (in then out tx), "
          f"with their laundering ratios",
          f"{name}_b")


def plot_q9(df: pd.DataFrame, name: str) -> None:
    df = df.copy().sort_values("n_banks")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(df["n_banks"], df["n_patterns"], color=LAUNDER_COLOR)
    ax.set_xlabel("Distinct banks per laundering pattern")
    ax.set_ylabel("Number of pattern instances")
    ax.set_title("q9 — Banks per laundering pattern (multi-bank distribution)")
    ax.grid(True, alpha=0.3, axis="y")
    _save(fig, name)


def plot_q10(df: pd.DataFrame, name: str) -> None:
    """Top 20 banks by total transaction volume. Horizontal bars showing
    total_tx; each bar annotated with its laundering ratio for context."""
    df = df.copy()
    df["label"] = df.apply(
        lambda r: f'{r["bank_id"]} — {r["name"]}'
        if pd.notna(r["name"]) else str(r["bank_id"]),
        axis=1,
    )
    df = df.sort_values("total_tx", ascending=False).head(20).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    y = np.arange(len(df))
    ax.barh(y, df["total_tx"], color=NEUTRAL)
    ax.set_yticks(y)
    ax.set_yticklabels(df["label"], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Total transactions (incoming + outgoing)")
    ax.set_title("q10 — Top 20 banks by transaction volume")
    for i, r in df.iterrows():
        ax.text(r["total_tx"], i,
                f"  laundering = {r['laundering_ratio'] * 100:.2f}%",
                va="center", fontsize=7, color=LAUNDER_COLOR)
    ax.grid(True, axis="x", alpha=0.3)
    _save(fig, name)


def plot_q11(df: pd.DataFrame, name: str) -> None:
    """Amount distribution by class, normalized so each class's bars sum
    to 100%. Reveals where laundering over- or under-represents on the
    amount-size axis (round-number 'structuring' peaks are the classic
    AML signature near $9k / $99k)."""
    pivot = (df.pivot_table(index="log10_bin", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .sort_index())
    legit = pivot["Legitimate"] / pivot["Legitimate"].sum() * 100
    laund = pivot["Laundering"] / pivot["Laundering"].sum() * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.array(pivot.index)
    width = 0.4
    ax.bar(x - width / 2, legit, width, color=LEGIT_COLOR, label="Legitimate")
    ax.bar(x + width / 2, laund, width, color=LAUNDER_COLOR, label="Laundering")
    ax.set_xlabel("Amount paid — log10 decade  "
                  "(bin N covers $10$^N$..$10$^{N+1})$")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("q11 — Transaction amount distribution by class "
                 "(per-class density)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"$10^{{{int(b)}}}$" for b in x])
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    _save(fig, name)


def plot_q13(df: pd.DataFrame, name: str) -> None:
    """Currency mismatch (cross-currency transactions) share by class.
    Same plot shape as q4; expected to show 'mismatch' over-represented
    in laundering if FX-layering typology is in the dataset."""
    pivot = (df.pivot_table(index="currency_scope", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .reindex(["same", "mismatch"]))
    norm = pivot.div(pivot.sum(axis=0), axis=1) * 100

    fig, ax = plt.subplots(figsize=(7, 4.5))
    norm.T.plot(kind="bar", stacked=True, ax=ax,
                color=[NEUTRAL, "#f08b3a"])
    ax.set_ylabel("% of transactions")
    ax.set_title("q13 — Cross-currency transactions, by class")
    # Override legend labels to be readable.
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles, ["Same currency", "Cross-currency"], title=None)
    plt.setp(ax.get_xticklabels(), rotation=0)
    _save(fig, name)


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
    "q10": plot_q10,
    "q11": plot_q11,
    "q13": plot_q13,
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
        PLOTS[name](df, name)


if __name__ == "__main__":
    main()
