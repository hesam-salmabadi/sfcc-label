"""Figure: how the unfrozen and frozen permittivity levels are obtained, for three topsoil winters.
Orange: bins between +0.8 and +2.5 degC whose median is the unfrozen level. Blue circles: flat run of the
coldest bins (observed frozen level, the criterion used to build the prior). Blue dashed: frozen level estimated
by the joint fit; blue band: prior range 0.44 +- 0.14 of the unfrozen level."""
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from common import COLORS as C, FIGURES, ROOT, style
from frozen_level_winters import plateau
from sfcc_label import classify as c

CASES = [("local_ec06_005cm_s1", 2014, "(a) frozen level observed", "EC06"),
         ("local_ug21_005cm_s1", 2014, "(b) cold, but still sinking", "UG21"),
         ("local_bj04_005cm_s1", 2020, "(c) never fully frozen", "BJ04")]
S = c.Settings()
style()
fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.9))
tt = np.linspace(-11, 2.5, 600)
for ax, (sid, fy, title, name) in zip(axes, CASES):
    frame = c.sensor_frame(c.read_standardized(ROOT / "standardized/local" / f"{sid}.csv"), True)
    fit = c.fit_sensor(sid, frame, S)
    w = fit.winters[fy]
    half = c.freezing_half(frame[c.freeze_year(frame.index) == fy], fy, c.readings_per_day(fit.step_h, 0.5), S)
    bins = c.bin_medians(half, S, 3)
    g_unf = c.unfrozen_level(bins, S)
    eu = g_unf**2
    lo, hi = S.unfrozen_range_c
    ax.axvspan(lo, hi, color=C["thawed"], alpha=0.10, lw=0)
    ax.axhspan((0.44 - 0.14) * eu, (0.44 + 0.14) * eu, color=C["frozen"], alpha=0.10, lw=0)
    ax.scatter(bins.index, bins.values**2, s=5, color=C["muted"], zorder=2)
    warm = bins[(bins.index >= lo) & (bins.index <= hi)]
    ax.scatter(warm.index, warm.values**2, s=7, color=C["thawed"], zorder=3)
    ax.axhline(eu, color=C["thawed"], lw=1, ls="--")
    pl = plateau(bins, g_unf) if bins.index.min() <= -5 else None
    if pl is not None:
        cold = bins[bins.index <= lo].sort_index()
        ref = cold.iloc[:3].median()
        run = cold[((cold - ref).abs() <= 0.10 * (g_unf - cold.min())).cumprod().astype(bool)]
        ax.scatter(run.index, run.values**2, s=16, facecolor="none", edgecolor=C["frozen"], lw=0.8, zorder=4)
        ax.axhline(pl**2, color=C["frozen"], lw=1.2)
    if w.fitted:
        g_fr = np.sqrt(w.eps_frozen)
        ax.axhline(w.eps_frozen, color=C["frozen"], lw=1.2, ls="--")
        ax.plot(tt, (g_unf - c.frozen_fraction(tt, w.t_on, w.t_fr, S) * (g_unf - g_fr)) ** 2, color=C["ink"], lw=1.3)
    ax.set_xlim(min(-2.0, max(-7.5, bins.index.min() - 0.5)), hi + 0.2)
    ax.set_ylim(0, eu * 1.25)
    ax.set_xlabel("soil temperature (°C)")
    obs = f"observed {pl**2:.1f}" if pl is not None else "not observed"
    ax.set_title(f"{title}\n{name} {fy}–{str(fy + 1)[2:]}, coldest {w.coldest_c:.1f} °C",
                 loc="left", fontsize=7)
    print(sid, fy, "eps_u", round(eu, 2), "observed", None if pl is None else round(pl**2, 2), "fitted",
          round(w.eps_frozen, 2), "coldest", w.coldest_c, "slow", w.slow, "status", w.status)
axes[0].set_ylabel(r"permittivity $\varepsilon$")
handles = [Patch(color=C["thawed"], alpha=0.25, label="+0.8 to +2.5 °C window"),
           Line2D([], [], color=C["thawed"], ls="--", label="unfrozen level ε_u (median of window bins)"),
           Line2D([], [], marker="o", ls="", mfc="none", mec=C["frozen"], label="flat run of coldest bins"),
           Line2D([], [], color=C["frozen"], label="observed frozen level (median of run)"),
           Line2D([], [], color=C["frozen"], ls="--", label="frozen level ε_r from the joint fit"),
           Patch(color=C["frozen"], alpha=0.2, label="prior range (0.44 ± 0.14) ε_u"),
           Line2D([], [], color=C["ink"], label="fitted curve")]
fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=6.3, frameon=False, bbox_to_anchor=(0.5, 0.0))
fig.set_size_inches(7.2, 3.3)
fig.subplots_adjust(left=0.08, right=0.99, top=0.8, bottom=0.34, wspace=0.28)
fig.savefig(FIGURES / "fig_levels.png")
