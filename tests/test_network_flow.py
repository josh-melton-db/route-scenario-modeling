from copy import deepcopy

from route_opt.network_flow import solve_fixed_capacity_network
from route_opt.network_synthetic import generate_national_network_dataset
from route_opt.synthetic import generate_depots


def _national_rows():
    return generate_national_network_dataset(generate_depots(), seed=42)


def test_solver_respects_fixed_capacity_and_reduces_unmet_demand() -> None:
    rows = _national_rows()
    result = solve_fixed_capacity_network(
        rows,
        demand_plan_version_id="DEMAND_US_BASELINE_V1",
        capacity_plan_version_id="CAPACITY_US_SE_CONSTRAINED_V2",
        horizon_start="2026-09-21",
        horizon_end="2026-09-21",
        region_id="ALL",
    )

    baseline_by_key = {
        (str(row["service_date"]), str(row["lane_id"])): int(row["assigned_units"])
        for row in rows["baseline_network_flow_daily"]
        if str(row["service_date"]) == "2026-09-21"
    }
    lane_capacity = {
        str(row["lane_id"]): int(row["capacity_units"])
        for row in rows["lane_capacity_daily"]
        if str(row["capacity_plan_version_id"]) == "CAPACITY_US_SE_CONSTRAINED_V2"
        and str(row["service_date"]) == "2026-09-21"
    }

    baseline_assigned = sum(
        units
        for (_, lane_id), units in baseline_by_key.items()
        if lane_id.startswith("LNE_DC_")
    )
    solved_assigned = sum(row["assigned_units"] for row in result["allocation_rows"])

    assert solved_assigned >= baseline_assigned
    for row in result["allocation_rows"]:
        assert 0 <= row["assigned_units"] <= lane_capacity[row["lane_id"]]
    assert sum(row["unmet_units"] for row in result["unmet_rows"]) > 0
    assert sum(row["assigned_units"] for row in result["unmet_rows"]) == solved_assigned
    for row in result["flow_rows"]:
        if row["lane_type"] == "MARKET":
            depot_id = row["lane_id"].removeprefix("LNE_").split("_TO_")[0]
            matching = next(
                item
                for item in result["unmet_rows"]
                if item["depot_id"] == depot_id
            )
            assert row["assigned_units"] == matching["assigned_units"]


def test_solver_uses_alternate_dc_when_primary_disabled() -> None:
    rows = _national_rows()
    result = solve_fixed_capacity_network(
        rows,
        demand_plan_version_id="DEMAND_US_BASELINE_V1",
        capacity_plan_version_id="CAPACITY_US_BASELINE_V1",
        horizon_start="2026-09-21",
        horizon_end="2026-09-21",
        region_id="REGION_SOUTHEAST",
        disabled_facility_ids={"DC_SOUTHEAST_ATLANTA"},
    )

    atlanta_lanes = [
        row
        for row in result["allocation_rows"]
        if row["lane_id"].startswith("LNE_DC_SOUTHEAST_ATLANTA_TO_")
    ]
    assert all(row["assigned_units"] == 0 for row in atlanta_lanes)

    charlotte_lanes = [
        row
        for row in result["allocation_rows"]
        if row["lane_id"].startswith("LNE_DC_SOUTHEAST_CHARLOTTE_TO_")
        and row["assigned_units"] > 0
    ]
    assert charlotte_lanes, "Charlotte should serve depots when Atlanta is disabled"
    # Capacity is never invented: with Atlanta's fixed DC capacity gone, the
    # demand it served becomes explicit unmet demand rather than being absorbed.
    unmet_total = sum(row["unmet_units"] for row in result["unmet_rows"])
    assert unmet_total > 0
    atlanta_depots = {"DPT_SE_BIRMINGHAM", "DPT_SE_JACKSONVILLE", "DPT_SE_NASHVILLE"}
    assert all(
        row["depot_id"] in atlanta_depots
        for row in result["unmet_rows"]
        if row["unmet_units"] > 0
    )


