"""Coarse land/water mask for synthetic point generation.

Synthetic customers and markets are scattered around their depot, which drops a
large share of coastal and Great Lakes stops into open water. A full coastline
dataset would be overkill here, so this module approximates the continental US
with a low-resolution outline plus the five Great Lakes.

The mask is deliberately conservative: it is meant to catch obvious water, not to
resolve every inlet, island, or river. Callers should treat a positive result as
"worth nudging inland" rather than a precise shoreline test.
"""

from __future__ import annotations

Point = tuple[float, float]

# Low-resolution continental US outline, ordered along the border and coast.
# Vertices are (lat, lng).
_CONUS_OUTLINE: tuple[Point, ...] = (
    (48.4, -124.7),
    (46.5, -124.1),
    (44.0, -124.1),
    (41.8, -124.2),
    (39.0, -123.7),
    (37.0, -122.4),
    (35.4, -120.9),
    (34.4, -119.7),
    (33.7, -118.2),
    (32.6, -117.1),
    (32.5, -114.8),
    (31.3, -111.0),
    (31.3, -108.2),
    (31.8, -106.5),
    (31.8, -103.0),
    (29.5, -101.2),
    (26.0, -97.5),
    (27.0, -95.0),
    (29.7, -93.8),
    (29.2, -90.1),
    (30.3, -88.0),
    (30.4, -86.5),
    (29.0, -83.0),
    (27.5, -82.7),
    (25.2, -81.0),
    (26.5, -80.0),
    (28.5, -80.6),
    (30.7, -81.5),
    (32.0, -80.9),
    (33.5, -78.0),
    (35.2, -75.5),
    (36.5, -75.9),
    (37.5, -75.5),
    (38.5, -75.0),
    (39.5, -74.2),
    (40.5, -74.0),
    (41.0, -72.0),
    (41.5, -70.0),
    (42.0, -70.2),
    (42.8, -70.8),
    (43.5, -70.3),
    (44.5, -67.5),
    (45.0, -67.0),
    (45.5, -67.5),
    (47.0, -68.0),
    (47.3, -69.0),
    (45.5, -71.0),
    (45.0, -74.5),
    (44.0, -76.5),
    (43.5, -79.0),
    (42.6, -80.1),
    (42.1, -81.5),
    (41.95, -82.5),
    (42.05, -83.05),
    (42.35, -82.95),
    (42.62, -82.75),
    (42.97, -82.42),
    (44.0, -82.6),
    (45.0, -83.4),
    (46.0, -84.3),
    (46.5, -84.5),
    (47.5, -85.5),
    (48.0, -89.0),
    (48.2, -89.5),
    (48.0, -95.0),
    (49.0, -95.0),
    (49.0, -123.0),
)

# Great Lakes, kept slightly inside the shoreline so shoreline cities such as
# Chicago, Milwaukee, Cleveland, and Detroit stay classified as land.
_GREAT_LAKES: tuple[tuple[Point, ...], ...] = (
    # Lake Michigan
    (
        (41.62, -87.10),
        (41.75, -87.52),
        (42.05, -87.68),
        (42.50, -87.78),
        (43.00, -87.85),
        (43.55, -87.75),
        (44.20, -87.35),
        (44.80, -86.90),
        (45.30, -86.30),
        (45.80, -85.30),
        (45.95, -84.90),
        (45.75, -84.60),
        (45.30, -85.00),
        (44.60, -85.55),
        (44.00, -86.25),
        (43.50, -86.45),
        (43.00, -86.30),
        (42.50, -86.25),
        (42.00, -86.45),
        (41.72, -86.90),
    ),
    # Lake Superior
    (
        (46.60, -92.10),
        (46.70, -90.60),
        (46.90, -89.20),
        (47.30, -88.00),
        (47.55, -86.60),
        (48.20, -86.60),
        (48.75, -88.40),
        (48.85, -90.60),
        (48.20, -92.00),
        (47.40, -92.10),
    ),
    # Lake Huron
    (
        (43.05, -82.55),
        (43.60, -82.55),
        (44.00, -83.05),
        (44.50, -83.45),
        (45.00, -83.90),
        (45.80, -84.55),
        (46.00, -84.10),
        (45.30, -83.30),
        (44.60, -82.90),
        (43.90, -82.45),
        (43.30, -82.20),
    ),
    # Lake Erie
    (
        (41.50, -82.55),
        (41.55, -83.55),
        (41.75, -83.85),
        (42.05, -83.20),
        (42.35, -82.45),
        (42.60, -81.30),
        (42.85, -79.75),
        (42.50, -78.95),
        (42.20, -80.05),
        (41.90, -81.30),
        (41.60, -82.05),
    ),
    # Lake Ontario
    (
        (43.20, -79.80),
        (43.30, -79.00),
        (43.40, -78.00),
        (43.30, -76.55),
        (43.90, -76.55),
        (44.10, -77.50),
        (44.00, -78.80),
        (43.55, -79.30),
        (43.30, -79.70),
    ),
)


