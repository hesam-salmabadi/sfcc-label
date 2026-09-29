"""Which grouping best predicts a topsoil sensor's thresholds at a site it has not seen? Leave-one-site-out.

Uses the fitted topsoil winters of data/winter_widths.csv (winters wider than the slow-freeze cut-off are left
out, since their T_fr is replaced). For every site, groups are formed from all other sites (at least three
winters per group, as in the fallback chain), the group median predicts the left-out site's winters, and a
missing group falls back to the global median. Writes ../data/grouping_test.csv (summary),
grouping_errors.csv (one row per winter and grouping) and grouping_winters.csv (the winters used).
"""
import numpy as np
import pandas as pd

from common import DATA, ROOT
from sfcc_label.classify import catalog_probes

M = ROOT / "metadata"
w = pd.read_csv(DATA / "winter_widths.csv")
w = w[w.status == "fitted"]
cut = w[w.frozen_level_seen].width_c.quantile(0.9)
w = w[w.width_c <= cut].copy()
cat = pd.read_csv(M / "catalog.csv", low_memory=False)
cat = cat[cat.sensor_id.isin(w.sensor_id)].copy()
cat["probe"] = catalog_probes(cat, pd.read_csv(M / "ismn_pairing.csv"))
lc = pd.read_csv(M / "sensor_landcover_cci.csv", usecols=["sensor_id", "cci_class", "sensor_class"]).drop_duplicates("sensor_id")
soil = pd.read_csv(M / "sensor_soil.csv", usecols=["sensor_id", "texture_class_usda"]).drop_duplicates("sensor_id")
bio = pd.read_csv(M / "sensor_biome.csv", usecols=["sensor_id", "biome"])
d = (w.merge(cat[["sensor_id", "site_id", "probe"]], on="sensor_id").merge(lc, on="sensor_id", how="left")
     .merge(soil, on="sensor_id", how="left").merge(bio, on="sensor_id", how="left"))
d["site"] = d.source + "|" + d.site_id.astype(str)
d["network"] = d.network.fillna(d.source)
d["cci_detailed"] = d.cci_class.astype("Int64").astype(str)
for a, b in (("sensor_class", "texture_class_usda"), ("biome", "texture_class_usda"), ("biome", "sensor_class"),
             ("biome", "cci_detailed"), ("network", "probe")):
    d[f"{a} x {b}"] = d[a].astype(str) + "|" + d[b].astype(str)
d["biome x land cover x texture"] = d["biome x sensor_class"] + "|" + d.texture_class_usda.astype(str)
GROUPS = {"global": None, "land cover (6 classes)": "sensor_class", "CCI detailed class": "cci_detailed",
          "biome": "biome", "texture": "texture_class_usda", "land cover x texture": "sensor_class x texture_class_usda",
          "biome x texture": "biome x texture_class_usda", "biome x land cover": "biome x sensor_class",
          "biome x CCI detailed": "biome x cci_detailed", "biome x land cover x texture": "biome x land cover x texture",
          "network x probe": "network x probe"}
TARGETS = {"t_on": "T_on", "t_fr": "T_fr", "width_c": "width"}
print("winters", len(d), "sensors", d.sensor_id.nunique(), "sites", d.site.nunique())
rows, long = [], []
for name, col in GROUPS.items():
    row = {"grouping": name}
    for tgt, label in TARGETS.items():
        err, hit = [], 0
        for s, te in d.groupby("site"):
            tr = d[d.site != s]
            glob = tr[tgt].median()
            if col is None:
                pred = np.full(len(te), glob)
            else:
                med = tr.groupby(col)[tgt].agg(["median", "size"])
                pred = te[col].map(med.loc[med["size"] >= 3, "median"])
                hit += int(pred.notna().sum())
                pred = pred.fillna(glob).values
            e = np.abs(pred - te[tgt].values)
            err += list(e)
            long += [dict(grouping=name, target=label, sensor_id=i, fyear=y, error=v)
                     for i, y, v in zip(te.sensor_id, te.fyear, e)]
        row[f"{label} MAE"] = round(float(np.median(err)), 3)
        if tgt == "t_on":
            row["share matched"] = round(hit / len(d), 2) if col else 1.0
    rows.append(row)
out = pd.DataFrame(rows)
print(out.to_string(index=False))
out.to_csv(DATA / "grouping_test.csv", index=False)
pd.DataFrame(long).to_csv(DATA / "grouping_errors.csv", index=False)
d.to_csv(DATA / "grouping_winters.csv", index=False)
