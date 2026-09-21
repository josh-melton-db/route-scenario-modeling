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
