# ABoVE Chelene import audit (2026-09-29)

The three source folders are under `/Volumes/Expansion/UQAM/Chelene`.
The two temperature releases are separate active sources: ORNL DAAC 1767
(`ak_profiles`) and ORNL DAAC 1680 (`usarray_ground`). No source values from
their shared sites are blended.

| Release | Source files | Active source files | Active streams | Status |
| --- | ---: | ---: | ---: | --- |
| 1767 Soil Temperature Profiles | 17 | 17 | 88 | Published under `standardized/ak_profiles` |
| 1680 USArray Ground Temperature | 64 | 54 | 252 | Published under `standardized/usarray_ground`; 10 files excluded |
| 2123 Alaska/Alberta Soil Moisture | 4 CSVs | 0 | 0 | UTC conversion held for missing clock definition |

The 1767 and 1680 dataset guides explicitly label `date_time` AKST. The
importers convert AKST to UTC by adding nine hours and round to the nearest
UTC hour. The 1767 source has 136 malformed timestamp rows across nine files;
these are counted in `metadata/ak_profiles_import_status.csv` and skipped.
All 88 active 1767 streams and all 252 active 1680 streams had their first
valid source value independently checked against the standardized UTC row,
with zero mismatches. Copied observation and metadata files were verified
against their staged counterparts by SHA-256.

Ten 1680 files contain two distinct readings both labeled `2018-11-04 1:00,AKST`,
the local fall daylight saving transition. The fixed AKST label cannot
distinguish those two elapsed hours. The importer excludes the entire affected
files when `--skip-ambiguous-clock-files` is used, records the reason in
`metadata/usarray_ground_import_status.csv`, and otherwise raises an error.
The excluded sites are MRA-1 through MRA-4, SHA-2 through SHA-4, and WS1
through WS3. Their UTC values require clarification from the source publisher.

The 2123 guide and its local copy describe `time_stamp` only as date and time
of measurement. The calibration supplement, four CSVs, and official dataset
page provide no explicit UTC offset or daylight saving rule for the Alaska
and Alberta loggers. A provisional conversion exists only under
`/private/tmp/above_moisture_provisional_20260928`; it is not active data.
Twenty real staged sensors were checked independently against the source CSVs
for temperature, moisture, and raw period values (60 field checks, zero
mismatches). This verifies the value extraction and unit conversion only;
it does not establish the time zone.
The importer requires separately supplied Alaska and Alberta UTC offsets with
evidence before it can write standardized UTC files. Source logger IDs lacking
probe metadata will be reported and excluded when that import runs.

Official guides:

- [ORNL DAAC 1767](https://daac.ornl.gov/ABOVE/guides/Soil_Temperature_Profiles_AK.html)
- [ORNL DAAC 1680](https://daac.ornl.gov/ABOVE/guides/USArray_Ground_Temperature.html)
- [ORNL DAAC 2123](https://daac.ornl.gov/SOILS/guides/Soil_Moisture_Alaska_Alberta.html)
