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
    ax.set_title("q1 — Daily laundering rate (Sept 1–16 active window)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    _save(fig, name)


def plot_q2(df: pd.DataFrame, name: str) -> None:
    """Stacked bar of laundering % per payment_format, sorted by
    laundering share descending (highest-risk format first)."""
    pivot = (df.pivot_table(index="payment_format", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"}))
    pct = pivot.div(pivot.sum(axis=1), axis=0) * 100
    pct = pct.sort_values("Laundering", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 5))
    pct.plot(kind="bar", stacked=True, ax=ax,
             color=[LEGIT_COLOR, LAUNDER_COLOR])
    ax.set_xlabel("Payment format (ordered by laundering share)")
    ax.set_ylabel("Share of transactions (%)")
    ax.set_title("q2 — Laundering share by payment format")
    ax.set_ylim(0, 108)        # headroom so the annotations don't clip
    ax.legend(title=None, loc="center right")
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
    """Two panels of the top-20 banks by transaction count. q8a uses
    incoming tx, q8b uses outgoing tx; bars show the bank's laundering
    ratio so the reader sees whether high-traffic banks carry above- or
    below-average laundering risk."""
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
        ax.grid(True, axis="x", alpha=0.3)
        _save(fig, suffix)

    top_n = 20
    by_in = df.sort_values("in_transactions",  ascending=False).head(top_n)
    by_out = df.sort_values("out_transactions", ascending=False).head(top_n)
    _bars(by_in,
          f"q8a — Top {top_n} banks by incoming transaction count "
          f"(laundering ratio on bar)",
          f"{name}_a")
    _bars(by_out,
          f"q8b — Top {top_n} banks by outgoing transaction count "
          f"(laundering ratio on bar)",
          f"{name}_b")


def plot_q9(df: pd.DataFrame, name: str) -> None:
    """Bank-scope distribution of laundering patterns: for each
    distinct-banks bucket, how many pattern instances touch that many
    banks. Reads as 'a typical laundering scheme involves N banks'."""
    df = df.copy().sort_values("n_banks")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(df["n_banks"], df["n_patterns"], color=LAUNDER_COLOR)
    ax.set_xlabel("Number of distinct banks involved in the laundering scheme")
    ax.set_ylabel("Number of laundering schemes (pattern instances)")
    ax.set_title("q9 — How many banks does a laundering scheme touch?")
    # Annotate the mode and the long-tail tail-tip.
    mode_row = df.loc[df["n_patterns"].idxmax()]
    ax.annotate(f"Mode: {int(mode_row['n_banks'])} banks "
                f"({int(mode_row['n_patterns']):,} schemes)",
                xy=(mode_row["n_banks"], mode_row["n_patterns"]),
                xytext=(15, -5), textcoords="offset points",
                fontsize=9, color=NEUTRAL,
                arrowprops=dict(arrowstyle="->", color=NEUTRAL))
    tail_row = df.loc[df["n_banks"].idxmax()]
    ax.annotate(f"Tail: up to {int(tail_row['n_banks'])} banks",
                xy=(tail_row["n_banks"], tail_row["n_patterns"]),
                xytext=(-110, 30), textcoords="offset points",
                fontsize=9, color=NEUTRAL,
                arrowprops=dict(arrowstyle="->", color=NEUTRAL))
    intra = df.loc[df["n_banks"] == 1, "n_patterns"].sum() if (df["n_banks"] == 1).any() else 0
    total = df["n_patterns"].sum()
    if intra and total:
        ax.text(0.99, 0.95,
                f"Only {intra}/{total} ({100*intra/total:.2f}%) "
                "schemes are intra-bank",
                transform=ax.transAxes, fontsize=9, color=NEUTRAL,
                ha="right", va="top")
    ax.grid(True, alpha=0.3, axis="y")
    _save(fig, name)


def plot_q10(df: pd.DataFrame, name: str) -> None:
    """Top 20 banks by total transaction volume — bars only, no
    per-bar laundering annotation (that question is answered by q8)."""
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
    ax.grid(True, axis="x", alpha=0.3)
    _save(fig, name)


_Q11_BIN_LABELS = {
    -1: "<$1",
    0:  "$1–10",
    1:  "$10–100",
    2:  "$100–1K",
    3:  "$1K–10K",
    4:  "$10K–100K",
    5:  "$100K–1M",
    6:  "$1M–10M",
    7:  "$10M–100M",
    8:  "$100M–1B",
    9:  "$1B+",
}


def plot_q11(df: pd.DataFrame, name: str) -> None:
    """Per-currency amount distribution by class. We render one panel per
    top-N currency by total volume; each panel's bars sum to 100% within
    a (currency, class) so the shape comparison is fair. Mixing currencies
    on a single x-axis (the previous version) is incorrect because the
    bin labels were USD but the values were not."""
    df = df.copy()
    df["n"] = df["n"].astype(int)

    # Pick top currencies by total transaction count.
    cur_totals = df.groupby("payment_currency")["n"].sum().sort_values(ascending=False)
    n_panels = min(6, len(cur_totals))
    top_currencies = list(cur_totals.head(n_panels).index)

    ncols = 3
    nrows = (n_panels + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows),
                              sharey=True)
    axes = np.atleast_2d(axes).ravel()

    for ax, cur in zip(axes, top_currencies):
        sub = df[df["payment_currency"] == cur]
        pivot = (sub.pivot_table(index="log10_bin", columns="is_laundering",
                                  values="n", aggfunc="sum", fill_value=0)
                    .rename(columns={0: "Legitimate", 1: "Laundering"})
                    .sort_index())
        legit_total = pivot.get("Legitimate", pd.Series(dtype=float)).sum() or 1
        laund_total = pivot.get("Laundering", pd.Series(dtype=float)).sum() or 1
        legit = pivot.get("Legitimate", 0) / legit_total * 100
        laund = pivot.get("Laundering", 0) / laund_total * 100

        x = np.arange(len(pivot.index))
        width = 0.4
        ax.bar(x - width / 2, legit, width, color=LEGIT_COLOR, label="Legitimate")
        ax.bar(x + width / 2, laund, width, color=LAUNDER_COLOR, label="Laundering")
        ax.set_xticks(x)
        ax.set_xticklabels([_Q11_BIN_LABELS.get(int(b), str(int(b)))
                            for b in pivot.index],
                           rotation=30, ha="right", fontsize=8)
        ax.set_title(
            f"{cur}  (legit n={int(legit_total):,}, "
            f"laund n={int(laund_total):,})",
            fontsize=10,
        )
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_xlabel("Transaction amount bucket")

    # Hide any unused axes.
    for ax in axes[n_panels:]:
        ax.axis("off")

    # Common y-label on the left column only.
    for r in range(nrows):
        axes[r * ncols].set_ylabel("Share of class (%)")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center",
               ncol=2, fontsize=10, frameon=False,
               bbox_to_anchor=(0.5, 1.01))
    fig.suptitle("q11 — Transaction amount distribution by class, "
                 "per currency", y=1.03)
    _save(fig, name)


