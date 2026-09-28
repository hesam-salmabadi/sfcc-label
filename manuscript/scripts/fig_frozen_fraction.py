"""Figure: frozen-to-unfrozen permittivity ratio of topsoil winters with an observed frozen level.
Needs data/frozen_level_winters.csv (frozen_level_winters.py)."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import COLORS as C, DATA, FIGURES, style

style()
w = pd.read_csv(DATA / "frozen_level_winters.csv")
w = w[w.depth_class == "topsoil"]
f = w.frozen_fraction
q10, q50, q90 = f.quantile([0.1, 0.5, 0.9])
print(f"topsoil winters {len(w)}, sensors {w.sensor_id.nunique()}, mean {f.mean():.3f}, median {q50:.3f}, "
      f"sd {f.std():.3f}, p10 {q10:.2f}, p90 {q90:.2f}")

fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 3.0))
a.hist(f, bins=np.linspace(0, 1, 41), color=C["frozen"], alpha=0.85)
a.axvspan(q10, q90, color=C["grid"], alpha=0.6, lw=0, zorder=0)
a.axvline(q50, color=C["ink"], lw=1.2)
a.text(q50 + 0.015, a.get_ylim()[1] * 0.93, f"median {q50:.2f}\nmean {f.mean():.2f}", fontsize=7.5, va="top")
a.text(q10, a.get_ylim()[1] * 0.5, f"{q10:.2f}", fontsize=7, ha="right", color=C["ink2"])
a.text(q90, a.get_ylim()[1] * 0.5, f" {q90:.2f}", fontsize=7, color=C["ink2"])
a.set_xlabel(r"$\varepsilon_r / \varepsilon_u$"); a.set_ylabel("number of winters")
a.set_title("(a) frozen / unfrozen permittivity", loc="left", fontsize=8.5)
b.scatter(w.eps_unfrozen, w.eps_frozen, s=5, color=C["frozen"], alpha=0.45, lw=0)
x = np.array([3, 60])
for k, ls in ((0.44, "-"), (q10, ":"), (q90, ":")):
    b.plot(x, k * x, color=C["ink"], lw=1 if ls == "-" else 0.8, ls=ls)
b.text(30, 0.44 * 30 * 1.25, r"$0.44\,\varepsilon_u$", fontsize=7.5, ha="center")
b.set_xscale("log"); b.set_yscale("log"); b.set_xlim(4, 60); b.set_ylim(1.5, 40)
from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter
for axis, ticks in ((b.xaxis, [5, 10, 20, 40]), (b.yaxis, [2, 5, 10, 20])):
    axis.set_major_locator(FixedLocator(ticks)); axis.set_minor_locator(NullLocator())
    axis.set_major_formatter(ScalarFormatter())
b.set_xlabel(r"unfrozen permittivity $\varepsilon_u$"); b.set_ylabel(r"frozen permittivity $\varepsilon_r$")
b.set_title("(b) one dot = one winter", loc="left", fontsize=8.5)
fig.tight_layout()
fig.savefig(FIGURES / "fig_frozen_fraction.png")
