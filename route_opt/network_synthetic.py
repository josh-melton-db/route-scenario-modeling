from __future__ import annotations
from functools import lru_cache


@lru_cache(maxsize=1)
def national_dataset_cached(seed: int = 42) -> dict[str, list]:
    """Single shared national dataset for overview, scenarios, and depot baselines."""
    from .synthetic import generate_depots

    return generate_national_network_dataset(generate_depots(), seed=seed)  # type: ignore[return-value]



import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone

from .matrix import haversine_miles
from .network_schemas import (
    NETWORK_TABLE_MODELS,
    BaselineNetworkFlowDaily,
    DemandPlanDaily,
    ExternalPlanVersion,
    FacilityCapacityDaily,
    FacilityHierarchy,
    LaneCapacityDaily,
    NetworkCustomer,
    NetworkFacility,
    NetworkLane,
    NetworkMarket,
    NetworkModel,
    NetworkRegion,
)

NETWORK_SOURCE_SYSTEM = "synthetic_upstream_planning"
DEFAULT_NETWORK_HORIZON_START = date(2026, 9, 21)
DEFAULT_NETWORK_HORIZON_DAYS = 7
GREAT_LAKES_REGION_ID = "REGION_GREAT_LAKES"
DEMAND_PLAN_VERSION_ID = "DEMAND_GL_BASELINE_V1"
CAPACITY_PLAN_VERSION_ID = "CAPACITY_GL_BASELINE_V1"
NATIONAL_DEMAND_PLAN_VERSION_ID = "DEMAND_US_BASELINE_V1"
NATIONAL_CAPACITY_PLAN_VERSION_ID = "CAPACITY_US_BASELINE_V1"
SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID = "CAPACITY_US_SE_CONSTRAINED_V2"

_DISTRIBUTION_CENTERS = (
    (
        "DC_GREAT_LAKES_EAST",
        "Detroit Distribution Center",
        42.2124,
        -83.3534,
    ),
    (
        "DC_GREAT_LAKES_WEST",
        "Chicago Distribution Center",
        41.8781,
        -87.6298,
    ),
)

_EXISTING_DEPOT_PARENTS = {
    "DPT_NORTH": "DC_GREAT_LAKES_EAST",
    "DPT_CENTRAL": "DC_GREAT_LAKES_EAST",
    "DPT_WEST": "DC_GREAT_LAKES_WEST",
}

_ADDITIONAL_DEPOTS = (
    (
        "DPT_CLEVELAND",
        "Cleveland Depot",
        "DC_GREAT_LAKES_EAST",
        41.4993,
        -81.6944,
    ),
    (
        "DPT_CHICAGO",
        "Chicago Depot",
        "DC_GREAT_LAKES_WEST",
        41.8500,
        -87.6500,
    ),
    (
        "DPT_MILWAUKEE",
        "Milwaukee Depot",
        "DC_GREAT_LAKES_WEST",
        43.0389,
        -87.9065,
    ),
)

_ADDITIONAL_REGION_SPECS = (
    (
        "REGION_NORTHEAST",
        "Northeast",
        (
            (
                "DC_NORTHEAST_NEW_JERSEY",
                "New Jersey Distribution Center",
                40.7357,
                -74.1724,
                "America/New_York",
            ),
            (
                "DC_NORTHEAST_BOSTON",
                "Boston Distribution Center",
                42.3601,
                -71.0589,
                "America/New_York",
            ),
        ),
        (
            (
                "DPT_NE_PHILADELPHIA",
                "Philadelphia Depot",
                "DC_NORTHEAST_NEW_JERSEY",
                39.9526,
                -75.1652,
            ),
            (
                "DPT_NE_PITTSBURGH",
                "Pittsburgh Depot",
                "DC_NORTHEAST_NEW_JERSEY",
                40.4406,
                -79.9959,
            ),
            (
                "DPT_NE_BUFFALO",
                "Buffalo Depot",
                "DC_NORTHEAST_NEW_JERSEY",
                42.8864,
                -78.8784,
            ),
            (
                "DPT_NE_HARTFORD",
                "Hartford Depot",
                "DC_NORTHEAST_BOSTON",
                41.7658,
                -72.6734,
            ),
            (
                "DPT_NE_PORTLAND",
                "Portland Maine Depot",
                "DC_NORTHEAST_BOSTON",
                43.6591,
                -70.2568,
            ),
            (
                "DPT_NE_BOSTON",
                "Boston Depot",
                "DC_NORTHEAST_BOSTON",
                42.3473,
                -71.0826,
            ),
        ),
    ),
    (
        "REGION_SOUTHEAST",
        "Southeast",
        (
            (
                "DC_SOUTHEAST_ATLANTA",
                "Atlanta Distribution Center",
                33.7490,
                -84.3880,
                "America/New_York",
            ),
            (
                "DC_SOUTHEAST_CHARLOTTE",
                "Charlotte Distribution Center",
                35.2271,
                -80.8431,
                "America/New_York",
            ),
        ),
        (
            (
                "DPT_SE_NASHVILLE",
                "Nashville Depot",
                "DC_SOUTHEAST_ATLANTA",
                36.1627,
                -86.7816,
            ),
            (
                "DPT_SE_BIRMINGHAM",
                "Birmingham Depot",
                "DC_SOUTHEAST_ATLANTA",
                33.5186,
                -86.8104,
            ),
            (
                "DPT_SE_JACKSONVILLE",
                "Jacksonville Depot",
                "DC_SOUTHEAST_ATLANTA",
                30.3322,
                -81.6557,
            ),
            (
                "DPT_SE_RALEIGH",
                "Raleigh Depot",
                "DC_SOUTHEAST_CHARLOTTE",
                35.7796,
                -78.6382,
            ),
            (
                "DPT_SE_RICHMOND",
                "Richmond Depot",
                "DC_SOUTHEAST_CHARLOTTE",
                37.5407,
                -77.4360,
            ),
            (
                "DPT_SE_CHARLESTON",
                "Charleston Depot",
                "DC_SOUTHEAST_CHARLOTTE",
                32.7765,
                -79.9311,
            ),
        ),
    ),
    (
        "REGION_WEST",
        "West",
        (
            (
                "DC_WEST_LOS_ANGELES",
                "Los Angeles Distribution Center",
                34.0522,
                -118.2437,
                "America/Los_Angeles",
            ),
            (
                "DC_WEST_DENVER",
                "Denver Distribution Center",
                39.7392,
                -104.9903,
                "America/Denver",
            ),
        ),
        (
            (
                "DPT_WEST_SAN_DIEGO",
                "San Diego Depot",
                "DC_WEST_LOS_ANGELES",
                32.7157,
                -117.1611,
            ),
            (
                "DPT_WEST_PHOENIX",
                "Phoenix Depot",
                "DC_WEST_LOS_ANGELES",
                33.4484,
                -112.0740,
            ),
            (
                "DPT_WEST_LAS_VEGAS",
                "Las Vegas Depot",
                "DC_WEST_LOS_ANGELES",
                36.1699,
                -115.1398,
            ),
            (
                "DPT_WEST_SALT_LAKE",
                "Salt Lake City Depot",
                "DC_WEST_DENVER",
                40.7608,
                -111.8910,
            ),
            (
                "DPT_WEST_PORTLAND",
                "Portland Depot",
                "DC_WEST_DENVER",
                45.5152,
                -122.6784,
            ),
            (
                "DPT_WEST_SEATTLE",
                "Seattle Depot",
                "DC_WEST_DENVER",
                47.6062,
                -122.3321,
            ),
        ),
    ),
    (
        "REGION_TOLA",
        "TOLA",
        (
            (
                "DC_TOLA_DALLAS",
                "Dallas Distribution Center",
                32.7767,
                -96.7970,
                "America/Chicago",
            ),
            (
                "DC_TOLA_HOUSTON",
                "Houston Distribution Center",
                29.7604,
                -95.3698,
                "America/Chicago",
            ),
        ),
        (
            (
                "DPT_TOLA_DALLAS",
                "Dallas Depot",
                "DC_TOLA_DALLAS",
                32.8500,
                -96.8500,
            ),
            (
                "DPT_TOLA_OKLAHOMA",
                "Oklahoma City Depot",
                "DC_TOLA_DALLAS",
                35.4676,
                -97.5164,
            ),
            (
                "DPT_TOLA_LITTLE_ROCK",
                "Little Rock Depot",
                "DC_TOLA_DALLAS",
                34.7465,
                -92.2896,
            ),
            (
                "DPT_TOLA_HOUSTON",
                "Houston Depot",
                "DC_TOLA_HOUSTON",
                29.8200,
                -95.4200,
            ),
            (
                "DPT_TOLA_SAN_ANTONIO",
                "San Antonio Depot",
                "DC_TOLA_HOUSTON",
                29.4241,
                -98.4936,
            ),
            (
                "DPT_TOLA_NEW_ORLEANS",
                "New Orleans Depot",
                "DC_TOLA_HOUSTON",
                29.9511,
                -90.0715,
            ),
        ),
    ),
)