def plot_q12(df: pd.DataFrame, name: str) -> None:
    """Hour-of-day × day-of-week heatmap of laundering rate. Hive
    DAYOFWEEK returns 1=Sun..7=Sat — we reorder to Mon..Sun."""
    pivot = df.pivot_table(index="day_of_week", columns="hour_of_day",
                           values="rate", fill_value=0)
    pivot = pivot.reindex([2, 3, 4, 5, 6, 7, 1])  # Mon..Sun

    fig, ax = plt.subplots(figsize=(12, 4.5))
    im = ax.imshow(pivot.values * 100, cmap="magma", aspect="auto")
    ax.set_yticks(range(7))
    ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(24))
    ax.set_xticklabels(range(24))
    ax.set_xlabel("Hour of day (cluster local TZ, MSK)")
    ax.set_ylabel("Day of week")
    ax.set_title("q12 — Laundering rate by hour × weekday "
                 "(Sept 1-16, active stream only)")
    fig.colorbar(im, ax=ax, label="Laundering rate (%)")
    _save(fig, name)


def plot_q13(df: pd.DataFrame, name: str) -> None:
    """Cross-currency share by class. Stacked bar with one bar per
    class; segments are same-currency vs cross-currency."""
    pivot = (df.pivot_table(index="currency_scope", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .reindex(["same", "mismatch"]))
    norm = pivot.div(pivot.sum(axis=0), axis=1) * 100

    fig, ax = plt.subplots(figsize=(7, 4.5))
    norm.T.plot(kind="bar", stacked=True, ax=ax,
                color=[NEUTRAL, "#f08b3a"])
    ax.set_xlabel("Transaction class")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("q13 — Cross-currency share, by class")
    handles, _ = ax.get_legend_handles_labels()
    ax.legend(handles, ["Same currency", "Cross-currency"], title=None)
    plt.setp(ax.get_xticklabels(), rotation=0)
    _save(fig, name)


def plot_q14(df: pd.DataFrame, name: str) -> None:
    """Pattern duration distribution by canonical type. Box-and-whisker
    per type, y-axis on log scale (durations span seconds to days)."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    # Use hours; clip 0 -> 0.01 so log scale doesn't blow up on
    # single-transaction patterns (duration == 0).
    df["duration_hours_clipped"] = df["duration_hours"].clip(lower=0.01)

    order = [c for c in CANONICAL_PATTERNS
             if (df["canonical"] == c).any()]
    data_by_type = [df.loc[df["canonical"] == c,
                            "duration_hours_clipped"].values
                    for c in order]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.boxplot(data_by_type, labels=order, showfliers=True,
               patch_artist=True,
               boxprops=dict(facecolor=LAUNDER_COLOR, alpha=0.5),
               medianprops=dict(color="black"))
    ax.set_yscale("log")
    ax.set_ylabel("Pattern duration (hours, log scale)")
    ax.set_xlabel("Canonical pattern type")
    ax.set_title("q14 — Pattern duration distribution per canonical type "
                 "(N={:,} pattern instances)".format(len(df)))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    ax.grid(True, axis="y", alpha=0.3, which="both")
    _save(fig, name)


def plot_q15(df: pd.DataFrame, name: str) -> None:
    """Account-degree CCDF. Shows fraction of accounts whose degree is
    at least k, for k = 1, 2, ..., separately for in-degree and out-degree
    and for legit / ever-laundering accounts."""
    df = df.copy()
    df["deg"] = df["deg"].astype(int)
    df["n_accounts"] = df["n_accounts"].astype(int)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, direction, label in zip(axes, ["in", "out"],
                                    ["In-degree (txns received)",
                                     "Out-degree (txns sent)"]):
        d = df[df["direction"] == direction]
        for ever, color, lbl in [(0, LEGIT_COLOR, "Legit"),
                                  (1, LAUNDER_COLOR, "Ever laundering")]:
            sub = (d[d["ever_laundering"] == ever]
                   .sort_values("deg"))
            if sub.empty:
                continue
            total = sub["n_accounts"].sum()
            # CCDF = P(D >= k) = 1 - cumulative-from-below + n_at_k / total
            cum_lt = sub["n_accounts"].cumsum().shift(fill_value=0)
            ccdf = 1.0 - cum_lt / total
            ax.loglog(sub["deg"].clip(lower=1), ccdf,
                      drawstyle="steps-post",
                      color=color, label=f"{lbl} (n={total:,})")
        ax.set_xlabel(label)
        ax.set_title(f"q15 — {direction}-degree CCDF")
        ax.grid(True, which="both", alpha=0.25)
        ax.legend(fontsize=9)
    axes[0].set_ylabel("P(degree >= k)")
    _save(fig, name)


_Q16_BUCKET_ORDER = [
    "1", "2", "3-9", "10-99", "100-999",
    "1K-9.9K", "10K-99.9K", "100K-999K", "1M+",
]


def plot_q16(df: pd.DataFrame, name: str) -> None:
    """Connected-component size distribution. Reorder buckets so the
    log axis is monotone, annotate the giant component size on top of
    the rightmost bar."""
    df = df.copy()
    df = (df.set_index("size_bucket")
            .reindex(_Q16_BUCKET_ORDER)
            .dropna(subset=["n_components"])
            .reset_index())
    df["n_components"] = df["n_components"].astype(int)
    df["n_vertices_in_bucket"] = df["n_vertices_in_bucket"].astype(int)
    df["max_size_in_bucket"] = df["max_size_in_bucket"].astype(int)

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(df))
    ax.bar(x, df["n_components"], color=NEUTRAL)
    ax.set_xticks(x)
    ax.set_xticklabels(df["size_bucket"])
    ax.set_yscale("log")
    ax.set_xlabel("Component size bucket (accounts)")
    ax.set_ylabel("Number of components (log)")
    ax.set_title("q16 — Weakly-connected-component size distribution")
    # Annotate each bar with the within-bucket vertex count and biggest size.
    for i, r in df.iterrows():
        ax.annotate(
            f"max {int(r['max_size_in_bucket']):,}",
            xy=(i, r["n_components"]),
            xytext=(0, 4), textcoords="offset points",
            ha="center", fontsize=7, color=LAUNDER_COLOR,
        )
    ax.grid(True, axis="y", which="both", alpha=0.3)
    _save(fig, name)


_Q17_DECADE_LABELS = {
    -1: "<1s",
    0:  "1s-1min",
    1:  "1min-1h",
    2:  "1h-1d",
    3:  "1d-1w",
    4:  "1w+",
}


def plot_q17(df: pd.DataFrame, name: str) -> None:
    """Pass-through-time histogram. For each (in -> next-out) gap on an
    account, bucket into log decades; render per-class density so the
    plot reveals shifts even when laundering counts are tiny."""
    pivot = (df.pivot_table(index="decade", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .sort_index())
    legit_total = pivot.get("Legitimate", pd.Series(dtype=float)).sum() or 1
    laund_total = pivot.get("Laundering", pd.Series(dtype=float)).sum() or 1
    legit = pivot.get("Legitimate", 0) / legit_total * 100
    laund = pivot.get("Laundering", 0) / laund_total * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(pivot.index))
    width = 0.4
    ax.bar(x - width / 2, legit, width, color=LEGIT_COLOR,
           label=f"Legitimate (n={int(legit_total):,})")
    ax.bar(x + width / 2, laund, width, color=LAUNDER_COLOR,
           label=f"Laundering (n={int(laund_total):,})")
    ax.set_xticks(x)
    ax.set_xticklabels([_Q17_DECADE_LABELS.get(int(b), str(int(b)))
                        for b in pivot.index])
    ax.set_xlabel("In -> next-out gap")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("q17 — Account pass-through time, by class")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, name)


def plot_q18(df: pd.DataFrame, name: str) -> None:
    """Pattern x bank-scope heatmap. Roll the 75 raw pattern_type strings
    up to the paper's 8 canonical types (FAN-IN, FAN-OUT, ...), bucket
    n_banks into broad ranges (1, 2, 3-5, 6-10, 11-20, 21+), and render
    as a log-coloured 2D grid."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    df["n_banks"] = df["n_banks"].astype(int)
    df["n_patterns"] = df["n_patterns"].astype(int)

    def _bucket(n):
        if n <= 1:  return "1"
        if n == 2:  return "2"
        if n <= 5:  return "3-5"
        if n <= 10: return "6-10"
        if n <= 20: return "11-20"
        return "21+"
    bucket_order = ["1", "2", "3-5", "6-10", "11-20", "21+"]
    df["bucket"] = df["n_banks"].map(_bucket)

    grid = (df.groupby(["canonical", "bucket"], as_index=False)["n_patterns"]
              .sum()
              .pivot(index="canonical", columns="bucket", values="n_patterns")
              .reindex(index=CANONICAL_PATTERNS, columns=bucket_order)
              .fillna(0))

    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(np.log10(grid.values + 1), cmap="magma", aspect="auto")
    ax.set_xticks(range(len(bucket_order)))
    ax.set_xticklabels(bucket_order)
    ax.set_yticks(range(len(CANONICAL_PATTERNS)))
    ax.set_yticklabels(CANONICAL_PATTERNS)
    ax.set_xlabel("Distinct banks involved in pattern")
    ax.set_ylabel("Canonical pattern type")
    ax.set_title("q18 — Pattern x bank-scope (log10 pattern instances)")
    # Cell annotations with raw counts.
    for i, ptype in enumerate(CANONICAL_PATTERNS):
        for j, b in enumerate(bucket_order):
            v = int(grid.loc[ptype, b]) if ptype in grid.index else 0
            if v:
                ax.text(j, i, f"{v}", ha="center", va="center",
                        fontsize=7,
                        color="white" if np.log10(v + 1) > 1.5 else "black")
    fig.colorbar(im, ax=ax, label="log10(n + 1)")
    _save(fig, name)


def plot_q19(df: pd.DataFrame, name: str) -> None:
    """Currency-pair flow heatmaps. Two panels: legitimate vs laundering,
    each a square heatmap of (payment_currency, receiving_currency)
    transaction count on a log scale. Diagonal = same-currency."""
    df = df.copy()
    df["n"] = df["n"].astype(int)
    # Top 10 currencies by total volume across both panels.
    totals = (pd.concat([df.groupby("payment_currency")["n"].sum(),
                          df.groupby("receiving_currency")["n"].sum()])
                .groupby(level=0).sum()
                .sort_values(ascending=False)
                .head(10))
    cur_order = list(totals.index)

    def _grid(d):
        g = (d.pivot_table(index="payment_currency",
                            columns="receiving_currency",
                            values="n", aggfunc="sum", fill_value=0)
                .reindex(index=cur_order, columns=cur_order, fill_value=0))
        return g

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, klass, title, cmap in zip(
            axes,
            [0, 1],
            ["Legitimate", "Laundering"],
            ["Blues", "Reds"]):
        sub = df[df["is_laundering"] == klass]
        g = _grid(sub)
        im = ax.imshow(np.log10(g.values + 1), cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(cur_order)))
        ax.set_xticklabels(cur_order, rotation=60, ha="right", fontsize=8)
        ax.set_yticks(range(len(cur_order)))
        ax.set_yticklabels(cur_order, fontsize=8)
        ax.set_xlabel("Receiving currency")
        if ax is axes[0]:
            ax.set_ylabel("Payment currency")
        ax.set_title(f"{title} (n={int(sub['n'].sum()):,})")
        fig.colorbar(im, ax=ax, label="log10(n + 1)", shrink=0.8)
    fig.suptitle("q19 — Currency-pair flow, by class (top 10 currencies)",
                 y=1.02)
    _save(fig, name)


