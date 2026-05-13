"""Render the 8 canonical AMLworld laundering patterns as a single figure.

Each pattern is drawn as a small directed graph using matplotlib only
(no networkx dependency). The layouts are hand-tuned so each subplot
fits its name without overlap.

Output: report/images/canonical_patterns.png
"""
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

OUT = Path(__file__).resolve().parent.parent / "report" / "images" / "canonical_patterns.png"

NODE_KW = dict(s=320, c="#4c72b0", zorder=3, edgecolors="white", linewidths=1.6)
SUSP_KW = dict(s=320, c="#c44e52", zorder=3, edgecolors="white", linewidths=1.6)
ARROW_KW = dict(arrowstyle="-|>", mutation_scale=14, color="#444", lw=1.5,
                shrinkA=11, shrinkB=11, zorder=2)


def _draw_arrow(ax, p1, p2):
    ax.add_patch(FancyArrowPatch(p1, p2, **ARROW_KW))


def _setup(ax, title):
    ax.set_title(title, fontsize=11)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)


def fan_in(ax):
    _setup(ax, "Fan-in")
    # Five senders → one receiver
    centre = (0.0, -0.4)
    senders = [(-1.0, 0.7), (-0.5, 0.95), (0.0, 1.0), (0.5, 0.95), (1.0, 0.7)]
    for (x, y) in senders:
        ax.scatter(x, y, **NODE_KW)
        _draw_arrow(ax, (x, y), centre)
    ax.scatter(*centre, **SUSP_KW)


def fan_out(ax):
    _setup(ax, "Fan-out")
    centre = (0.0, 0.4)
    receivers = [(-1.0, -0.7), (-0.5, -0.95), (0.0, -1.0), (0.5, -0.95), (1.0, -0.7)]
    ax.scatter(*centre, **SUSP_KW)
    for (x, y) in receivers:
        ax.scatter(x, y, **NODE_KW)
        _draw_arrow(ax, centre, (x, y))


def gather_scatter(ax):
    _setup(ax, "Gather-scatter")
    src = [(-1.05, 0.85), (-1.05, 0.0), (-1.05, -0.85)]
    sink = [(1.05, 0.85), (1.05, 0.0), (1.05, -0.85)]
    hub = (0.0, 0.0)
    for p in src:
        ax.scatter(*p, **NODE_KW)
        _draw_arrow(ax, p, hub)
    for p in sink:
        ax.scatter(*p, **NODE_KW)
        _draw_arrow(ax, hub, p)
    ax.scatter(*hub, **SUSP_KW)


def scatter_gather(ax):
    _setup(ax, "Scatter-gather")
    src = (-1.05, 0.0)
    mids = [(0.0, 0.85), (0.0, 0.0), (0.0, -0.85)]
    sink = (1.05, 0.0)
    ax.scatter(*src, **SUSP_KW)
    for m in mids:
        ax.scatter(*m, **NODE_KW)
        _draw_arrow(ax, src, m)
        _draw_arrow(ax, m, sink)
    ax.scatter(*sink, **SUSP_KW)


def cycle(ax):
    _setup(ax, "Cycle")
    n = 5
    R = 0.85
    pts = [(R * math.cos(2 * math.pi * k / n + math.pi / 2),
            R * math.sin(2 * math.pi * k / n + math.pi / 2)) for k in range(n)]
    for p in pts:
        ax.scatter(*p, **NODE_KW)
    for i in range(n):
        _draw_arrow(ax, pts[i], pts[(i + 1) % n])


def random_walk(ax):
    _setup(ax, "Random walk")
    pts = [(-1.0, 0.4), (-0.4, 0.9), (0.1, 0.1),
           (0.5, -0.7), (1.0, -0.1)]
    for p in pts:
        ax.scatter(*p, **NODE_KW)
    for i in range(len(pts) - 1):
        _draw_arrow(ax, pts[i], pts[i + 1])


def bipartite(ax):
    _setup(ax, "Bipartite")
    left = [(-0.9, 0.85), (-0.9, 0.0), (-0.9, -0.85)]
    right = [(0.9, 0.85), (0.9, 0.0), (0.9, -0.85)]
    for p in left + right:
        ax.scatter(*p, **NODE_KW)
    for l in left:
        for r in right:
            _draw_arrow(ax, l, r)


def stack(ax):
    _setup(ax, "Stack")
    pts = [(-1.05, 0.0), (-0.55, 0.0), (-0.05, 0.0),
           (0.45, 0.0), (0.95, 0.0)]
    for p in pts:
        ax.scatter(*p, **NODE_KW)
    for i in range(len(pts) - 1):
        _draw_arrow(ax, pts[i], pts[i + 1])


def build():
    fig, axes = plt.subplots(2, 4, figsize=(11.5, 5.6))
    fns = [fan_in, fan_out, gather_scatter, scatter_gather,
           cycle, random_walk, bipartite, stack]
    for ax, fn in zip(axes.flat, fns):
        fn(ax)
    fig.suptitle(
        "The eight canonical AMLworld laundering patterns",
        fontsize=13, y=1.01,
    )
    fig.tight_layout()
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