_WEEKDAY_MULTIPLIERS = (1.00, 1.07, 1.12, 0.98, 1.16, 0.72, 0.58)


def _rows(models: Sequence[NetworkModel]) -> list[dict[str, object]]:
    return [model.model_dump(mode="json") for model in models]


def _road_distance_miles(
    origin_lat: float,
    origin_lng: float,
    destination_lat: float,
    destination_lng: float,
) -> float:
    return round(
        haversine_miles(origin_lat, origin_lng, destination_lat, destination_lng)
        * 1.18,
        1,
    )


def _transit_minutes(distance_miles: float) -> int:
    return max(15, int(round(distance_miles / 45 * 60)))


def _capacity_for(volume: int, buffer_pct: float) -> int:
    return max(volume, int(math.ceil(volume * (1 + buffer_pct))))


def _build_facilities(
    existing_depots: Sequence[Mapping[str, object]],
) -> list[NetworkFacility]:
    by_id = {str(row["depot_id"]): row for row in existing_depots}
    missing = sorted(set(_EXISTING_DEPOT_PARENTS) - set(by_id))
    if missing:
        raise ValueError(
            "The canonical network requires the current route-planning depots: "
            + ", ".join(missing)
        )

    facilities = [
        NetworkFacility(
            facility_id=facility_id,
            facility_name=facility_name,
            facility_type="distribution_center",
            region_id=GREAT_LAKES_REGION_ID,
            lat=lat,
            lng=lng,
            timezone="America/Detroit" if facility_id.endswith("EAST") else "America/Chicago",
        )
        for facility_id, facility_name, lat, lng in _DISTRIBUTION_CENTERS
    ]

    for depot_id, parent_id in _EXISTING_DEPOT_PARENTS.items():
        depot = by_id[depot_id]
        facilities.append(
            NetworkFacility(
                facility_id=depot_id,
                facility_name=str(depot["depot_name"]),
                facility_type="depot",
                region_id=GREAT_LAKES_REGION_ID,
                parent_facility_id=parent_id,
                lat=float(depot["lat"]),
                lng=float(depot["lng"]),
                timezone="America/Detroit" if parent_id.endswith("EAST") else "America/Chicago",
            )
        )

    facilities.extend(
        NetworkFacility(
            facility_id=depot_id,
            facility_name=depot_name,
            facility_type="depot",
            region_id=GREAT_LAKES_REGION_ID,
            parent_facility_id=parent_id,
            lat=lat,
            lng=lng,
            timezone="America/Detroit" if parent_id.endswith("EAST") else "America/Chicago",
        )
        for depot_id, depot_name, parent_id, lat, lng in _ADDITIONAL_DEPOTS
    )
    return facilities


def _build_hierarchy(facilities: Sequence[NetworkFacility]) -> list[FacilityHierarchy]:
    rows: list[FacilityHierarchy] = []
    for facility in facilities:
        rows.append(
            FacilityHierarchy(
                ancestor_id=facility.region_id,
                ancestor_type="region",
                descendant_facility_id=facility.facility_id,
                relationship_type="region_contains",
                depth=1 if facility.facility_type == "distribution_center" else 2,
            )
        )
        if facility.parent_facility_id:
            rows.append(
                FacilityHierarchy(
                    ancestor_id=facility.parent_facility_id,
                    ancestor_type="facility",
                    descendant_facility_id=facility.facility_id,
                    relationship_type="distribution_center_serves",
                    depth=1,
                )
            )
    return rows


def _build_markets(facilities: Sequence[NetworkFacility]) -> list[NetworkMarket]:
    offsets = (
        (0.08, 0.11),
        (-0.07, 0.12),
        (0.10, -0.09),
        (-0.09, -0.10),
        (0.06, -0.13),
        (-0.11, 0.07),
    )
    return [
        NetworkMarket(
            market_id=f"MKT_{facility.facility_id.removeprefix('DPT_')}",
            market_name=f"{facility.facility_name.removesuffix(' Depot')} Market",
            region_id=facility.region_id,
            primary_depot_id=facility.facility_id,
            lat=round(facility.lat + offsets[index][0], 6),
            lng=round(facility.lng + offsets[index][1], 6),
        )
        for index, facility in enumerate(
            sorted(
                (row for row in facilities if row.facility_type == "depot"),
                key=lambda row: row.facility_id,
            )
        )
    ]