def plot_q20(df: pd.DataFrame, name: str) -> None:
    """Top bank-pair corridors. Two horizontal-bar panels:
       a) top 25 pairs by total transactions, laundering segment overlaid
       b) top 25 pairs by laundering rate (filtered to >= 1000 total txns
          via the SQL HAVING clause), bar colour = laundering segment."""
    df = df.copy()
    df["n_total"]      = df["n_total"].astype(int)
    df["n_laundering"] = df["n_laundering"].astype(int)
    df["laundering_rate"] = df["laundering_rate"].astype(float)
    df["label"] = df["from_bank"].astype(str) + " -> " + df["to_bank"].astype(str)

    def _panel(panel_df, title, suffix, by_rate=False):
        panel_df = panel_df.reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(10, 7))
        y = np.arange(len(panel_df))
        if by_rate:
            ax.barh(y, panel_df["laundering_rate"] * 100, color=LAUNDER_COLOR)
            ax.set_xlabel("Laundering rate (% of pair's transactions)")
            for i, r in panel_df.iterrows():
                ax.text(r["laundering_rate"] * 100, i,
                        f"  {int(r['n_total']):,} tx",
                        va="center", fontsize=7, color=NEUTRAL)
        else:
            ax.barh(y, panel_df["n_total"], color=LEGIT_COLOR, label="Legit (segment)")
            ax.barh(y, panel_df["n_laundering"], color=LAUNDER_COLOR,
                    label="Laundering (segment)")
            ax.set_xlabel("Transactions on this corridor")
            ax.set_xscale("log")
            ax.legend(fontsize=8, loc="lower right")
            for i, r in panel_df.iterrows():
                ax.text(r["n_total"], i,
                        f"  {r['laundering_rate'] * 100:.2f}%",
                        va="center", fontsize=7, color=LAUNDER_COLOR)
        ax.set_yticks(y)
        ax.set_yticklabels(panel_df["label"], fontsize=8)
        ax.invert_yaxis()
        ax.set_title(title)
        ax.grid(True, axis="x", alpha=0.3)
        _save(fig, suffix)

    top_volume = df.sort_values("n_total", ascending=False).head(25)
    top_rate   = (df[df["n_total"] >= 1000]
                    .sort_values("laundering_rate", ascending=False)
                    .head(25))
    _panel(top_volume, "q20a - Top 25 bank-pair corridors by volume",
           f"{name}_a", by_rate=False)
    _panel(top_rate,
           "q20b - Top 25 bank-pair corridors by laundering rate (>=1000 tx)",
           f"{name}_b", by_rate=True)


