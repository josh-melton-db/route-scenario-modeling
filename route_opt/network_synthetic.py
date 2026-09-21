from __future__ import annotations

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
                ancestor_id=GREAT_LAKES_REGION_ID,
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
            customer_id = f"NET-CUST-{customer_number:04d}"
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

    east = facilities_by_id["DC_GREAT_LAKES_EAST"]
    west = facilities_by_id["DC_GREAT_LAKES_WEST"]
    lanes.extend(
        (
            _lane(
                lane_id="LNE_GL_EAST_TO_WEST",
                lane_name="Detroit DC to Chicago DC",
                lane_type="LINEHAUL",
                origin=east,
                destination_id=west.facility_id,
                destination_type="facility",
                destination_lat=west.lat,
                destination_lng=west.lng,
            ),
            _lane(
                lane_id="LNE_GL_WEST_TO_EAST",
                lane_name="Chicago DC to Detroit DC",
                lane_type="LINEHAUL",
                origin=west,
                destination_id=east.facility_id,
                destination_type="facility",
                destination_lat=east.lat,
                destination_lng=east.lng,
            ),
        )
    )

    for depot in sorted(
        (row for row in facilities if row.facility_type == "depot"),
        key=lambda row: row.facility_id,
    ):
        parent = facilities_by_id[str(depot.parent_facility_id)]
        market = markets_by_depot[depot.facility_id]
        lanes.append(
            _lane(
                lane_id=f"LNE_{parent.facility_id}_TO_{depot.facility_id}",
                lane_name=f"{parent.facility_name} to {depot.facility_name}",
                lane_type="LINEHAUL",
                origin=parent,
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
                    demand_plan_version_id=DEMAND_PLAN_VERSION_ID,
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
                    capacity_plan_version_id=CAPACITY_PLAN_VERSION_ID,
                    service_date=service_date,
                    facility_id=facility.facility_id,
                    capacity_units=_capacity_for(volume, buffer_pct),
                )
            )

        for lane in lanes:
            if lane.lane_type == "LINEHAUL":
                destination = facilities_by_id[lane.destination_endpoint_id]
                if destination.facility_type == "depot":
                    assigned = demand_by_date_depot[(service_date, destination.facility_id)]
                    capacity = _capacity_for(assigned, 0.14)
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
                    capacity_plan_version_id=CAPACITY_PLAN_VERSION_ID,
                    service_date=service_date,
                    lane_id=lane.lane_id,
                    capacity_units=capacity,
                )
            )
            baseline_flow.append(
                BaselineNetworkFlowDaily(
                    demand_plan_version_id=DEMAND_PLAN_VERSION_ID,
                    capacity_plan_version_id=CAPACITY_PLAN_VERSION_ID,
                    service_date=service_date,
                    lane_id=lane.lane_id,
                    lane_type=lane.lane_type,
                    assigned_units=assigned,
                )
            )
    return facility_capacity, lane_capacity, baseline_flow


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

    facility_capacity: dict[tuple[str, str], int] = {}
    lane_capacity: dict[tuple[str, str], int] = {}
    for row in dataset["facility_capacity_daily"]:
        capacity_key = (str(row["service_date"]), str(row["facility_id"]))
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
        capacity_key = (str(row["service_date"]), str(row["lane_id"]))
        if capacity_key in lane_capacity:
            errors.append(f"lane_capacity_daily contains duplicate row {capacity_key}.")
        lane_capacity[capacity_key] = int(row["capacity_units"])
        if str(row["capacity_plan_version_id"]) not in capacity_versions:
            errors.append(
                f"Lane capacity references missing plan {row['capacity_plan_version_id']}."
            )
        if str(row["lane_id"]) not in lanes:
            errors.append(f"Capacity row references missing lane {row['lane_id']}.")

    demand_by_date_depot: defaultdict[tuple[str, str], int] = defaultdict(int)
    demand_by_date: defaultdict[str, int] = defaultdict(int)
    for row in demand_rows:
        service_date = str(row["service_date"])
        units = int(row["demand_units"])
        demand_by_date[service_date] += units
        demand_by_date_depot[(service_date, str(row["depot_id"]))] += units

    flow_by_type_date: defaultdict[tuple[str, str], int] = defaultdict(int)
    depot_linehaul_by_date: defaultdict[tuple[str, str], int] = defaultdict(int)
    flow_keys: set[tuple[str, str]] = set()
    for row in dataset["baseline_network_flow_daily"]:
        service_date = str(row["service_date"])
        lane_id = str(row["lane_id"])
        flow_key = (service_date, lane_id)
        if flow_key in flow_keys:
            errors.append(f"baseline_network_flow_daily contains duplicate row {flow_key}.")
        flow_keys.add(flow_key)
        lane = lanes.get(lane_id)
        if lane is None:
            errors.append(f"Flow row references missing lane {lane_id}.")
            continue
        units = int(row["assigned_units"])
        capacity = lane_capacity.get((service_date, lane_id))
        if capacity is None:
            errors.append(f"Flow row for {lane_id} on {service_date} has no supplied capacity.")
        elif units > capacity:
            errors.append(
                f"Flow {lane_id} on {service_date} exceeds capacity: {units} > {capacity}."
            )
        lane_type = str(row["lane_type"])
        if lane_type != str(lane["lane_type"]):
            errors.append(f"Flow row {lane_id} has the wrong lane type.")
        flow_by_type_date[(service_date, lane_type)] += units
        destination = facilities.get(str(lane["destination_endpoint_id"]))
        if lane_type == "LINEHAUL" and destination and destination["facility_type"] == "depot":
            depot_linehaul_by_date[(service_date, str(destination["facility_id"]))] += units

    for service_date, total_demand in demand_by_date.items():
        for lane_type in ("LINEHAUL", "MARKET", "DELIVERY"):
            assigned = flow_by_type_date[(service_date, lane_type)]
            if assigned != total_demand:
                errors.append(
                    f"{lane_type} flow on {service_date} does not reconcile to demand: "
                    f"{assigned} != {total_demand}."
                )

    for (service_date, depot_id), depot_demand in demand_by_date_depot.items():
        if depot_linehaul_by_date[(service_date, depot_id)] != depot_demand:
            errors.append(
                f"Linehaul flow to {depot_id} on {service_date} does not reconcile to demand."
            )
        depot_capacity = facility_capacity.get((service_date, depot_id))
        if depot_capacity is None or depot_demand > depot_capacity:
            errors.append(
                f"Depot {depot_id} on {service_date} lacks sufficient supplied facility capacity."
            )

    distribution_centers = {
        facility_id: facility
        for facility_id, facility in facilities.items()
        if facility["facility_type"] == "distribution_center"
    }
    for service_date in demand_by_date:
        for dc_id in distribution_centers:
            child_demand = sum(
                volume
                for (row_date, depot_id), volume in demand_by_date_depot.items()
                if row_date == service_date
                and str(facilities[depot_id].get("parent_facility_id")) == dc_id
            )
            dc_capacity = facility_capacity.get((service_date, dc_id))
            if dc_capacity is None or child_demand > dc_capacity:
                errors.append(
                    f"Distribution center {dc_id} on {service_date} lacks supplied capacity."
                )

    demand_version = next(iter(demand_versions.values()), None)
    if demand_version and int(demand_version["record_count"]) != len(demand_rows):
        errors.append("Demand plan record_count does not match demand_plan_daily.")
    capacity_version = next(iter(capacity_versions.values()), None)
    expected_capacity_count = len(dataset["facility_capacity_daily"]) + len(
        dataset["lane_capacity_daily"]
    )
    if capacity_version and int(capacity_version["record_count"]) != expected_capacity_count:
        errors.append("Capacity plan record_count does not match its daily capacity tables.")
    return errors


def assert_valid_network_dataset(
    dataset: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    errors = validate_network_dataset(dataset)
    if errors:
        raise ValueError("Invalid canonical network dataset:\n- " + "\n- ".join(errors))