def _build_customers(
    facilities: Sequence[NetworkFacility],
    markets: Sequence[NetworkMarket],
    *,
    customers_per_depot: int,
    rng: random.Random,
    customer_id_prefix: str = "NET-CUST",
) -> tuple[list[NetworkCustomer], dict[str, int]]:
    if customers_per_depot < 1:
        raise ValueError("customers_per_depot must be at least 1.")

    markets_by_depot = {market.primary_depot_id: market for market in markets}
    customers: list[NetworkCustomer] = []
    base_demand: dict[str, int] = {}
    customer_number = 1
    for depot in sorted(
        (row for row in facilities if row.facility_type == "depot"),
        key=lambda row: row.facility_id,
    ):
        market = markets_by_depot[depot.facility_id]
        for local_number in range(1, customers_per_depot + 1):
            customer_id = f"{customer_id_prefix}-{customer_number:04d}"
            radius = rng.triangular(0.03, 0.45, 0.12)
            theta = rng.uniform(0, math.tau)
            tier_roll = rng.random()
            tier = (
                "strategic"
                if tier_roll < 0.12
                else "key"
                if tier_roll < 0.42
                else "standard"
            )
            tier_multiplier = {"strategic": 1.8, "key": 1.25, "standard": 0.85}[tier]
            depot_multiplier = 1.2 if depot.facility_id in {"DPT_NORTH", "DPT_CHICAGO"} else 1.0
            base_demand[customer_id] = max(
                20,
                int(round(rng.lognormvariate(4.2, 0.38) * tier_multiplier * depot_multiplier)),
            )
            customers.append(
                NetworkCustomer(
                    customer_id=customer_id,
                    customer_name=(
                        f"{depot.facility_name.removesuffix(' Depot')} "
                        f"Customer {local_number:02d}"
                    ),
                    customer_tier=tier,
                    region_id=depot.region_id,
                    distribution_center_id=str(depot.parent_facility_id),
                    depot_id=depot.facility_id,
                    market_id=market.market_id,
                    lat=round(depot.lat + radius * math.sin(theta) * 0.68, 6),
                    lng=round(depot.lng + radius * math.cos(theta), 6),
                )
            )
            customer_number += 1
    return customers, base_demand


def _lane(
    *,
    lane_id: str,
    lane_name: str,
    lane_type: str,
    origin: NetworkFacility,
    destination_id: str,
    destination_type: str,
    destination_lat: float,
    destination_lng: float,
) -> NetworkLane:
    distance = _road_distance_miles(
        origin.lat,
        origin.lng,
        destination_lat,
        destination_lng,
    )
    return NetworkLane(
        lane_id=lane_id,
        lane_name=lane_name,
        lane_type=lane_type,
        origin_endpoint_id=origin.facility_id,
        origin_endpoint_type="facility",
        destination_endpoint_id=destination_id,
        destination_endpoint_type=destination_type,
        distance_miles=distance,
        transit_minutes=_transit_minutes(distance),
    )


def _build_lanes(
    facilities: Sequence[NetworkFacility],
    markets: Sequence[NetworkMarket],
    customers: Sequence[NetworkCustomer],
) -> list[NetworkLane]:
    facilities_by_id = {row.facility_id: row for row in facilities}
    markets_by_depot = {row.primary_depot_id: row for row in markets}
    lanes: list[NetworkLane] = []

    distribution_centers = sorted(
        (row for row in facilities if row.facility_type == "distribution_center"),
        key=lambda row: row.facility_id,
    )
    for origin in distribution_centers:
        for destination in distribution_centers:
            if origin.facility_id == destination.facility_id:
                continue
            lanes.append(
                _lane(
                    lane_id=f"LNE_{origin.facility_id}_TO_{destination.facility_id}",
                    lane_name=f"{origin.facility_name} to {destination.facility_name}",
                    lane_type="LINEHAUL",
                    origin=origin,
                    destination_id=destination.facility_id,
                    destination_type="facility",
                    destination_lat=destination.lat,
                    destination_lng=destination.lng,
                ),
            )

    for depot in sorted(
        (row for row in facilities if row.facility_type == "depot"),
        key=lambda row: row.facility_id,
    ):
        market = markets_by_depot[depot.facility_id]
        for distribution_center in distribution_centers:
            lanes.append(
                _lane(
                lane_id=(
                    f"LNE_{distribution_center.facility_id}_TO_{depot.facility_id}"
                ),
                lane_name=(
                    f"{distribution_center.facility_name} to {depot.facility_name}"
                ),
                lane_type="LINEHAUL",
                origin=distribution_center,
                destination_id=depot.facility_id,
                destination_type="facility",
                destination_lat=depot.lat,
                destination_lng=depot.lng,
                )
            )
        lanes.append(
            _lane(
                lane_id=f"LNE_{depot.facility_id}_TO_{market.market_id}",
                lane_name=f"{depot.facility_name} to {market.market_name}",
                lane_type="MARKET",
                origin=depot,
                destination_id=market.market_id,
                destination_type="market",
                destination_lat=market.lat,
                destination_lng=market.lng,
            )
        )

    for customer in customers:
        depot = facilities_by_id[customer.depot_id]
        lanes.append(
            _lane(
                lane_id=f"LNE_{depot.facility_id}_TO_{customer.customer_id}",
                lane_name=f"{depot.facility_name} to {customer.customer_name}",
                lane_type="DELIVERY",
                origin=depot,
                destination_id=customer.customer_id,
                destination_type="customer",
                destination_lat=customer.lat,
                destination_lng=customer.lng,
            )
        )
    return lanes


def _build_demand(
    customers: Sequence[NetworkCustomer],
    base_demand: Mapping[str, int],
    *,
    horizon_start: date,
    horizon_days: int,
    seed: int,
    demand_plan_version_id: str = DEMAND_PLAN_VERSION_ID,
) -> list[DemandPlanDaily]:
    rng = random.Random(seed + 19)
    rows: list[DemandPlanDaily] = []
    for day_offset in range(horizon_days):
        service_date = horizon_start + timedelta(days=day_offset)
        day_multiplier = _WEEKDAY_MULTIPLIERS[service_date.weekday()]
        for customer in customers:
            customer_variation = rng.uniform(0.90, 1.12)
            rows.append(
                DemandPlanDaily(
                    demand_plan_version_id=demand_plan_version_id,
                    service_date=service_date,
                    region_id=customer.region_id,
                    distribution_center_id=customer.distribution_center_id,
                    depot_id=customer.depot_id,
                    market_id=customer.market_id,
                    customer_id=customer.customer_id,
                    demand_units=max(
                        1,
                        int(
                            round(
                                base_demand[customer.customer_id]
                                * day_multiplier
                                * customer_variation
                            )
                        ),
                    ),
                )
            )
    return rows