def test_texas_corridor_shares_monterrey_capacity_and_tariff_reroutes() -> None:
    rows = _national_rows()
    service_date = "2026-09-21"
    cross_border_lanes = {
        "LNE_DC_MEXICO_MONTERREY_TO_DPT_TOLA_SAN_ANTONIO",
        "LNE_DC_MEXICO_MONTERREY_TO_DPT_TOLA_DALLAS",
    }
    common = dict(
        demand_plan_version_id="DEMAND_US_BASELINE_V1",
        capacity_plan_version_id="CAPACITY_US_BASELINE_V1",
        horizon_start=service_date,
        horizon_end=service_date,
        region_id="REGION_TOLA",
    )

    untariffed = solve_fixed_capacity_network(rows, **common)
    tariffed = solve_fixed_capacity_network(
        rows,
        **common,
        tariff_per_case_by_date_lane={
            (service_date, lane_id): 0.10 for lane_id in cross_border_lanes
        },
    )
    cross_border_before = sum(
        row["assigned_units"]
        for row in untariffed["allocation_rows"]
        if row["lane_id"] in cross_border_lanes
    )
    cross_border_after = sum(
        row["assigned_units"]
        for row in tariffed["allocation_rows"]
        if row["lane_id"] in cross_border_lanes
    )
    baseline_cross_border = sum(
        int(row["assigned_units"])
        for row in rows["baseline_network_flow_daily"]
        if row["capacity_plan_version_id"] == "CAPACITY_US_BASELINE_V1"
        and row["service_date"] == service_date
        and row["lane_id"] in cross_border_lanes
    )
    assert cross_border_before == baseline_cross_border > 0
    assert 0 < cross_border_after < cross_border_before

    # The Texas focus also solves Monterrey's three domestic depots. Their flow
    # and Texas flow share the one dated DC capacity arc, preventing reuse.
    solved_depots = {row["depot_id"] for row in tariffed["unmet_rows"]}
    assert len(solved_depots) == 9
    assert {
        "DPT_MX_MONTERREY",
        "DPT_MX_SALTILLO",
        "DPT_MX_CHIHUAHUA",
    } <= solved_depots
    assert "DPT_MX_GUADALAJARA" not in solved_depots
    assert "DPT_CA_TORONTO" not in solved_depots
    monterrey_outbound = sum(
        row["assigned_units"]
        for row in tariffed["allocation_rows"]
        if row["lane_id"].startswith("LNE_DC_MEXICO_MONTERREY_TO_DPT_")
    )
    monterrey_capacity = next(
        int(row["capacity_units"])
        for row in rows["facility_capacity_daily"]
        if row["capacity_plan_version_id"] == "CAPACITY_US_BASELINE_V1"
        and row["service_date"] == service_date
        and row["facility_id"] == "DC_MEXICO_MONTERREY"
    )
    assert monterrey_outbound <= monterrey_capacity


def test_tariffed_corridor_uses_cross_border_when_domestic_capacity_binds() -> None:
    # Keep capacity perturbations local even if the data source becomes cached.
    rows = deepcopy(_national_rows())
    service_date = "2026-09-21"
    cross_border_lanes = {
        "LNE_DC_MEXICO_MONTERREY_TO_DPT_TOLA_SAN_ANTONIO",
        "LNE_DC_MEXICO_MONTERREY_TO_DPT_TOLA_DALLAS",
    }
    for row in rows["facility_capacity_daily"]:
        if (
            row["capacity_plan_version_id"] == "CAPACITY_US_BASELINE_V1"
            and row["service_date"] == service_date
            and row["facility_id"] in {"DC_TOLA_DALLAS", "DC_TOLA_HOUSTON"}
        ):
            row["capacity_units"] = int(row["capacity_units"] * 0.55)

    result = solve_fixed_capacity_network(
        rows,
        demand_plan_version_id="DEMAND_US_BASELINE_V1",
        capacity_plan_version_id="CAPACITY_US_BASELINE_V1",
        horizon_start=service_date,
        horizon_end=service_date,
        region_id="REGION_TOLA",
        tariff_per_case_by_date_lane={
            (service_date, lane_id): 10.0 for lane_id in cross_border_lanes
        },
    )
    assert sum(
        row["assigned_units"]
        for row in result["allocation_rows"]
        if row["lane_id"] in cross_border_lanes
    ) > 0
