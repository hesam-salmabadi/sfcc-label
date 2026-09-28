# ESSD manuscript draft

Working title: **A harmonised in situ soil temperature and moisture dataset for Northern Hemisphere soil freeze--thaw studies**.

The target is an *Earth System Science Data* (ESSD) data description article. `main.tex` uses the official Copernicus LaTeX package, version 7.16 (3 September 2026), downloaded from [Copernicus manuscript preparation](https://publications.copernicus.org/for_authors/manuscript_preparation.html). `template.tex` and the class/style files are the unchanged upstream package for reference.

Build locally with `latexmk -pdf main.tex` from this directory. Build artifacts are ignored by `manuscript/.gitignore`.

This is a starting draft. The concise Data and metadata section summarizes [`docs/manuscript_data_section.md`](../docs/manuscript_data_section.md) and the full [`docs/data_processing_record.md`](../docs/data_processing_record.md). Its table and diagram describe the working collection as of 2026-09-27. Confirm author order, affiliations, correspondence email, contributions, funding, and competing interests with the co-authors.

## ESSD release dependency

ESSD requires the described data product to be accessible for review in a suitable repository and ultimately persistently identified and openly reusable. The current collection contains ISMN records that cannot be redistributed and partner records with unresolved release status. Define and archive the releasable product, document exclusions and source access paths, and add a data citation or review link before submission. The article also needs a dedicated evaluation of data quality, uncertainty, or plausibility.