def _build_capacity_and_flow(
    *,
    facilities: Sequence[NetworkFacility],
    lanes: Sequence[NetworkLane],
    demand: Sequence[DemandPlanDaily],
    demand_plan_version_id: str = DEMAND_PLAN_VERSION_ID,
    capacity_plan_version_id: str = CAPACITY_PLAN_VERSION_ID,
) -> tuple[
    list[FacilityCapacityDaily],
    list[LaneCapacityDaily],
    list[BaselineNetworkFlowDaily],
]:
    facilities_by_id = {row.facility_id: row for row in facilities}
    demand_by_date_depot: defaultdict[tuple[date, str], int] = defaultdict(int)
    demand_by_date_customer: dict[tuple[date, str], int] = {}
    service_dates: set[date] = set()
    for row in demand:
        service_dates.add(row.service_date)
        demand_by_date_depot[(row.service_date, row.depot_id)] += row.demand_units
        demand_by_date_customer[(row.service_date, row.customer_id)] = row.demand_units

    child_depots: defaultdict[str, list[str]] = defaultdict(list)
    for facility in facilities:
        if facility.parent_facility_id:
            child_depots[facility.parent_facility_id].append(facility.facility_id)

    facility_capacity: list[FacilityCapacityDaily] = []
    lane_capacity: list[LaneCapacityDaily] = []
    baseline_flow: list[BaselineNetworkFlowDaily] = []
    for service_date in sorted(service_dates):
        regional_demand = sum(
            volume
            for (row_date, _), volume in demand_by_date_depot.items()
            if row_date == service_date
        )
        for facility in facilities:
            if facility.facility_type == "distribution_center":
                volume = sum(
                    demand_by_date_depot[(service_date, depot_id)]
                    for depot_id in child_depots[facility.facility_id]
                )
                buffer_pct = 0.20
            else:
                volume = demand_by_date_depot[(service_date, facility.facility_id)]
                buffer_pct = 0.16
            facility_capacity.append(
                FacilityCapacityDaily(
                    capacity_plan_version_id=capacity_plan_version_id,
                    service_date=service_date,
                    facility_id=facility.facility_id,
                    capacity_units=_capacity_for(volume, buffer_pct),
                )
            )

        for lane in lanes:
            if lane.lane_type == "LINEHAUL":
                destination = facilities_by_id[lane.destination_endpoint_id]
                if destination.facility_type == "depot":
                    depot_demand = demand_by_date_depot[
                        (service_date, destination.facility_id)
                    ]
                    is_primary = (
                        lane.origin_endpoint_id == destination.parent_facility_id
                    )
                    assigned = depot_demand if is_primary else 0
                    capacity = (
                        _capacity_for(depot_demand, 0.14)
                        if is_primary
                        else max(1, int(math.ceil(depot_demand * 0.45)))
                    )
                else:
                    assigned = 0
                    capacity = _capacity_for(regional_demand, 0.35)
            elif lane.lane_type == "MARKET":
                assigned = demand_by_date_depot[(service_date, lane.origin_endpoint_id)]
                capacity = _capacity_for(assigned, 0.12)
            else:
                assigned = demand_by_date_customer[(service_date, lane.destination_endpoint_id)]
                capacity = _capacity_for(assigned, 0.25)

            lane_capacity.append(
                LaneCapacityDaily(
                    capacity_plan_version_id=capacity_plan_version_id,
                    service_date=service_date,
                    lane_id=lane.lane_id,
                    capacity_units=capacity,
                )
            )
            baseline_flow.append(
                BaselineNetworkFlowDaily(
                    demand_plan_version_id=demand_plan_version_id,
                    capacity_plan_version_id=capacity_plan_version_id,
                    service_date=service_date,
                    lane_id=lane.lane_id,
                    lane_type=lane.lane_type,
                    assigned_units=assigned,
                )
            )
    return facility_capacity, lane_capacity, baseline_flow


def _build_spec_facilities(
    region_id: str,
    distribution_centers: Sequence[tuple[str, str, float, float, str]],
    depots: Sequence[tuple[str, str, str, float, float]],
) -> list[NetworkFacility]:
    timezone_by_dc = {row[0]: row[4] for row in distribution_centers}
    facilities = [
        NetworkFacility(
            facility_id=facility_id,
            facility_name=facility_name,
            facility_type="distribution_center",
            region_id=region_id,
            lat=lat,
            lng=lng,
            timezone=timezone_name,
        )
        for facility_id, facility_name, lat, lng, timezone_name in distribution_centers
    ]
    facilities.extend(
        NetworkFacility(
            facility_id=facility_id,
            facility_name=facility_name,
            facility_type="depot",
            region_id=region_id,
            parent_facility_id=parent_id,
            lat=lat,
            lng=lng,
            timezone=timezone_by_dc[parent_id],
        )
        for facility_id, facility_name, parent_id, lat, lng in depots
    )
    return facilities


