"""Shared paths and figure style for the manuscript scripts."""
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FIGURES = HERE.parent / "figures"
DATA = HERE.parent / "data"            # derived tables from private records; not committed (see .gitignore)
ROOT = Path(os.environ.get("SFCC_DATA_ROOT", "/Volumes/Expansion/sfcc-label-data"))
FIGURES.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

COLORS = dict(ink="#0b0b0b", ink2="#52514e", muted="#8a8984", grid="#e4e3df", surface="#ffffff",
              thawed="#eb6834", transition="#1baf7a", frozen="#2a78d6")


def style():
    plt.rcParams.update({"figure.facecolor": COLORS["surface"], "axes.facecolor": COLORS["surface"],
                         "axes.edgecolor": COLORS["ink2"], "axes.labelcolor": COLORS["ink"],
                         "xtick.color": COLORS["ink2"], "ytick.color": COLORS["ink2"], "text.color": COLORS["ink"],
                         "font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": COLORS["grid"], "grid.linewidth": 0.6,
                         "savefig.dpi": 300})
