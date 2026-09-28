"""Winters with an observed (clean) frozen permittivity level, used to derive the frozen-fraction prior.

A winter qualifies when sfcc_label.classify.observed_frozen_level finds its frozen level: the soil reaches -5 degC,
the coldest bins form a flat run (within 10 % of the observed drop, spanning >= 0.5 degC), the drop exceeds 3
permittivity units and the frozen level is at least 2.
Reads the private data volume; writes manuscript/data/frozen_level_winters.csv.
Run: python manuscript/scripts/frozen_level_winters.py [workers]
"""
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from common import DATA, ROOT
from sfcc_label import classify as c

S = c.Settings()


def sensor_winters(row):
    try:
        frame = c._sensor_input(row, ROOT / "standardized", ROOT / "flags")
    except (OSError, ValueError, KeyError):
        return []
    pairs = frame.dropna()
    if pairs.empty:
        return []
    step = c.native_step_hours(pairs.index)
    min_day, min_n = c.readings_per_day(step, S.day_fit_share), (S.min_bin_readings if step <= 1.5 else 2)
    out = []
    for fyear, rows in frame.groupby(c.freeze_year(frame.index)):
        half = c.freezing_half(rows, int(fyear), min_day, S)
        if half is None:
            continue
        bins = c.bin_medians(half, S, min_n)
        g_unf = c.unfrozen_level(bins, S)
        g_fr = c.observed_frozen_level(bins, g_unf, S)
        if g_fr is None:
            continue
        out.append(dict(sensor_id=row["sensor_id"], source=row["source"], network=row.get("network"),
                        depth_cm=row.get("depth_cm"), depth_from_cm=row.get("depth_from_cm"),
                        depth_to_cm=row.get("depth_to_cm"), latitude=row["latitude"], longitude=row["longitude"],
                        fyear=int(fyear), eps_unfrozen=g_unf**2, eps_frozen=g_fr**2))
    return out


if __name__ == "__main__":
    cat = pd.read_csv(ROOT / "metadata/catalog.csv", low_memory=False)
    pairing = pd.read_csv(ROOT / "metadata/ismn_pairing.csv")
    amf = pd.read_csv(ROOT / "metadata/ameriflux_pairing.csv")
    wet = set(pairing.loc[pairing.pairing_method.isin(["same_instrument", "same_position", "sole_at_depth"]), "sensor_id"])
    wet |= set(amf.loc[amf.moisture_column.notna(), "sensor_id"])
    wet |= set(cat.sensor_id[cat.source.isin(["local", "tvc_hydraprobe", "chapleau", "berms", "tvc_boike"])])
    rows = cat[cat.sensor_id.isin(wet)].to_dict("records")
    with ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 8) as pool:
        winters = [w for ws in pool.map(sensor_winters, rows, chunksize=8) for w in ws]
    out = pd.DataFrame(winters)
    out["frozen_fraction"] = out.eps_frozen / out.eps_unfrozen
    out["depth_class"] = [c.depth_class(*d) for d in zip(out.depth_cm, out.depth_from_cm, out.depth_to_cm)]
    out.to_csv(DATA / "frozen_level_winters.csv", index=False)
    print(len(out), "winters,", out.sensor_id.nunique(), "sensors;", (out.depth_class == "topsoil").sum(), "topsoil")