# Coarse populated-belt outline for Canada. Hudson Bay and the far north are
# approximated rather than modelled.
_CANADA_OUTLINE: tuple[Point, ...] = (
    (49.10, -123.20),
    (49.00, -114.00),
    (49.00, -104.00),
    (49.00, -95.20),
    (48.00, -89.50),
    (46.50, -84.50),
    (45.30, -83.00),
    (44.50, -80.50),
    (43.00, -79.20),
    (44.00, -76.50),
    (45.00, -74.50),
    (45.20, -71.50),
    (47.30, -69.00),
    (47.30, -66.00),
    (45.00, -64.00),
    (46.00, -60.00),
    (50.00, -60.00),
    (55.00, -64.00),
    (60.00, -70.00),
    (62.00, -85.00),
    (60.00, -100.00),
    (60.00, -115.00),
    (58.00, -125.00),
    (54.50, -130.50),
    (51.50, -127.50),
)

# Coarse mainland Mexico outline; the Gulf of California is treated as land
# because no depot sits near it.
_MEXICO_OUTLINE: tuple[Point, ...] = (
    (14.60, -92.30),
    (16.00, -95.20),
    (17.50, -101.00),
    (19.50, -105.50),
    (21.50, -106.50),
    (23.50, -109.00),
    (25.50, -109.50),
    (29.00, -111.00),
    (32.50, -114.80),
    (31.30, -111.00),
    (31.30, -108.20),
    (31.80, -106.50),
    (31.80, -103.00),
    (29.50, -101.20),
    (26.00, -97.50),
    (23.00, -97.80),
    (21.50, -97.50),
    (19.50, -96.40),
    (18.50, -94.50),
    (17.50, -92.00),
)

_LAND_POLYGONS: tuple[tuple[Point, ...], ...] = (
    _CONUS_OUTLINE,
    _CANADA_OUTLINE,
    _MEXICO_OUTLINE,
)


def is_on_water(lat: float, lng: float) -> bool:
    """True when a coordinate looks like open water or a Great Lake."""
    for lake in _GREAT_LAKES:
        if _point_in_polygon(lat, lng, lake):
            return True
    return not any(_point_in_polygon(lat, lng, land) for land in _LAND_POLYGONS)


def pull_to_land(
    lat: float,
    lng: float,
    anchor_lat: float,
    anchor_lng: float,
    *,
    steps: int = 24,
) -> tuple[float, float]:
    """Slide a point toward its anchor until it lands on shore.

    The anchor is the depot the point was generated around. The random draw is
    left untouched beyond this correction so seeded datasets stay reproducible.
    """
    if not is_on_water(lat, lng):
        return lat, lng
    if is_on_water(anchor_lat, anchor_lng):
        # The anchor is not trustworthy, so leave the point where it was drawn.
        return lat, lng

    # Mirror across the depot first: coastal depots push their water draws
    # offshore, so the opposite bearing is usually inland and keeps the same
    # service radius.
    mirrored_lat = anchor_lat - (lat - anchor_lat)
    mirrored_lng = anchor_lng - (lng - anchor_lng)
    if not is_on_water(mirrored_lat, mirrored_lng):
        return mirrored_lat, mirrored_lng

    last_land = 0.0
    for step in range(1, steps + 1):
        t = step / steps
        if is_on_water(
            anchor_lat + (lat - anchor_lat) * t,
            anchor_lng + (lng - anchor_lng) * t,
        ):
            break
        last_land = t

    if last_land <= 0.0:
        return anchor_lat, anchor_lng

    # Keep the point just inside the shoreline rather than resting on it.
    t = max(0.05, last_land * 0.92)
    return (
        anchor_lat + (lat - anchor_lat) * t,
        anchor_lng + (lng - anchor_lng) * t,
    )


def _point_in_polygon(lat: float, lng: float, polygon: tuple[Point, ...]) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        lat_a, lng_a = polygon[index]
        lat_b, lng_b = polygon[(index + 1) % count]
        if (lat_a > lat) != (lat_b > lat):
            ratio = (lat - lat_a) / (lat_b - lat_a)
            if lng < lng_a + ratio * (lng_b - lng_a):
                inside = not inside
    return inside
