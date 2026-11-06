"""PNG do alerta: velas 4H, zonas (escada), âncora, entrada e stop. matplotlib (backend Agg)."""
from __future__ import annotations
import os
from . import store


def render(coin, h4, zones, entry=None, stop=None, anchor=None, title="", out_name="chart.png", bars=90, tp=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    h4 = h4[-bars:]
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=110)
    fig.patch.set_facecolor("#0b0d12"); ax.set_facecolor("#151821")
    for i, c in enumerate(h4):
        col = "#21c37a" if c["close"] >= c["open"] else "#ff5470"
        ax.plot([i, i], [c["low"], c["high"]], color=col, lw=.8)
        ax.add_patch(Rectangle((i - .35, min(c["open"], c["close"])), .7, abs(c["close"] - c["open"]) or 1e-12, color=col))
    t0 = h4[0]["start"] if h4 else 0
    for z in zones:
        x0 = max(0, sum(1 for c in h4 if c["start"] < int(float(z.get("formed_ts", t0)))) - 2)
        col = {"CONFIRMED": "#7c5cff", "USED": "#7c5cff", "TESTED": "#f5b942"}.get(z["status"], "#3a7bd5")
        ax.add_patch(Rectangle((x0, float(z["zone_bottom"])), len(h4) - x0, float(z["zone_top"]) - float(z["zone_bottom"]),
                               color=col, alpha=.22, lw=0))
        ax.text(len(h4) - .5, float(z["zone_top"]), f"#{z.get('rank', '')} {z['status']}", color=col, fontsize=7, va="bottom", ha="right")
    for y, lab, col, ls in ((entry, "entrada", "#21c37a", "-"), (stop, "stop", "#ff5470", "--"),
                               (tp, "TP", "#7c5cff", "-."), (anchor, "âncora (1D)", "#8a90a2", ":")):
        if y:
            ax.axhline(y, color=col, ls=ls, lw=1.2); ax.text(0, y, f" {lab} {y:,.6g}", color=col, fontsize=8, va="bottom")
    ax.set_title(title or coin, color="#e8eaf0", fontsize=11, loc="left")
    ax.tick_params(colors="#8a90a2"); [s.set_color("#232838") for s in ax.spines.values()]
    step = max(1, len(h4) // 8)
    ax.set_xticks(range(0, len(h4), step)); ax.set_xticklabels([store.iso(h4[i]["start"])[5:13].replace("T", " ") for i in range(0, len(h4), step)], fontsize=7)
    ax.grid(color="#232838", lw=.5); ax.set_xlim(-1, len(h4))
    d = os.path.join(store.STATE, "charts"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, out_name); fig.tight_layout(); fig.savefig(p, facecolor=fig.get_facecolor()); plt.close(fig)
    return p
