"""Figure: temperature binning of one freezing leg (Kenaston EC02, HydraProbe, 5 cm, winter 2017-18).
(a) soil temperature through the freezing leg with short freeze-thaw episodes before the main freeze;
(b) every hourly reading in permittivity-temperature space and the 0.1 degC bin medians;
(c) hours per 0.1 degC bin - the soil spends weeks near 0 degC but each bin contributes one point."""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import COLORS as C, FIGURES, ROOT, style
from sfcc_label import classify as c

SID, FY = "local_ec02_005cm_s1", 2017
S = c.Settings()
style()
frame = c.sensor_frame(c.read_standardized(ROOT / "standardized/local" / f"{SID}.csv"), True)
fit = c.fit_sensor(SID, frame, S)
c.pool_sensors([fit])
w = fit.winters[FY]
half = c.freezing_half(frame[c.freeze_year(frame.index) == FY], FY, c.readings_per_day(fit.step_h, 0.5), S)
bins = c.bin_medians(half, S, 3)
counts = half.groupby(np.round(half["T"] / S.bin_width_c) * S.bin_width_c).size()

# main freeze = last continuous run of days below T_on that reaches the coldest day; earlier sub-T_on days = episodes
daily = half["T"].resample("D").mean()
below = daily < w.t_on
run_id = (~below).cumsum()
main_start = daily[below & (run_id == run_id.iloc[-1])].index.min()
episode_days = daily.index[below & (daily.index < main_start)]
hour_day = half.index.normalize()
episode = hour_day.isin(episode_days)

fig = plt.figure(figsize=(7.2, 2.9))
gs = fig.add_gridspec(1, 3, width_ratios=[1.35, 1, 0.75], wspace=0.38)
a, b, h = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])
T6 = half["T"].resample("6h").mean()
a.plot(T6.index, T6, color=C["ink"], lw=0.8)
for day in episode_days:
    a.axvspan(day, day + pd.Timedelta(days=1), color=C["thawed"], alpha=0.35, lw=0)
a.axvspan(main_start, half.index.max(), color=C["frozen"], alpha=0.08, lw=0)
a.axhline(0, color=C["ink2"], lw=0.6)
a.text(main_start + pd.Timedelta(days=3), 5.4, "main freeze", fontsize=7, color=C["frozen"], va="top")
a.set_ylim(-10, 6); a.set_ylabel("soil T (°C)")
a.xaxis.set_major_locator(mdates.MonthLocator()); a.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
a.set_title("(a) freezing leg (1 Aug to coldest day)", loc="left", fontsize=8)
sel = half[(half["T"] >= -3) & (half["T"] <= 2.5)]
b.scatter(sel["T"][~episode[half.index.isin(sel.index)]], sel["g"][~episode[half.index.isin(sel.index)]] ** 2,
          s=2, color=C["muted"], alpha=0.35, lw=0, label="hourly readings")
b.scatter(sel["T"][episode[half.index.isin(sel.index)]], sel["g"][episode[half.index.isin(sel.index)]] ** 2,
          s=3, color=C["thawed"], alpha=0.6, lw=0, label="short episodes")
bs = bins[(bins.index >= -3) & (bins.index <= 2.5)]
b.scatter(bs.index, bs.values**2, s=12, color=C["ink"], zorder=3, label="bin median (0.1 °C)")
b.axvline(w.t_on_pooled, color=C["thawed"], ls=":", lw=1); b.axvline(w.t_fr_pooled, color=C["frozen"], ls=":", lw=1)
b.set_xlabel("soil temperature (°C)"); b.set_ylabel(r"permittivity $\varepsilon$")
b.set_title("(b) readings and bin medians", loc="left", fontsize=8)
from matplotlib.lines import Line2D
b.legend(handles=[Line2D([], [], marker="o", ls="", ms=3, color=C["muted"], label="hourly readings"),
                  Line2D([], [], marker="o", ls="", ms=3, color=C["thawed"], label="short episodes"),
                  Line2D([], [], marker="o", ls="", ms=4.5, color=C["ink"], label="bin median (0.1 °C)")],
         fontsize=6.3, frameon=False, loc="lower right")
cs = counts[(counts.index >= -3) & (counts.index <= 2.5)]
h.barh(cs.index, cs.values, height=0.09, color=C["ink2"])
h.set_xscale("log"); h.set_ylim(-3, 2.5); h.set_xlabel("hours per bin")
h.set_ylabel("soil temperature (°C)")
h.set_title("(c) readings per bin", loc="left", fontsize=8)
fig.subplots_adjust(left=0.09, right=0.99, top=0.86, bottom=0.17)
fig.savefig(FIGURES / "fig_binning.png")
print(f"episode days {len(episode_days)}, main freeze from {main_start.date()}, bins {len(bins)}, "
      f"hours within ±0.5 °C {int(counts[(counts.index > -0.55) & (counts.index < 0.55)].sum())}, "
      f"max hours in one bin {int(counts.max())}, T_on {w.t_on_pooled:.2f}, T_fr {w.t_fr_pooled:.2f}")