# -----------------------------------------------------------------------------
# Business-understanding plots driven by Hive (b1, b4, b5, b6). Each follows
# the same CSV -> matplotlib convention as q*. Plots b3, b8, b9, b10, b11,
# b13 are produced by scripts/business_plots.py (no Hive dependency).
# -----------------------------------------------------------------------------

def plot_b1(df: pd.DataFrame, name: str) -> None:
    """Sub-threshold structuring. $50 bins on $7K-$12K, per-class density,
    vertical line at the $10K CTR reporting threshold."""
    pivot = (df.pivot_table(index="bin_lo", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .sort_index())
    legit_total = pivot.get("Legitimate", pd.Series(dtype=float)).sum() or 1
    laund_total = pivot.get("Laundering", pd.Series(dtype=float)).sum() or 1
    legit = pivot.get("Legitimate", 0) / legit_total * 100
    laund = pivot.get("Laundering", 0) / laund_total * 100

    fig, ax = plt.subplots(figsize=(12, 5))
    x = pivot.index.values
    ax.bar(x - 12, legit, width=24, color=LEGIT_COLOR,
           label=f"Legitimate (n={int(legit_total):,})")
    ax.bar(x + 12, laund, width=24, color=LAUNDER_COLOR,
           label=f"Laundering (n={int(laund_total):,})")
    ax.axvline(10000, color="black", linestyle="--", linewidth=1)
    ax.annotate("$10,000 CTR threshold", xy=(10000, ax.get_ylim()[1]),
                xytext=(6, -10), textcoords="offset points",
                fontsize=9, color="black")
    ax.set_xlabel("Transaction amount ($)")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("b1 — Sub-threshold structuring, $50 bins on $7K–$12K range")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, name)


