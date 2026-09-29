import math

import pytest

shapely = pytest.importorskip("shapely")

from sfcc_label.biome import assign_ecoregions


def test_point_inside_and_near_polygon():
    from shapely.geometry import box
    geoms = [box(0, 50, 10, 60), box(10, 50, 20, 60)]
    attrs = [{"BIOME_NAME": "Boreal Forests/Taiga"}, {"BIOME_NAME": "Tundra"}]
    out = assign_ecoregions([(5, 55), (15, 55), (20.02, 55), (25, 55)], geoms, attrs)
    assert out[0] == (attrs[0], 0.0) and out[1] == (attrs[1], 0.0)
    assert out[2][0] is attrs[1] and 0 < out[2][1] < 5000
    assert out[3][0] is None and math.isnan(out[3][1])