def _append_southeast_constrained_capacity_plan(
    dataset: dict[str, list[dict[str, object]]],
) -> None:
    """Add a supplied-capacity snapshot with an explicit Atlanta shortfall."""

    facilities = {
        str(row["facility_id"]): row for row in dataset["dim_facilities"]
    }
    lanes = {str(row["lane_id"]): row for row in dataset["dim_network_lanes"]}
    atlanta_dc_id = "DC_SOUTHEAST_ATLANTA"
    atlanta_depots = {
        facility_id
        for facility_id, row in facilities.items()
        if str(row.get("parent_facility_id")) == atlanta_dc_id
    }

    reduced_delivery: dict[tuple[str, str], int] = {}
    target_by_date_depot: defaultdict[tuple[str, str], int] = defaultdict(int)
    normal_flow = [
        row
        for row in dataset["baseline_network_flow_daily"]
        if row["capacity_plan_version_id"] == NATIONAL_CAPACITY_PLAN_VERSION_ID
    ]
    for row in normal_flow:
        lane = lanes[str(row["lane_id"])]
        if lane["lane_type"] != "DELIVERY":
            continue
        depot_id = str(lane["origin_endpoint_id"])
        if depot_id not in atlanta_depots:
            continue
        service_date = str(row["service_date"])
        reduced = int(math.floor(int(row["assigned_units"]) * 0.72))
        reduced_delivery[(service_date, str(row["lane_id"]))] = reduced
        target_by_date_depot[(service_date, depot_id)] += reduced

    constrained_flow: list[dict[str, object]] = []
    for row in normal_flow:
        lane = lanes[str(row["lane_id"])]
        service_date = str(row["service_date"])
        assigned = int(row["assigned_units"])
        if lane["lane_type"] == "DELIVERY":
            assigned = reduced_delivery.get(
                (service_date, str(row["lane_id"])), assigned
            )
        elif lane["lane_type"] == "MARKET":
            depot_id = str(lane["origin_endpoint_id"])
            if depot_id in atlanta_depots:
                assigned = target_by_date_depot[(service_date, depot_id)]
        elif lane["lane_type"] == "LINEHAUL":
            depot_id = str(lane["destination_endpoint_id"])
            if depot_id in atlanta_depots:
                assigned = (
                    target_by_date_depot[(service_date, depot_id)]
                    if str(lane["origin_endpoint_id"]) == atlanta_dc_id
                    else 0
                )
        constrained_flow.append(
            {
                **row,
                "capacity_plan_version_id": SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID,
                "assigned_units": assigned,
            }
        )

    constrained_facility_capacity: list[dict[str, object]] = []
    for row in dataset["facility_capacity_daily"]:
        if row["capacity_plan_version_id"] != NATIONAL_CAPACITY_PLAN_VERSION_ID:
            continue
        capacity = int(row["capacity_units"])
        if row["facility_id"] == atlanta_dc_id:
            service_date = str(row["service_date"])
            capacity = sum(
                target_by_date_depot[(service_date, depot_id)]
                for depot_id in atlanta_depots
            )
        constrained_facility_capacity.append(
            {
                **row,
                "capacity_plan_version_id": SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID,
                "capacity_units": capacity,
            }
        )

    constrained_lane_capacity: list[dict[str, object]] = []
    for row in dataset["lane_capacity_daily"]:
        if row["capacity_plan_version_id"] != NATIONAL_CAPACITY_PLAN_VERSION_ID:
            continue
        lane = lanes[str(row["lane_id"])]
        capacity = int(row["capacity_units"])
        destination_id = str(lane["destination_endpoint_id"])
        if (
            lane["lane_type"] == "LINEHAUL"
            and str(lane["origin_endpoint_id"]) == atlanta_dc_id
            and destination_id in atlanta_depots
        ):
            capacity = target_by_date_depot[
                (str(row["service_date"]), destination_id)
            ]
        constrained_lane_capacity.append(
            {
                **row,
                "capacity_plan_version_id": SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID,
                "capacity_units": capacity,
            }
        )

    published_at = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    constrained_version = ExternalPlanVersion(
        plan_version_id=SOUTHEAST_CONSTRAINED_CAPACITY_PLAN_VERSION_ID,
        plan_id="CAPACITY_US_SOUTHEAST_CONSTRAINED",
        revision=2,
        plan_type="capacity",
        display_name="US capacity plan · Southeast constrained",
        source_system=NETWORK_SOURCE_SYSTEM,
        published_at=published_at,
        as_of_date=published_at.date(),
        horizon_start=date.fromisoformat(
            str(dataset["capacity_plan_versions"][0]["horizon_start"])
        ),
        horizon_end=date.fromisoformat(
            str(dataset["capacity_plan_versions"][0]["horizon_end"])
        ),
        record_count=len(constrained_facility_capacity) + len(constrained_lane_capacity),
    )
    dataset["capacity_plan_versions"].extend(_rows([constrained_version]))
    dataset["facility_capacity_daily"].extend(constrained_facility_capacity)
    dataset["lane_capacity_daily"].extend(constrained_lane_capacity)
    dataset["baseline_network_flow_daily"].extend(constrained_flow)


def generate_network_dataset(
    existing_depots: Sequence[Mapping[str, object]],
    *,
    seed: int = 42,
    customers_per_depot: int = 12,
    horizon_start: date = DEFAULT_NETWORK_HORIZON_START,
    horizon_days: int = DEFAULT_NETWORK_HORIZON_DAYS,
) -> dict[str, list[dict[str, object]]]:
    """Generate one coherent regional network slice from immutable upstream plans."""

    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1.")

    rng = random.Random(seed)
    regions = [
        NetworkRegion(
            region_id=GREAT_LAKES_REGION_ID,
            region_name="Great Lakes",
        )
    ]
    facilities = _build_facilities(existing_depots)
    hierarchy = _build_hierarchy(facilities)
    markets = _build_markets(facilities)
    customers, base_demand = _build_customers(
        facilities,
        markets,
        customers_per_depot=customers_per_depot,
        rng=rng,
    )
    lanes = _build_lanes(facilities, markets, customers)
    demand = _build_demand(
        customers,
        base_demand,
        horizon_start=horizon_start,
        horizon_days=horizon_days,
        seed=seed,
    )
    facility_capacity, lane_capacity, baseline_flow = _build_capacity_and_flow(
        facilities=facilities,
        lanes=lanes,
        demand=demand,
    )
    horizon_end = horizon_start + timedelta(days=horizon_days - 1)
    published_at = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    demand_versions = [
        ExternalPlanVersion(
            plan_version_id=DEMAND_PLAN_VERSION_ID,
            plan_id="DEMAND_GL_BASELINE",
            revision=1,
            plan_type="demand",
            display_name="Great Lakes published demand plan",
            source_system=NETWORK_SOURCE_SYSTEM,
            published_at=published_at,
            as_of_date=published_at.date(),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            record_count=len(demand),
        )
    ]
    capacity_versions = [
        ExternalPlanVersion(
            plan_version_id=CAPACITY_PLAN_VERSION_ID,
            plan_id="CAPACITY_GL_BASELINE",
            revision=1,
            plan_type="capacity",
            display_name="Great Lakes supplied capacity plan",
            source_system=NETWORK_SOURCE_SYSTEM,
            published_at=published_at,
            as_of_date=published_at.date(),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            record_count=len(facility_capacity) + len(lane_capacity),
        )
    ]

    dataset = {
        "dim_regions": _rows(regions),
        "dim_facilities": _rows(facilities),
        "facility_hierarchy": _rows(hierarchy),
        "dim_markets": _rows(markets),
        "dim_network_customers": _rows(customers),
        "dim_network_lanes": _rows(lanes),
        "demand_plan_versions": _rows(demand_versions),
        "demand_plan_daily": _rows(demand),
        "capacity_plan_versions": _rows(capacity_versions),
        "facility_capacity_daily": _rows(facility_capacity),
        "lane_capacity_daily": _rows(lane_capacity),
        "baseline_network_flow_daily": _rows(baseline_flow),
    }
    assert_valid_network_dataset(dataset)
    return dataset