def plot_b4(df: pd.DataFrame, name: str) -> None:
    """Per-canonical-pattern visibility under each setup. For each
    pattern instance we computed isolated_visible_edges (best single
    bank), loose_consortium_edges (>=1 endpoint in top-20), and
    strict_consortium_edges (both endpoints in top-20). Roll up to
    canonical type by *mean* fraction of edges visible."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    for c in ["n_edges_total", "isolated_visible_edges",
              "loose_consortium_edges", "strict_consortium_edges"]:
        df[c] = df[c].astype(float)
    df["isolated_frac"] = df["isolated_visible_edges"] / df["n_edges_total"]
    df["loose_frac"]    = df["loose_consortium_edges"] / df["n_edges_total"]
    df["strict_frac"]   = df["strict_consortium_edges"] / df["n_edges_total"]
    # Shared-features = 1.0 by construction (all edges visible after pooling).
    df["shared_features_frac"] = 1.0

    rolled = (df.groupby("canonical", as_index=False)
                .agg(n_patterns=("n_edges_total", "size"),
                     isolated=("isolated_frac", "mean"),
                     shared=("shared_features_frac", "mean"),
                     consort_loose=("loose_frac", "mean"),
                     consort_strict=("strict_frac", "mean"))
                .set_index("canonical")
                .reindex(CANONICAL_PATTERNS)
                .dropna(subset=["n_patterns"])
                .reset_index())

    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = np.arange(len(rolled))
    w = 0.2
    ax.bar(x - 1.5*w, rolled["isolated"]      * 100, w, color=NEUTRAL,
           label="Isolated (best single bank)")
    ax.bar(x - 0.5*w, rolled["shared"]        * 100, w, color=LEGIT_COLOR,
           label="Shared-features (all edges)")
    ax.bar(x + 0.5*w, rolled["consort_loose"] * 100, w, color="#f08b3a",
           label="Consortium top-20 (>=1 endpoint)")
    ax.bar(x + 1.5*w, rolled["consort_strict"]* 100, w, color=LAUNDER_COLOR,
           label="Consortium top-20 (both endpoints)")
    ax.set_xticks(x)
    ax.set_xticklabels(rolled["canonical"], rotation=30, ha="right")
    ax.set_ylabel("Mean fraction of pattern edges visible (%)")
    ax.set_ylim(0, 110)
    ax.set_title("b4 — Pattern edge visibility per data-sharing setup "
                 "(mean over instances)")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, axis="y", alpha=0.3)
    for i, r in rolled.iterrows():
        ax.text(i, 105, f"n={int(r['n_patterns'])}",
                ha="center", fontsize=7, color=NEUTRAL)
    _save(fig, name)


def plot_b5(df: pd.DataFrame, name: str) -> None:
    """Consortium-membership coverage curve. For each K, fraction of
    transactions covered when the top-K banks are members, under loose
    and strict definitions, split by class."""
    df = df.copy()
    df["k"]       = df["k"].astype(int)
    df["n_at_k"]  = df["n_at_k"].astype(int)
    df["is_laundering"] = df["is_laundering"].astype(int)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    style = {
        ("loose", 0):  dict(color=LEGIT_COLOR,   linestyle="-",  label="Legitimate — loose"),
        ("loose", 1):  dict(color=LAUNDER_COLOR, linestyle="-",  label="Laundering — loose"),
        ("strict", 0): dict(color=LEGIT_COLOR,   linestyle="--", label="Legitimate — strict"),
        ("strict", 1): dict(color=LAUNDER_COLOR, linestyle="--", label="Laundering — strict"),
    }
    for (cov, lab), grp in df.groupby(["coverage_type", "is_laundering"]):
        grp = grp.sort_values("k")
        total = grp["n_at_k"].sum()
        if total == 0:
            continue
        coverage = grp["n_at_k"].cumsum() / total
        ax.plot(grp["k"], coverage * 100, **style[(cov, lab)])
    ax.set_xscale("log")
    ax.set_xlabel("Consortium membership size K (top banks by volume)")
    ax.set_ylabel("Coverage of class transactions (%)")
    ax.set_title("b5 — Consortium membership coverage curve")
    # Annotate K = 5, 10, 20, 50 with vertical dashed lines.
    for k in (5, 10, 20, 50):
        ax.axvline(k, color="#bbb", linestyle=":", linewidth=0.8)
        ax.annotate(f"K={k}", xy=(k, 5), xytext=(2, 0),
                    textcoords="offset points",
                    fontsize=7, color="#666")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, which="both", alpha=0.25)
    ax.set_ylim(0, 105)
    _save(fig, name)


def plot_b6(df: pd.DataFrame, name: str) -> None:
    """Cross-bank share by canonical pattern type. For each canonical
    type: stacked horizontal bar showing total intra-bank vs inter-bank
    EDGE counts, with the fraction of pattern *instances* that have at
    least one inter-bank edge annotated to the right."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    rolled = (df.groupby("canonical", as_index=False)
                .agg(n_patterns=("n_patterns", "sum"),
                     n_with_inter_edge=("n_with_inter_edge", "sum"),
                     total_intra=("total_intra_edges", "sum"),
                     total_inter=("total_inter_edges", "sum"))
                .set_index("canonical")
                .reindex(CANONICAL_PATTERNS)
                .dropna(subset=["n_patterns"])
                .reset_index())
    rolled["frac_inter_instances"] = (
        rolled["n_with_inter_edge"] / rolled["n_patterns"]
    )
    rolled["total_edges"] = rolled["total_intra"] + rolled["total_inter"]
    rolled = rolled.sort_values("total_edges", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    y = np.arange(len(rolled))
    ax.barh(y, rolled["total_intra"], color=NEUTRAL,    label="Intra-bank edges")
    ax.barh(y, rolled["total_inter"], left=rolled["total_intra"],
            color=LAUNDER_COLOR, label="Inter-bank edges")
    ax.set_yticks(y)
    ax.set_yticklabels(rolled["canonical"])
    ax.set_xlabel("Edges across all pattern instances (log scale)")
    ax.set_xscale("log")
    ax.set_title("b6 — Cross-bank share by canonical pattern type")
    ax.legend(fontsize=9, loc="lower right")
    for i, r in rolled.iterrows():
        ax.text(r["total_edges"], i,
                f"  {r['frac_inter_instances']*100:.0f}% inter, n={int(r['n_patterns'])}",
                va="center", fontsize=7, color=LAUNDER_COLOR)
    ax.grid(True, axis="x", which="both", alpha=0.3)
    _save(fig, name)


def plot_q7b(df: pd.DataFrame, name: str) -> None:
    """Bank-pair flow heatmap across the top 500 banks. Same shape as
    q7 but with rank-based axes (no tick labels), so the long tail of
    bank-pair traffic is visible alongside the dense corridors among
    the very largest banks."""
    df = df.copy()
    df["from_rank"]    = df["from_rank"].astype(int)
    df["to_rank"]      = df["to_rank"].astype(int)
    df["n"]            = df["n"].astype(int)
    df["laundering_n"] = df["laundering_n"].astype(int)

    N = int(max(df["from_rank"].max(), df["to_rank"].max()))
    grid = np.zeros((N, N))
    for _, r in df.iterrows():
        grid[int(r["from_rank"]) - 1, int(r["to_rank"]) - 1] = r["n"]

    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = ax.imshow(np.log10(grid + 1), cmap="magma", aspect="auto")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("Destination bank (ranked by total volume, 1 → 500)")
    ax.set_ylabel("Source bank (ranked by total volume, 1 → 500)")
    ax.set_title(f"q7b — Bank-pair flow across the top {N} banks "
                 "(log10 transaction count)")
    fig.colorbar(im, ax=ax, label="log10(transaction count + 1)")
    _save(fig, name)


# -----------------------------------------------------------------------------
# Hive-driven business-understanding additions: b14 ($ moved by pattern),
# b15 (account-lifetime by class), b16 (hour-of-day by class). These three
# treat the project as a real-world AML engagement: each speaks directly
# to a business question about laundering behaviour rather than about the
# benchmark dataset.
# -----------------------------------------------------------------------------

def plot_b14(df: pd.DataFrame, name: str) -> None:
    """Total USD value moved per canonical pattern type. Sums
    amount_paid across the laundering_patterns table (USD-only rows
    per the SQL). Two-panel: $ moved (left) and pattern-instance
    count (right) so the reader can see both "how much money" and
    "how often" each typology runs."""
    df = df.copy()
    df["canonical"] = df["pattern_type"].map(_canonicalize_pattern)
    for c in ["n_transactions", "n_pattern_instances", "total_usd"]:
        df[c] = df[c].astype(float)
    rolled = (df.groupby("canonical", as_index=False)
                .agg(n_transactions=("n_transactions", "sum"),
                     n_pattern_instances=("n_pattern_instances", "sum"),
                     total_usd=("total_usd", "sum"))
                .set_index("canonical")
                .reindex(CANONICAL_PATTERNS)
                .dropna(subset=["total_usd"])
                .reset_index())

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    y = np.arange(len(rolled))

    # Left panel: dollars moved.
    axes[0].barh(y, rolled["total_usd"] / 1e6, color=LAUNDER_COLOR)
    axes[0].set_yticks(y); axes[0].set_yticklabels(rolled["canonical"])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("USD moved through this typology (millions, USD-only rows)")
    axes[0].set_title("Money moved by typology")
    axes[0].grid(True, axis="x", alpha=0.3)
    for i, r in rolled.iterrows():
        axes[0].text(r["total_usd"] / 1e6, i,
                     f"  ${r['total_usd'] / 1e6:,.1f}M",
                     va="center", fontsize=8, color=NEUTRAL)

    # Right panel: number of pattern instances.
    axes[1].barh(y, rolled["n_pattern_instances"], color=NEUTRAL)
    axes[1].set_yticks(y); axes[1].set_yticklabels(rolled["canonical"])
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Number of laundering schemes (pattern instances)")
    axes[1].set_title("Scheme count by typology")
    axes[1].grid(True, axis="x", alpha=0.3)
    for i, r in rolled.iterrows():
        axes[1].text(r["n_pattern_instances"], i,
                     f"  {int(r['n_pattern_instances']):,}",
                     va="center", fontsize=8, color=NEUTRAL)

    fig.suptitle("b14 — Money laundered and scheme count, by canonical typology",
                 y=1.02)
    _save(fig, name)


_B15_BUCKETS = {
    0: "<1d",
    1: "1–2d",
    2: "2–4d",
    3: "4–7d",
    4: "7–11d",
    5: "11–14d",
    6: "14d+",
}


def plot_b15(df: pd.DataFrame, name: str) -> None:
    """Per-account lifetime distribution. Density per class on
    pre-binned ranges from <1 day to 14d+ (16-day active window)."""
    df = df.copy()
    df["ever_laundering"] = df["ever_laundering"].astype(int)
    df["lifetime_bucket"] = df["lifetime_bucket"].astype(int)
    df["n_accounts"] = df["n_accounts"].astype(int)

    bucket_order = list(_B15_BUCKETS.keys())
    pivot = (df.pivot_table(index="lifetime_bucket", columns="ever_laundering",
                             values="n_accounts", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legit only", 1: "Ever laundering"})
                .reindex(bucket_order, fill_value=0))
    legit_total = pivot["Legit only"].sum() or 1
    laund_total = pivot["Ever laundering"].sum() or 1
    legit = pivot["Legit only"] / legit_total * 100
    laund = pivot["Ever laundering"] / laund_total * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(bucket_order))
    w = 0.4
    ax.bar(x - w/2, legit, w, color=LEGIT_COLOR,
           label=f"Legit only (n={int(legit_total):,})")
    ax.bar(x + w/2, laund, w, color=LAUNDER_COLOR,
           label=f"Ever laundering (n={int(laund_total):,})")
    ax.set_xticks(x)
    ax.set_xticklabels([_B15_BUCKETS[b] for b in bucket_order])
    ax.set_xlabel("Account lifetime (first → last transaction)")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("b15 — Account lifetime distribution, by class")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, name)


