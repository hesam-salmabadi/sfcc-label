"""Figure: choosing where temperature-only sensors borrow thresholds (leave-one-site-out test).
Needs data/grouping_winters.csv and data/grouping_errors.csv (grouping_test.py)."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import COLORS as C, DATA, FIGURES, style

style()
d = pd.read_csv(DATA / "grouping_winters.csv")
e = pd.read_csv(DATA / "grouping_errors.csv")
EXAMPLE = "local_bj04_005cm_s1"
SHOW = {"global": "none (all sites)", "land cover (6 classes)": "land cover", "texture": "soil texture",
        "biome": "biome", "land cover x texture": "land cover × texture", "biome x texture": "biome × texture",
        "biome x land cover x texture": "biome × cover × texture", "network x probe": "network × probe"}
COL = {"land cover x texture": "sensor_class x texture_class_usda", "biome x texture": "biome x texture_class_usda",
       "network x probe": "network x probe"}

fig = plt.figure(figsize=(7.2, 6.4))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.05], hspace=0.42, wspace=0.08)
a = fig.add_subplot(gs[0, :])
ex = d[d.sensor_id == EXAMPLE]
site = ex.site.iloc[0]
others = d[d.site != site]
truth = ex.t_on.mean()
cases = [("global", "none (all other sites)"), ("land cover x texture", "land cover × texture"),
         ("biome x texture", "biome × texture"), ("network x probe", "network × probe")]
rng = np.random.default_rng(0)
for i, (key, label) in enumerate(cases):
    g = others if key == "global" else others[others[COL[key]] == ex[COL[key]].iloc[0]]
    x = i + rng.uniform(-0.28, 0.28, len(g))
    a.scatter(x, g.t_on, s=3 if len(g) > 500 else 7, color=C["muted"], alpha=0.35 if len(g) > 500 else 0.7, lw=0)
    pred = g.t_on.median()
    a.plot([i - 0.34, i + 0.34], [pred, pred], color=C["ink"], lw=2)
    name = "all" if key == "global" else ex[COL[key]].iloc[0].replace("|", " + ").replace("Boreal Forests/Taiga", "boreal")
    a.text(i, 1.62, f"{label}\n{name}\n{len(g):,} winters, {g.site.nunique()} sites", ha="center", va="bottom", fontsize=6.4)
    a.text(i + 0.36, pred, f"{pred:+.2f}\nerror {abs(pred - truth):.2f}", fontsize=6.4, va="center")
a.axhline(truth, color=C["thawed"], lw=1.2, ls="--")
a.text(3.88, truth + 0.12, f"BJ04 fitted $T_{{on}}$ {truth:+.2f} (truth)", color=C["thawed"], fontsize=6.5, va="bottom", ha="right")
a.set_xlim(-0.5, 3.9); a.set_ylim(-2, 1.6); a.set_xticks([])
a.set_ylabel(r"$T_{on}$ of other sites' winters (°C)")
a.set_title("(a) worked example: James Bay BJ04 hidden, T_on predicted from the other sites (black bar = median)",
            loc="left", fontsize=8, pad=40)

for j, (tgt, lab) in enumerate((("T_on", "(b) error in $T_{on}$"), ("T_fr", "(c) error in $T_{fr}$"))):
    ax = fig.add_subplot(gs[1, j])
    sub = e[(e.target == tgt) & e.grouping.isin(SHOW)]
    stats = sub.groupby("grouping").error.quantile([0.25, 0.5, 0.75]).unstack()
    stats = stats.loc[list(SHOW)].iloc[::-1]
    y = np.arange(len(stats))
    colors = [C["frozen"] if k == "biome x texture" else C["ink"] if k == "network x probe" else C["muted"]
              for k in stats.index]
    ax.hlines(y, stats[0.25], stats[0.75], color=colors, lw=1.2)
    ax.scatter(stats[0.5], y, color=colors, s=22, zorder=3)
    for yy, m in zip(y, stats[0.5]):
        ax.text(stats[0.75].max() + 0.02, yy, f"{m:.2f}", va="center", fontsize=6.5)
    ax.set_yticks(y)
    ax.set_yticklabels([SHOW[k] for k in stats.index] if j == 0 else [], fontsize=6.8)
    ax.set_xlim(0, stats[0.75].max() + 0.14)
    ax.set_xlabel("|predicted − fitted| (°C)", fontsize=7.5)
    ax.set_title(lab, loc="left", fontsize=8)
fig.text(0.5, 0.005, "dot: median over 4,507 winters at 978 sites; line: 25th–75th percentile", ha="center", fontsize=6.5,
         color=C["ink2"])
fig.subplots_adjust(left=0.19, right=0.98, top=0.87, bottom=0.08)
fig.savefig(FIGURES / "fig_grouping.png")