def generate_national_network_dataset(
    existing_depots: Sequence[Mapping[str, object]],
    *,
    seed: int = 42,
    customers_per_depot: int = 100,
    horizon_start: date = DEFAULT_NETWORK_HORIZON_START,
    horizon_days: int = 28,
) -> dict[str, list[dict[str, object]]]:
    """Generate the five-region US planning demo with alternate DC paths."""

    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1.")

    region_definitions: list[
        tuple[str, str, list[NetworkFacility], str]
    ] = [
        (
            GREAT_LAKES_REGION_ID,
            "Great Lakes",
            _build_facilities(existing_depots),
            "GL",
        )
    ]
    for region_id, region_name, distribution_centers, depots in _ADDITIONAL_REGION_SPECS:
        region_definitions.append(
            (
                region_id,
                region_name,
                _build_spec_facilities(region_id, distribution_centers, depots),
                {
                    "REGION_NORTHEAST": "NE",
                    "REGION_SOUTHEAST": "SE",
                    "REGION_WEST": "W",
                    "REGION_TOLA": "TOLA",
                }[region_id],
            )
        )

    regions: list[NetworkRegion] = []
    facilities: list[NetworkFacility] = []
    hierarchy: list[FacilityHierarchy] = []
    markets: list[NetworkMarket] = []
    customers: list[NetworkCustomer] = []
    lanes: list[NetworkLane] = []
    demand: list[DemandPlanDaily] = []
    facility_capacity: list[FacilityCapacityDaily] = []
    lane_capacity: list[LaneCapacityDaily] = []
    baseline_flow: list[BaselineNetworkFlowDaily] = []

    for region_index, (region_id, region_name, region_facilities, prefix) in enumerate(
        region_definitions
    ):
        regions.append(NetworkRegion(region_id=region_id, region_name=region_name))
        region_markets = _build_markets(region_facilities)
        region_customers, base_demand = _build_customers(
            region_facilities,
            region_markets,
            customers_per_depot=customers_per_depot,
            rng=random.Random(seed + region_index * 101),
            customer_id_prefix=f"NET-CUST-{prefix}",
        )
        region_lanes = _build_lanes(
            region_facilities,
            region_markets,
            region_customers,
        )
        region_demand = _build_demand(
            region_customers,
            base_demand,
            horizon_start=horizon_start,
            horizon_days=horizon_days,
            seed=seed + region_index * 101,
            demand_plan_version_id=NATIONAL_DEMAND_PLAN_VERSION_ID,
        )
        region_facility_capacity, region_lane_capacity, region_flow = (
            _build_capacity_and_flow(
                facilities=region_facilities,
                lanes=region_lanes,
                demand=region_demand,
                demand_plan_version_id=NATIONAL_DEMAND_PLAN_VERSION_ID,
                capacity_plan_version_id=NATIONAL_CAPACITY_PLAN_VERSION_ID,
            )
        )
        facilities.extend(region_facilities)
        hierarchy.extend(_build_hierarchy(region_facilities))
        markets.extend(region_markets)
        customers.extend(region_customers)
        lanes.extend(region_lanes)
        demand.extend(region_demand)
        facility_capacity.extend(region_facility_capacity)
        lane_capacity.extend(region_lane_capacity)
        baseline_flow.extend(region_flow)

    horizon_end = horizon_start + timedelta(days=horizon_days - 1)
    published_at = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    demand_versions = [
        ExternalPlanVersion(
            plan_version_id=NATIONAL_DEMAND_PLAN_VERSION_ID,
            plan_id="DEMAND_US_BASELINE",
            revision=1,
            plan_type="demand",
            display_name="US published demand plan",
            source_system=NETWORK_SOURCE_SYSTEM,
            published_at=published_at,
            as_of_date=published_at.date(),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            record_count=len(demand),
        )
    ]
    capacity_versions = [
        ExternalPlanVersion(
            plan_version_id=NATIONAL_CAPACITY_PLAN_VERSION_ID,
            plan_id="CAPACITY_US_BASELINE",
            revision=1,
            plan_type="capacity",
            display_name="US supplied capacity plan",
            source_system=NETWORK_SOURCE_SYSTEM,
            published_at=published_at,
            as_of_date=published_at.date(),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            record_count=len(facility_capacity) + len(lane_capacity),
        )
    ]
    dataset = {
        "dim_regions": _rows(regions),
        "dim_facilities": _rows(facilities),
        "facility_hierarchy": _rows(hierarchy),
        "dim_markets": _rows(markets),
        "dim_network_customers": _rows(customers),
        "dim_network_lanes": _rows(lanes),
        "demand_plan_versions": _rows(demand_versions),
        "demand_plan_daily": _rows(demand),
        "capacity_plan_versions": _rows(capacity_versions),
        "facility_capacity_daily": _rows(facility_capacity),
        "lane_capacity_daily": _rows(lane_capacity),
        "baseline_network_flow_daily": _rows(baseline_flow),
    }
    _append_southeast_constrained_capacity_plan(dataset)
    assert_valid_network_dataset(dataset)
    return dataset


