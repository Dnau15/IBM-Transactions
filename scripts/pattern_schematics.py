"""b10 — Schematic diagrams of the 8 canonical AMLworld laundering patterns.

Stylised (not drawn from real motif instances). Each panel is a small
directed graph showing the topology of one pattern type. Visual encoding:
hollow circle = source (placement-side), grey-filled = intermediate,
red-filled = sink (integration-side). Edges flow source -> sink in the
visual layout.

Produces output/b10_mpl.jpg ready for inclusion in §1.4 (Terminology)
and §3.7 (Patterns) of the report. Reference figure is Altman et al.
NeurIPS 2023 Figure 2.

Run:
    python scripts/pattern_schematics.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "output"

SRC_COLOR = "white"          # hollow with edge -> source
MID_COLOR = "#cccccc"        # grey -> intermediate
SNK_COLOR = "#c33"           # red -> sink
EDGE_COLOR = "#444"


def _draw(ax, nodes, edges, title):
    """nodes: dict id -> (x, y, role); role in {'src','mid','snk'}.
    edges: list of (src_id, dst_id) tuples. Layout pre-computed."""
    role_color = {"src": SRC_COLOR, "mid": MID_COLOR, "snk": SNK_COLOR}
    # Edges first so nodes overlap the arrowheads.
    for s, d in edges:
        x0, y0, _ = nodes[s]
        x1, y1, _ = nodes[d]
        ax.annotate("",
                    xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="-|>", color=EDGE_COLOR,
                                    lw=1.2, shrinkA=10, shrinkB=10))
    for nid, (x, y, role) in nodes.items():
        circle = mpatches.Circle((x, y), 0.06,
                                 facecolor=role_color[role],
                                 edgecolor="black", linewidth=1.0,
                                 zorder=10)
        ax.add_patch(circle)
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=10)


def _fan_in():
    """Many sources -> one sink."""
    nodes = {
        0: (0.1, 0.85, "src"),
        1: (0.1, 0.6, "src"),
        2: (0.1, 0.35, "src"),
        3: (0.1, 0.1, "src"),
        4: (0.85, 0.475, "snk"),
    }
    edges = [(i, 4) for i in range(4)]
    return nodes, edges


def _fan_out():
    """One source -> many sinks."""
    nodes = {
        0: (0.15, 0.475, "src"),
        1: (0.9, 0.85, "snk"),
        2: (0.9, 0.6, "snk"),
        3: (0.9, 0.35, "snk"),
        4: (0.9, 0.1, "snk"),
    }
    edges = [(0, i) for i in range(1, 5)]
    return nodes, edges


def _gather_scatter():
    """Many -> one intermediate -> many. (Sources gather into a hub
    which then scatters to many sinks.)"""
    nodes = {
        0: (0.05, 0.85, "src"),
        1: (0.05, 0.6, "src"),
        2: (0.05, 0.35, "src"),
        3: (0.05, 0.1, "src"),
        4: (0.5, 0.475, "mid"),
        5: (0.95, 0.85, "snk"),
        6: (0.95, 0.6, "snk"),
        7: (0.95, 0.35, "snk"),
        8: (0.95, 0.1, "snk"),
    }
    edges = [(i, 4) for i in range(4)] + [(4, i) for i in range(5, 9)]
    return nodes, edges


def _scatter_gather():
    """One source -> many intermediates -> one sink."""
    nodes = {
        0: (0.05, 0.475, "src"),
        1: (0.5, 0.85, "mid"),
        2: (0.5, 0.6, "mid"),
        3: (0.5, 0.35, "mid"),
        4: (0.5, 0.1, "mid"),
        5: (0.95, 0.475, "snk"),
    }
    edges = [(0, i) for i in range(1, 5)] + [(i, 5) for i in range(1, 5)]
    return nodes, edges


def _cycle():
    """Closed directed loop."""
    nodes = {}
    edges = []
    n = 6
    centre = (0.5, 0.5)
    r = 0.35
    for i in range(n):
        theta = np.pi / 2 - 2 * np.pi * i / n
        x = centre[0] + r * np.cos(theta)
        y = centre[1] + r * np.sin(theta)
        role = "src" if i == 0 else ("snk" if i == n // 2 else "mid")
        nodes[i] = (x, y, role)
    for i in range(n):
        edges.append((i, (i + 1) % n))
    return nodes, edges


def _random_walk():
    """Chain A -> B -> C -> D -> E. No convergence."""
    nodes = {
        0: (0.1, 0.5,  "src"),
        1: (0.3, 0.7,  "mid"),
        2: (0.5, 0.35, "mid"),
        3: (0.7, 0.65, "mid"),
        4: (0.9, 0.45, "snk"),
    }
    edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
    return nodes, edges


def _bipartite():
    """Two layers, cross-layer directed edges only. Multiple edges per
    source mimic a multipartite money-mule topology."""
    nodes = {
        0: (0.15, 0.85, "src"),
        1: (0.15, 0.55, "src"),
        2: (0.15, 0.25, "src"),
        3: (0.85, 0.85, "snk"),
        4: (0.85, 0.55, "snk"),
        5: (0.85, 0.25, "snk"),
    }
    edges = [(0, 3), (0, 4),
             (1, 3), (1, 4), (1, 5),
             (2, 4), (2, 5)]
    return nodes, edges


def _stack():
    """Sequential accumulation. Pairs of sources feed each successive
    intermediate node which then forwards to the final sink."""
    nodes = {
        0: (0.05, 0.85, "src"),
        1: (0.05, 0.55, "src"),
        2: (0.05, 0.25, "src"),
        3: (0.35, 0.85, "mid"),
        4: (0.35, 0.55, "mid"),
        5: (0.35, 0.25, "mid"),
        6: (0.65, 0.55, "mid"),
        7: (0.95, 0.55, "snk"),
    }
    edges = [
        (0, 3), (1, 4), (2, 5),     # one-to-one feeders
        (3, 6), (4, 6), (5, 6),     # converge into stack
        (6, 7),                      # forward to sink
    ]
    return nodes, edges


PATTERNS = [
    ("FAN-IN",         _fan_in),
    ("FAN-OUT",        _fan_out),
    ("GATHER-SCATTER", _gather_scatter),
    ("SCATTER-GATHER", _scatter_gather),
    ("CYCLE",          _cycle),
    ("RANDOM",         _random_walk),
    ("BIPARTITE",      _bipartite),
    ("STACK",          _stack),
]


def main():
    fig, axes = plt.subplots(2, 4, figsize=(14, 7))
    for ax, (name, fn) in zip(axes.ravel(), PATTERNS):
        nodes, edges = fn()
        _draw(ax, nodes, edges, name)

    # Legend at the bottom.
    legend_handles = [
        mpatches.Patch(facecolor=SRC_COLOR, edgecolor="black", label="Source"),
        mpatches.Patch(facecolor=MID_COLOR, edgecolor="black", label="Intermediate"),
        mpatches.Patch(facecolor=SNK_COLOR, edgecolor="black", label="Sink"),
    ]
    fig.legend(handles=legend_handles, loc="lower center",
               ncol=3, fontsize=10, frameon=False,
               bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("b10 — Eight canonical laundering patterns "
                 "(stylised; after Altman et al. 2023 Fig. 2)",
                 fontsize=12, y=0.99)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "b10_mpl.jpg"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
