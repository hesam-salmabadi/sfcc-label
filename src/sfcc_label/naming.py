"""Consistent sensor identifiers: ``<src>_<site>_<depth>_<tag>``.

Every part is lowercase ``a-z``, ``0-9`` or ``-``, so an id always splits into
exactly four parts on ``_``. The id is also the standardized file stem.

- src: short code of the source (``SOURCE_CODES``)
- site: site code, e.g. ``bs01``; ISMN uses ``network-station``
- depth: zero-padded cm, ``005cm``; decimals use ``p`` (``002p5cm``); an
  interval is ``000-015cm``; unknown depth is ``nodepth``
- tag: separates sensors at one site and depth (``h1v1r1``, ``pit2``, ``t``);
  ``s1`` when the source has a single sensor there
"""

from __future__ import annotations

import math
import re

SOURCE_CODES = {
    "ameriflux": "amf", "berms": "berms", "cambridge_bay": "cbay", "chapleau": "chap",
    "dryden": "dryden", "ismn": "ismn", "local": "local", "nrcan_ibutton": "nrcan",
    "st_marthe_maurice": "smm", "tvc_boike": "tvcb", "tvc_hydraprobe": "tvch",
    "james_bay": "jbay", "montmorency": "mont", "kuujjuarapik": "kuuj",
}
SENSOR_ID = re.compile(r"^[a-z0-9-]+(_[a-z0-9-]+){3}$")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _number(value: float) -> str:
    value = round(value, 2)
    whole = int(value)
    fraction = f"{value - whole:.2f}"[2:].rstrip("0")
    return f"{whole:03d}" + (f"p{fraction}" if fraction else "")


def _missing(value: float | None) -> bool:
    return value is None or math.isnan(value)


def depth_token(top_cm: float | None, bottom_cm: float | None = None) -> str:
    """Point depth when both ends agree (or only one is known), else an interval."""
    if bottom_cm is None and not _missing(top_cm):
        bottom_cm = top_cm
    if _missing(top_cm) and _missing(bottom_cm):
        return "nodepth"
    if _missing(top_cm) or _missing(bottom_cm) or round(top_cm, 2) == round(bottom_cm, 2):
        return _number(bottom_cm if _missing(top_cm) else top_cm) + "cm"
    return f"{_number(top_cm)}-{_number(bottom_cm)}cm"


def sensor_id(source: str, site: str, top_cm: float | None, bottom_cm: float | None = None,
              tag: str = "s1") -> str:
    ident = "_".join((SOURCE_CODES[source], slug(site), depth_token(top_cm, bottom_cm), slug(tag)))
    if not SENSOR_ID.match(ident):
        raise ValueError(f"invalid sensor id {ident!r}")
    return ident


def ameriflux_tag(column: str) -> str:
    """``TS_1_2_3`` -> ``h1v2r3``; ``TS_PI_1`` -> ``pi1``; ``TS_2`` -> ``i2``; ``TS`` -> ``s1``."""
    if match := re.fullmatch(r"TS_(\d+)_(\d+)_(\d+)", column):
        return "h{}v{}r{}".format(*match.groups())
    if match := re.fullmatch(r"TS_PI_(\d+)", column):
        return f"pi{match.group(1)}"
    if match := re.fullmatch(r"TS_(\d+)", column):
        return f"i{match.group(1)}"
    if column == "TS":
        return "s1"
    raise ValueError(f"unrecognized AmeriFlux soil temperature column {column!r}")
