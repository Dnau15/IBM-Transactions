"""Plot Stage I format benchmark — write and read figures, separate files.

Reads `output/format_benchmark.csv` (or path passed as argv[1]) and writes
`report/images/format_benchmark_write.png` and `..._read.png`.

Each plot is a grouped bar chart: codec on the x-axis, AVRO and Parquet as
the two grouped bars per codec. Missing cells (cached writes, unsupported
codec combos) are rendered as zero-height bars with a textual marker.
"""
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO / "output" / "format_benchmark.csv"
OUT_DIR = REPO / "report" / "images"

CODECS = ["none", "snappy", "gzip", "bzip2"]
FORMATS = ["avro", "parquet"]
COLORS = {"avro": "#5b8def", "parquet": "#f08b3a"}


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def missing_label(raw_value, status):
    """Short marker for missing-value cells."""
    if status == "codec_unsupported":
        return "unsupp."
    if raw_value == "cached":
        return "no data"
    if raw_value == "NA":
        return "n/a"
    return "—"


def plot_metric(rows, metric, title, ylabel, outfile):
    by = {(r["format"], r["codec"]): r for r in rows}

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(CODECS))
    width = 0.38

    max_val = 0.0
    for fmt in FORMATS:
        for c in CODECS:
            v = to_float(by.get((fmt, c), {}).get(metric, ""))
            if v is not None:
                max_val = max(max_val, v)

    for i, fmt in enumerate(FORMATS):
        offset = (i - 0.5) * width
        ys = []
        labels = []
        for c in CODECS:
            row = by.get((fmt, c), {})
            v = to_float(row.get(metric, ""))
            ys.append(v if v is not None else 0.0)
            if v is not None:
                labels.append(f"{v:.1f}")
            else:
                labels.append(missing_label(row.get(metric, ""),
                                            row.get("status", "")))
        bars = ax.bar(x + offset, ys, width, label=fmt.upper(),
                      color=COLORS[fmt], edgecolor="white")
        for j, bar in enumerate(bars):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.01,
                    labels[j],
                    ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels([c.title() for c in CODECS])
    ax.set_xlabel("Compression codec")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="upper left", frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_ylim(0, max_val * 1.18)
    ax.yaxis.grid(True, linestyle=":", alpha=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(outfile, dpi=150)
    plt.close(fig)
    print(f"wrote {outfile}")


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    with csv_path.open() as fh:
        rows = list(csv.DictReader(fh))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    plot_metric(
        rows, "write_seconds",
        "Sqoop write time — HI-Medium transactions (31.9M rows)",
        "Seconds (lower is better)",
        OUT_DIR / "format_benchmark_write.png",
    )
    plot_metric(
        rows, "read_seconds",
        "Spark full-table read time — HI-Medium transactions",
        "Seconds (lower is better)",
        OUT_DIR / "format_benchmark_read.png",
    )


if __name__ == "__main__":
    main()
