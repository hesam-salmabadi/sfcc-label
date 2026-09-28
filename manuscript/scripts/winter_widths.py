"""Fit every topsoil winter with the production settings and record its curve width T_on - T_fr.

Writes ../data/winter_widths.csv (one row per fitted winter) used by fig_widths.py. Only the per-winter fit is
run (bootstrap included); pooling, the slow-freeze rule and hourly probabilities are not applied.
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from common import DATA, ROOT
import sfcc_label.classify as c

S = c.Settings()


def sensor_widths(row):
    try:
        fit = c.fit_sensor(row["sensor_id"], c._sensor_input(row, ROOT / "standardized", ROOT / "flags"), S)
    except (OSError, ValueError, KeyError):
        return []
    return [dict(sensor_id=row["sensor_id"], source=row["source"], network=row.get("network"), fyear=w.fyear,
                 status=w.status, frozen_level_seen=w.frozen_level_seen, coldest_c=w.coldest_c, t_on=w.t_on, t_fr=w.t_fr,
                 eps_unfrozen=w.eps_unfrozen, eps_frozen=w.eps_frozen) for w in fit.winters.values()]


if __name__ == "__main__":
    cat = pd.read_csv(ROOT / "metadata/catalog.csv", low_memory=False)
    cat = cat[[c.depth_class(r["depth_cm"], r["depth_from_cm"], r["depth_to_cm"]) == "topsoil"
               for r in cat.to_dict("records")]]
    with ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 8) as pool:
        out = pd.DataFrame([w for ws in pool.map(sensor_widths, cat.to_dict("records"), chunksize=4) for w in ws])
    out["width_c"] = out.t_on - out.t_fr
    out.to_csv(DATA / "winter_widths.csv", index=False)
    print(len(out), "winters,", (out.status == "fitted").sum(), "fitted,",
          ((out.status == "fitted") & out.frozen_level_seen).sum(), "fitted with the frozen level seen")
