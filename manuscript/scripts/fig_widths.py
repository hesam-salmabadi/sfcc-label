"""Figure: curve width T_on - T_fr of fitted topsoil winters and the slow-freeze cut-off.
Needs data/winter_widths.csv (winter_widths.py)."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter

from common import COLORS as C, DATA, FIGURES, style

style()
w = pd.read_csv(DATA / "winter_widths.csv")
w = w[w.status == "fitted"]
well, other = w[w.frozen_level_seen], w[~w.frozen_level_seen]
cut = well.width_c.quantile(0.9)
slow = w.width_c > cut
print(f"fitted {len(w)}, frozen level seen {len(well)} at {well.sensor_id.nunique()} sensors, cut {cut:.2f}, "
      f"median seen {well.width_c.median():.2f}, slow {slow.sum()} ({slow.mean() * 100:.1f} %), "
      f"of which frozen level seen {(slow & w.frozen_level_seen).sum()}")

fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 3.1))
edges = np.arange(0, 7.6, 0.2)
a.hist([well.width_c, other.width_c], bins=edges, stacked=True, color=[C["frozen"], C["muted"]],
       label=[f"frozen level seen ({len(well)})", f"frozen level not seen ({len(other)})"],
       rwidth=0.9)
a.axvline(cut, color=C["ink"], lw=1.2)
a.text(cut + 0.1, a.get_ylim()[1] * 0.62, f"90th percentile of blue\n= {cut:.2f} °C\n{slow.sum()} winters to the right",
       fontsize=7)
a.set_xlabel(r"curve width $T_{on} - T_{fr}$ (°C)"); a.set_ylabel("number of winters")
a.set_title("(a) one bar = 0.2 °C of width", loc="left", fontsize=8.5)
a.legend(fontsize=6.8, frameon=False, loc="upper right", bbox_to_anchor=(1.0, 1.0))
a.set_xlim(0, 7.6)

for d, col in ((other, C["muted"]), (well, C["frozen"])):
    b.scatter(d.eps_unfrozen, d.width_c, s=4, lw=0, alpha=0.45, color=col)
b.axhline(cut, color=C["ink"], lw=1.2)
b.set_xscale("log"); b.set_xlim(2.5, 60); b.set_ylim(0, 7.6)
b.xaxis.set_major_locator(FixedLocator([3, 5, 10, 20, 40])); b.xaxis.set_minor_locator(NullLocator())
b.xaxis.set_major_formatter(ScalarFormatter())
b.set_xlabel(r"unfrozen permittivity $\varepsilon_u$ (wetness)"); b.set_ylabel(r"$T_{on} - T_{fr}$ (°C)")
b.set_title("(b) one dot = one winter", loc="left", fontsize=8.5)
fig.tight_layout()
fig.savefig(FIGURES / "fig_widths.png")
