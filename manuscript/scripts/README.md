# Manuscript scripts

Code that produces every figure and number in `main.tex` from the `sfcc_label` package and the private data
volume (`SFCC_DATA_ROOT`, default `/Volumes/Expansion/sfcc-label-data`). Install with
`python -m pip install -e '.[classify,paper]'` from the repository root, then run from this folder:

| script | produces |
|---|---|
| `frozen_level_winters.py [workers]` | `../data/frozen_level_winters.csv` — winters with an observed frozen level (≈ 2.5 min) |
| `fig_frozen_fraction.py` | `../figures/fig_frozen_fraction.png` (needs the table above) |
| `fig_binning.py` | `../figures/fig_binning.png` — binning of the Kenaston EC02 2017–18 freezing leg |
| `fig_example_winters.py` | `../figures/fig_example_winters.png` — Kenaston EC06 2014–15 and James Bay BJ04 2020–21 |
| `winter_widths.py [workers]` | `../data/winter_widths.csv` — production per-winter fit of every topsoil sensor (≈ 1 h) |
| `fig_widths.py` | `../figures/fig_widths.png` — curve widths and the slow-freeze cut-off (needs the table above) |
| `table_biome_soil.py` | `../tables/biome_soil.tex` — sites, sensors, main ESA CCI cover and SoilGrids properties per RESOLVE biome |
| `fig_grouping.py` | `../figures/fig_grouping.png` — leave-one-site-out example (James Bay BJ04) and errors per grouping (needs `grouping_test.py`) |
| `grouping_test.py` | `../data/grouping_test.csv` — leave-one-site-out test of fallback groupings (needs `winter_widths.csv`) |
| `fig_levels.py` | `../figures/fig_levels.png` — unfrozen and frozen levels for Kenaston EC06 2014–15, UG21 2014–15 and James Bay BJ04 2020–21 |

`../data/` holds derived tables from records that cannot be redistributed and is not committed.
