# Chapleau workbook clock decision (2026-09-29)

The four Chelene plot workbooks in `/Volumes/Expansion/UQAM/Chelene` do not
state a time zone for `Data.timestamp`. Their `ReadMe` sheets call it the
date and time of measurement. The accompanying
`Soil_moisture_data_documentation.docx` mentions 16:00 local standard time
for a fire-weather index, but does not define the soil logger clock. The
`CR1000_asp3_Table1.dat` header likewise has no time-zone field.

The active import **assumes fixed Ontario standard time, UTC−5 throughout the
year**. This is an inference rather than a publisher declaration.

Evidence:

1. All four workbooks include a 02:00 measurement on Ontario's spring
   daylight-saving change dates, and only one 01:00 on the autumn change
   dates. The displayed clock therefore continues hourly through those
   changes. This favors a fixed clock over `America/Toronto` with daylight
   saving.
2. For June–August 2018–2021, mean 6 cm soil temperature peaks at workbook
   hours 18 (aspen), 19 (mixedwood), 15 (jack pine), and 15 (black spruce).
   Its minima are at 8, 9, 7, and 7, respectively. Interpreting these hours
   as UTC would put several shallow-soil peaks before or near solar noon at
   Chapleau. A local clock puts the peaks in the afternoon or evening.
3. Combined, the daily cycle and clock-change continuity favor fixed local
   standard time over UTC or daylight-saving local time. They do not prove
   the logger setting; provider confirmation would supersede this assumption.

The importer adds five hours to each workbook timestamp and records the
assumption in `metadata/chapleau_context.csv` and
`metadata/chapleau_sensors.csv`. The 60 active streams were rebuilt from all
four workbooks and checked against 108 real source fields across all streams,
with zero mismatches. The former `America/Toronto` import is recoverable at
`archive/chapleau_toronto_dst_20260929`, including its metadata. Relative to
that import, the fixed-clock version retains 80 additional temperature hours
and 303 additional moisture hours that had been dropped at daylight-saving
transitions.