def validate_network_dataset(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[str]:
    """Return all canonical, referential, reconciliation, and capacity errors."""

    errors: list[str] = []
    for table_name, model in NETWORK_TABLE_MODELS.items():
        if table_name not in dataset:
            errors.append(f"Missing canonical table: {table_name}.")
            continue
        for index, row in enumerate(dataset[table_name]):
            try:
                model.model_validate(row)
            except Exception as exc:
                errors.append(f"{table_name}[{index}] failed schema validation: {exc}")
    if errors:
        return errors

    def unique_index(table_name: str, key: str) -> dict[str, Mapping[str, object]]:
        index: dict[str, Mapping[str, object]] = {}
        for row in dataset[table_name]:
            value = str(row[key])
            if value in index:
                errors.append(f"{table_name} contains duplicate {key}={value}.")
            index[value] = row
        return index

    regions = unique_index("dim_regions", "region_id")
    facilities = unique_index("dim_facilities", "facility_id")
    markets = unique_index("dim_markets", "market_id")
    customers = unique_index("dim_network_customers", "customer_id")
    lanes = unique_index("dim_network_lanes", "lane_id")
    demand_versions = unique_index("demand_plan_versions", "plan_version_id")
    capacity_versions = unique_index("capacity_plan_versions", "plan_version_id")

    for version in demand_versions.values():
        if version["plan_type"] != "demand":
            errors.append(f"Demand plan {version['plan_version_id']} has the wrong plan_type.")
    for version in capacity_versions.values():
        if version["plan_type"] != "capacity":
            errors.append(f"Capacity plan {version['plan_version_id']} has the wrong plan_type.")

    for facility in facilities.values():
        region_id = str(facility["region_id"])
        if region_id not in regions:
            errors.append(
                f"Facility {facility['facility_id']} references missing region {region_id}."
            )
        parent_id = facility.get("parent_facility_id")
        if parent_id:
            parent = facilities.get(str(parent_id))
            if parent is None or parent.get("facility_type") != "distribution_center":
                errors.append(
                    f"Depot {facility['facility_id']} references invalid distribution "
                    f"center {parent_id}."
                )

    hierarchy_keys: set[tuple[str, str, str]] = set()
    hierarchy_rows = dataset["facility_hierarchy"]
    for row in hierarchy_rows:
        key = (
            str(row["ancestor_type"]),
            str(row["ancestor_id"]),
            str(row["descendant_facility_id"]),
        )
        if key in hierarchy_keys:
            errors.append(f"facility_hierarchy contains duplicate relationship {key}.")
        hierarchy_keys.add(key)
        if str(row["descendant_facility_id"]) not in facilities:
            errors.append(
                f"Hierarchy references missing descendant {row['descendant_facility_id']}."
            )
        ancestor_index = regions if row["ancestor_type"] == "region" else facilities
        if str(row["ancestor_id"]) not in ancestor_index:
            errors.append(
                f"Hierarchy references missing {row['ancestor_type']} {row['ancestor_id']}."
            )

    for facility in facilities.values():
        region_relationship = (
            "region",
            str(facility["region_id"]),
            str(facility["facility_id"]),
        )
        if region_relationship not in hierarchy_keys:
            errors.append(
                f"Facility {facility['facility_id']} is missing its region hierarchy row."
            )
        if facility["facility_type"] == "depot":
            parent_relationship = (
                "facility",
                str(facility["parent_facility_id"]),
                str(facility["facility_id"]),
            )
            if parent_relationship not in hierarchy_keys:
                errors.append(f"Depot {facility['facility_id']} is missing its DC hierarchy row.")

    for market in markets.values():
        if str(market["region_id"]) not in regions:
            errors.append(f"Market {market['market_id']} references a missing region.")
        depot = facilities.get(str(market["primary_depot_id"]))
        if depot is None or depot["facility_type"] != "depot":
            errors.append(f"Market {market['market_id']} references an invalid primary depot.")

    for customer in customers.values():
        if str(customer["region_id"]) not in regions:
            errors.append(f"Customer {customer['customer_id']} references a missing region.")
        depot = facilities.get(str(customer["depot_id"]))
        dc = facilities.get(str(customer["distribution_center_id"]))
        market = markets.get(str(customer["market_id"]))
        if depot is None or depot["facility_type"] != "depot":
            errors.append(f"Customer {customer['customer_id']} references an invalid depot.")
        if dc is None or dc["facility_type"] != "distribution_center":
            errors.append(
                f"Customer {customer['customer_id']} references an invalid distribution center."
            )
        if market is None or str(market["primary_depot_id"]) != str(customer["depot_id"]):
            errors.append(f"Customer {customer['customer_id']} references an invalid market.")

    endpoint_indexes = {
        "facility": facilities,
        "market": markets,
        "customer": customers,
    }
    for lane in lanes.values():
        for side in ("origin", "destination"):
            endpoint_type = str(lane[f"{side}_endpoint_type"])
            endpoint_id = str(lane[f"{side}_endpoint_id"])
            if endpoint_id not in endpoint_indexes[endpoint_type]:
                errors.append(
                    f"Lane {lane['lane_id']} references missing {endpoint_type} {endpoint_id}."
                )

    demand_rows = dataset["demand_plan_daily"]
    demand_keys: set[tuple[str, str, str]] = set()
    for row in demand_rows:
        demand_key = (
            str(row["demand_plan_version_id"]),
            str(row["service_date"]),
            str(row["customer_id"]),
        )
        if demand_key in demand_keys:
            errors.append(f"demand_plan_daily contains duplicate row {demand_key}.")
        demand_keys.add(demand_key)
        if str(row["demand_plan_version_id"]) not in demand_versions:
            errors.append(
                f"Demand row references missing plan {row['demand_plan_version_id']}."
            )
        customer = customers.get(str(row["customer_id"]))
        if customer is None:
            errors.append(f"Demand row references missing customer {row['customer_id']}.")
            continue
        for field in ("region_id", "distribution_center_id", "depot_id", "market_id"):
            if str(row[field]) != str(customer[field]):
                errors.append(
                    f"Demand row for {row['customer_id']} disagrees with customer {field}."
                )

    facility_capacity: dict[tuple[str, str, str], int] = {}
    lane_capacity: dict[tuple[str, str, str], int] = {}
    for row in dataset["facility_capacity_daily"]:
        capacity_key = (
            str(row["capacity_plan_version_id"]),
            str(row["service_date"]),
            str(row["facility_id"]),
        )
        if capacity_key in facility_capacity:
            errors.append(f"facility_capacity_daily contains duplicate row {capacity_key}.")
        facility_capacity[capacity_key] = int(row["capacity_units"])
        if str(row["capacity_plan_version_id"]) not in capacity_versions:
            errors.append(
                f"Facility capacity references missing plan {row['capacity_plan_version_id']}."
            )
        if str(row["facility_id"]) not in facilities:
            errors.append(f"Capacity row references missing facility {row['facility_id']}.")
    for row in dataset["lane_capacity_daily"]:
        capacity_key = (
            str(row["capacity_plan_version_id"]),
            str(row["service_date"]),
            str(row["lane_id"]),
        )
        if capacity_key in lane_capacity:
            errors.append(f"lane_capacity_daily contains duplicate row {capacity_key}.")
        lane_capacity[capacity_key] = int(row["capacity_units"])
        if str(row["capacity_plan_version_id"]) not in capacity_versions:
            errors.append(
                f"Lane capacity references missing plan {row['capacity_plan_version_id']}."
            )
        if str(row["lane_id"]) not in lanes:
            errors.append(f"Capacity row references missing lane {row['lane_id']}.")

    demand_by_plan_date_depot: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    demand_by_plan_date: defaultdict[tuple[str, str], int] = defaultdict(int)
    for row in demand_rows:
        demand_plan_id = str(row["demand_plan_version_id"])
        service_date = str(row["service_date"])
        units = int(row["demand_units"])
        demand_by_plan_date[(demand_plan_id, service_date)] += units
        demand_by_plan_date_depot[
            (demand_plan_id, service_date, str(row["depot_id"]))
        ] += units

    flow_by_context_type: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    depot_linehaul: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    depot_market: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    depot_delivery: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    dc_outbound: defaultdict[tuple[str, str, str, str], int] = defaultdict(int)
    flow_contexts: set[tuple[str, str, str]] = set()
    flow_keys: set[tuple[str, str, str, str]] = set()
    for row in dataset["baseline_network_flow_daily"]:
        demand_plan_id = str(row["demand_plan_version_id"])
        capacity_plan_id = str(row["capacity_plan_version_id"])
        service_date = str(row["service_date"])
        lane_id = str(row["lane_id"])
        flow_key = (demand_plan_id, capacity_plan_id, service_date, lane_id)
        if flow_key in flow_keys:
            errors.append(f"baseline_network_flow_daily contains duplicate row {flow_key}.")
        flow_keys.add(flow_key)
        flow_contexts.add((demand_plan_id, capacity_plan_id, service_date))
        if demand_plan_id not in demand_versions:
            errors.append(f"Flow row references missing demand plan {demand_plan_id}.")
        if capacity_plan_id not in capacity_versions:
            errors.append(f"Flow row references missing capacity plan {capacity_plan_id}.")
        lane = lanes.get(lane_id)
        if lane is None:
            errors.append(f"Flow row references missing lane {lane_id}.")
            continue
        units = int(row["assigned_units"])
        capacity = lane_capacity.get((capacity_plan_id, service_date, lane_id))
        if capacity is None:
            errors.append(f"Flow row for {lane_id} on {service_date} has no supplied capacity.")
        elif units > capacity:
            errors.append(
                f"Flow {lane_id} on {service_date} exceeds capacity: {units} > {capacity}."
            )
        lane_type = str(row["lane_type"])
        if lane_type != str(lane["lane_type"]):
            errors.append(f"Flow row {lane_id} has the wrong lane type.")
        flow_by_context_type[
            (demand_plan_id, capacity_plan_id, service_date, lane_type)
        ] += units
        context_depot_prefix = (demand_plan_id, capacity_plan_id, service_date)
        destination = facilities.get(str(lane["destination_endpoint_id"]))
        if lane_type == "LINEHAUL" and destination and destination["facility_type"] == "depot":
            depot_linehaul[context_depot_prefix + (str(destination["facility_id"]),)] += units
            dc_outbound[context_depot_prefix + (str(lane["origin_endpoint_id"]),)] += units
        elif lane_type == "MARKET":
            depot_market[context_depot_prefix + (str(lane["origin_endpoint_id"]),)] += units
        elif lane_type == "DELIVERY":
            depot_delivery[context_depot_prefix + (str(lane["origin_endpoint_id"]),)] += units

    for demand_plan_id, capacity_plan_id, service_date in flow_contexts:
        total_demand = demand_by_plan_date[(demand_plan_id, service_date)]
        assigned_by_type = {
            lane_type: flow_by_context_type[
                (demand_plan_id, capacity_plan_id, service_date, lane_type)
            ]
            for lane_type in ("LINEHAUL", "MARKET", "DELIVERY")
        }
        if len(set(assigned_by_type.values())) != 1:
            errors.append(
                f"Flow layers do not reconcile for {demand_plan_id}/{capacity_plan_id} "
                f"on {service_date}: {assigned_by_type}."
            )
        if assigned_by_type["DELIVERY"] > total_demand:
            errors.append(
                f"Assigned flow exceeds demand for {demand_plan_id}/{capacity_plan_id} "
                f"on {service_date}."
            )

        for depot_id, facility in facilities.items():
            if facility["facility_type"] != "depot":
                continue
            depot_key = (demand_plan_id, capacity_plan_id, service_date, depot_id)
            assigned = depot_linehaul[depot_key]
            if not (assigned == depot_market[depot_key] == depot_delivery[depot_key]):
                errors.append(
                    f"Flow layers do not reconcile at depot {depot_id} on {service_date}."
                )
            depot_demand = demand_by_plan_date_depot[
                (demand_plan_id, service_date, depot_id)
            ]
            if assigned > depot_demand:
                errors.append(
                    f"Assigned flow to {depot_id} on {service_date} exceeds demand."
                )
            depot_capacity = facility_capacity.get(
                (capacity_plan_id, service_date, depot_id)
            )
            if depot_capacity is None or assigned > depot_capacity:
                errors.append(
                    f"Depot {depot_id} on {service_date} lacks supplied capacity."
                )

    distribution_centers = {
        facility_id: facility
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "distribution_center"
    }
    for demand_plan_id, capacity_plan_id, service_date in flow_contexts:
        for dc_id in distribution_centers:
            assigned = dc_outbound[
                (demand_plan_id, capacity_plan_id, service_date, dc_id)
            ]
            dc_capacity = facility_capacity.get(
                (capacity_plan_id, service_date, dc_id)
            )
            if dc_capacity is None or assigned > dc_capacity:
                errors.append(
                    f"Distribution center {dc_id} on {service_date} lacks supplied capacity."
                )

    for plan_version_id, version in demand_versions.items():
        expected = sum(
            1
            for row in demand_rows
            if str(row["demand_plan_version_id"]) == plan_version_id
        )
        if int(version["record_count"]) != expected:
            errors.append(
                f"Demand plan {plan_version_id} record_count does not match demand_plan_daily."
            )
    for plan_version_id, version in capacity_versions.items():
        expected = sum(
            1
            for row in dataset["facility_capacity_daily"]
            if str(row["capacity_plan_version_id"]) == plan_version_id
        ) + sum(
            1
            for row in dataset["lane_capacity_daily"]
            if str(row["capacity_plan_version_id"]) == plan_version_id
        )
        if int(version["record_count"]) != expected:
            errors.append(
                f"Capacity plan {plan_version_id} record_count does not match capacity facts."
            )
    return errors


def assert_valid_network_dataset(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    errors = validate_network_dataset(dataset)
    if errors:
        raise ValueError("Invalid canonical network dataset:\n- " + "\n- ".join(errors))
