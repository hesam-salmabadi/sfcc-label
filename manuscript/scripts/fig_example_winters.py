"""Figure: two topsoil winters processed with sfcc_label.classify - a complete freeze and an incomplete one.
(a,d) binned permittivity vs soil temperature with the fitted curve; (b,e) soil temperature through the freeze
year with the transition range; (c,f) hourly state probabilities."""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import COLORS as C, FIGURES, ROOT, style
from sfcc_label import classify as c

CASES = [("local_ec06_005cm_s1", 2014, "Complete freeze: Kenaston EC06, HydraProbe, 5 cm"),
         ("local_bj04_005cm_s1", 2020, "Incomplete freeze: James Bay BJ04, TEROS12, 5 cm")]
S = c.Settings()
style()
fig, axes = plt.subplots(2, 3, figsize=(7.2, 5.4), gridspec_kw={"width_ratios": [1, 1.25, 1.25], "hspace": 0.65})
for (sid, fy, title), row in zip(CASES, axes):
    frame = c.sensor_frame(c.read_standardized(ROOT / "standardized/local" / f"{sid}.csv"), True)
    fit = c.fit_sensor(sid, frame, S)
    c.pool_sensors([fit])
    w = fit.winters[fy]
    prob = c.hourly_probabilities(fit, frame["T"], None, S)
    half = c.freezing_half(frame[c.freeze_year(frame.index) == fy], fy, c.readings_per_day(fit.step_h, 0.5), S)
    bins = c.bin_medians(half, S, 3)
    g_unf, g_fr = np.sqrt(w.eps_unfrozen), np.sqrt(w.eps_frozen)
    tt = np.linspace(-4, 2.5, 400)
    # (a) curve
    a = row[0]
    sel = bins[(bins.index >= -4) & (bins.index <= 2.5)]
    for on, fr in w.boots[:: max(1, len(w.boots) // 60)]:
        a.plot(tt, (g_unf - c.frozen_fraction(tt, on, fr, S) * (g_unf - g_fr)) ** 2, color=C["muted"], lw=0.5, alpha=0.25)
    a.scatter(sel.index, sel.values**2, s=6, color=C["ink2"], zorder=3)
    a.plot(tt, (g_unf - c.frozen_fraction(tt, w.t_on, w.t_fr, S) * (g_unf - g_fr)) ** 2, color=C["ink"], lw=1.6)
    a.axhline(w.eps_unfrozen, color=C["thawed"], lw=0.8, ls="--")
    a.axhline(w.eps_frozen, color=C["frozen"], lw=0.8, ls="--")
    a.axvline(w.t_on_pooled, color=C["thawed"], lw=1.1, ls=":"); a.axvline(w.t_fr_pooled, color=C["frozen"], lw=1.1, ls=":")
    a.axvline(w.coldest_c, color=C["muted"], lw=0.8)
    a.set_xlim(-4, 2.5); a.set_ylim(0, None); a.set_ylabel(r"permittivity $\varepsilon$")
    a.text(0, 1.2, f"{title} — T$_{{on}}$ = {w.t_on_pooled:+.2f} ± {w.t_on_pooled_sd:.2f} °C, "
           f"T$_{{fr}}$ = {w.t_fr_pooled:+.2f} ± {w.t_fr_pooled_sd:.2f} °C", transform=a.transAxes, fontsize=8,
           weight="bold", ha="left", va="bottom")
    # (b) temperature
    win = slice(f"{fy}-10-01", f"{fy + 1}-05-31")
    T = frame.loc[win, "T"].resample("6h").mean()
    b = row[1]
    b.axhspan(w.t_fr_pooled, w.t_on_pooled, color=C["transition"], alpha=0.18, lw=0)
    b.plot(T.index, T, color=C["ink"], lw=0.8)
    coldest = prob.loc[win].index[(prob.loc[win, "leg"] == "thawing").values.argmax()]
    b.axvline(coldest, color=C["muted"], lw=0.8, ls="--")
    b.text(coldest, -6.8, " thawing leg →", fontsize=6.5, color=C["ink2"], va="bottom")
    b.set_ylim(-7, 6); b.set_ylabel("soil T (°C)")
    # (c) probabilities
    p = prob.loc[win, ["p_frozen", "p_transition", "p_thawed"]].astype(float).resample("6h").mean()
    d = row[2]
    d.stackplot(p.index, p.p_frozen.fillna(0), p.p_transition.fillna(0), p.p_thawed.fillna(0),
                colors=[C["frozen"], C["transition"], C["thawed"]], alpha=0.75, lw=0,
                labels=["frozen", "transition", "thawed"])
    d.set_ylim(0, 1); d.set_ylabel("probability")
    for ax in (b, d):
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[11, 1, 3, 5]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
for ax, lab in zip(axes.flat, "abcdef"):
    ax.text(-0.02, 1.02, f"({lab})", transform=ax.transAxes, fontsize=8, ha="right", va="bottom", weight="bold")
handles, labels = axes[0, 2].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=7, frameon=False, bbox_to_anchor=(0.72, -0.01))
for ax in axes[:, 0]:
    ax.set_xlabel("soil temperature (°C)")
fig.subplots_adjust(left=0.08, right=0.99, top=0.9, bottom=0.12, wspace=0.42)
fig.savefig(FIGURES / "fig_example_winters.png")
print({sid: {k: round(getattr(fit.winters[fy], k), 3) for k in ("t_on_pooled", "t_fr_pooled", "t_on_pooled_sd",
       "t_fr_pooled_sd", "eps_unfrozen", "eps_frozen", "coldest_c")} for (sid, fy, _), fit in [(CASES[-1], fit)]})
