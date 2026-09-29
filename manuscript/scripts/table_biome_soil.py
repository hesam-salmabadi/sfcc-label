"""Table: sites and sensors per RESOLVE biome, their main ESA CCI cover classes and SoilGrids soil properties.

Biome from RESOLVE Ecoregions 2017 (metadata/sensor_biome.csv); cover is the ESA CCI class of the sensor's 300 m
pixel; soil properties are the SoilGrids layer matched to each sensor's depth. Writes ../tables/biome_soil.tex.
"""
import pandas as pd

from common import HERE, ROOT
from sfcc_label.classify import depth_class
from sfcc_label.landcover_cci import CCI_NAMES

M = ROOT / "metadata"
cat = pd.read_csv(M / "catalog.csv", low_memory=False)
lc = pd.read_csv(M / "sensor_landcover_cci.csv", usecols=["sensor_id", "cci_class"]).drop_duplicates("sensor_id")
soil = pd.read_csv(M / "sensor_soil.csv").drop_duplicates("sensor_id")
bio = pd.read_csv(M / "sensor_biome.csv", usecols=["sensor_id", "biome"])
d = (cat[["sensor_id", "source", "site_id", "depth_cm", "depth_from_cm", "depth_to_cm"]]
     .merge(lc, on="sensor_id", how="left").merge(bio, on="sensor_id", how="left")
     .merge(soil[["sensor_id", "clay_pct", "sand_pct", "soc_g_kg", "bdod_g_cm3"]], on="sensor_id", how="left"))
d["site"] = d.source + "|" + d.site_id.astype(str)
d["topsoil"] = [depth_class(*x) == "topsoil" for x in zip(d.depth_cm, d.depth_from_cm, d.depth_to_cm)]
d["cover"] = d.cci_class.map(lambda c: CCI_NAMES.get(int(c), str(c)) if pd.notna(c) else "unknown")


def q(s, fmt):
    s = s.dropna()
    return "--" if s.empty else f"{s.median():{fmt}} ({s.quantile(0.1):{fmt}}--{s.quantile(0.9):{fmt}})"


rows = []
for biome, g in sorted(d.groupby("biome"), key=lambda x: -len(x[1])):
    cov = g.cover.value_counts(normalize=True)
    top = "; ".join(f"{k} {v:.0%}" for k, v in cov.head(2).items())
    rows.append(dict(biome=biome, sites=g.site.nunique(), sensors=len(g), top=int(g.topsoil.sum()), cover=top,
                     clay=q(g.clay_pct, ".0f"), sand=q(g.sand_pct, ".0f"), soc=q(g.soc_g_kg, ".0f"),
                     bd=q(g.bdod_g_cm3, ".2f")))
    print(rows[-1])
print("all:", d.site.nunique(), "sites,", len(d), "sensors,", int(d.topsoil.sum()), "topsoil")

esc = lambda t: t.replace("%", r"\%").replace("&", r"\&")
lines = [r"\begin{table*}[t]",
         r"\caption{Sites and sensors by RESOLVE Ecoregions 2017 biome \citep{dinerstein2017}, with the two most common "
         r"ESA CCI land-cover classes of the sensors' 300\,m pixels and SoilGrids 2.0 properties of the layer matched to "
         r"each sensor's depth, as median (10th--90th percentile). Topsoil: $2.5 < z < 7.5$\,cm or a 0--5\,cm "
         r"integrating probe.}",
         r"\label{tab:biome-soil}", r"\centering", r"\scriptsize",
         r"\begin{tabular}{p{3.2cm}rrrp{4.2cm}llll}", r"\tophline",
         r"Biome & Sites & Sensors & Topsoil & Main land cover (ESA CCI) & Clay (\%) & Sand (\%) & SOC (g\,kg$^{-1}$) & Bulk density (g\,cm$^{-3}$) \\",
         r"\middlehline"]
for r in rows:
    lines.append(f"{esc(r['biome'])} & {r['sites']:,} & {r['sensors']:,} & {r['top']:,} & {esc(r['cover'])} & "
                 f"{r['clay']} & {r['sand']} & {r['soc']} & {r['bd']} \\\\")
lines += [r"\bottomhline", r"\end{tabular}", r"\end{table*}"]
(HERE.parent / "tables" / "biome_soil.tex").write_text("\n".join(lines) + "\n")