def plot_b16(df: pd.DataFrame, name: str) -> None:
    """Per-hour density of transactions, separately for legit and
    laundering. Reads as 'do launderers prefer specific hours?'."""
    df = df.copy()
    df["hour_of_day"] = df["hour_of_day"].astype(int)
    df["is_laundering"] = df["is_laundering"].astype(int)
    df["n"] = df["n"].astype(int)
    pivot = (df.pivot_table(index="hour_of_day", columns="is_laundering",
                             values="n", aggfunc="sum", fill_value=0)
                .rename(columns={0: "Legitimate", 1: "Laundering"})
                .reindex(range(24), fill_value=0))
    legit_total = pivot["Legitimate"].sum() or 1
    laund_total = pivot["Laundering"].sum() or 1
    legit = pivot["Legitimate"] / legit_total * 100
    laund = pivot["Laundering"] / laund_total * 100

    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(24)
    ax.plot(x, legit, marker="o", color=LEGIT_COLOR,
            label=f"Legitimate (n={int(legit_total):,})")
    ax.plot(x, laund, marker="o", color=LAUNDER_COLOR,
            label=f"Laundering (n={int(laund_total):,})")
    ax.set_xticks(x)
    ax.set_xlabel("Hour of day (cluster local time)")
    ax.set_ylabel("Share of class (%)")
    ax.set_title("b16 — When do launderers move money? Per-hour density by class")
    ax.legend()
    ax.grid(True, alpha=0.3)
    _save(fig, name)


PLOTS = {
    "q1": plot_q1,
    "q2": plot_q2,
    "q3": plot_q3,
    "q4": plot_q4,
    "q5": plot_q5,
    "q6": plot_q6,
    "q7": plot_q7,
    "q7b": plot_q7b,
    "q8": plot_q8,
    "q9": plot_q9,
    "q10": plot_q10,
    "q11": plot_q11,
    "q12": plot_q12,
    "q13": plot_q13,
    "q14": plot_q14,
    "q15": plot_q15,
    "q16": plot_q16,
    "q17": plot_q17,
    "q18": plot_q18,
    "q19": plot_q19,
    "q20": plot_q20,
    "b1": plot_b1,
    "b4": plot_b4,
    "b5": plot_b5,
    "b6": plot_b6,
    "b14": plot_b14,
    "b15": plot_b15,
    "b16": plot_b16,
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
