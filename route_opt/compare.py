from __future__ import annotations

from .baseline import _route_contract, summarize_kpis
from .config import DEFAULT_GENERATED_AT
from .schemas import MATRIX_SOURCE


def flatten_kpis(kpis: dict[str, object]) -> dict[str, float]:
    flat: dict[str, float] = {}
    for key, value in kpis.items():
        if key == "cost_breakdown":
            flat.update(value)  # type: ignore[arg-type]
        elif isinstance(value, (int, float)):
            flat[key] = float(value)
    return flat


def kpi_deltas(
    baseline_kpis: dict[str, object],
    scenario_kpis: dict[str, object],
) -> dict[str, object]:
    baseline = flatten_kpis(baseline_kpis)
    scenario = flatten_kpis(scenario_kpis)
    keys = [
        "route_count",
        "driver_count",
        "vehicle_count",
        "total_miles",
        "drive_minutes",
        "service_minutes",
        "total_cases",
        "avg_stops_per_route",
        "avg_capacity_utilization_pct",
        "avg_driver_utilization_pct",
        "overtime_minutes",
        "missed_windows",
        "late_minutes",
        "total_revenue",
        "profit",
        "mileage_cost",
        "labor_cost",
        "overtime_cost",
        "fixed_vehicle_cost",
        "sla_penalty_cost",
        "carrier_linehaul_cost",
        "carrier_lane_cost",
        "carrier_stop_cost",
        "carrier_minimum_adjustment",
        "fuel_surcharge_cost",
        "accessorial_cost",
        "volume_tier_adjustment",
        "commitment_adjustment",
        "total_cost",
    ]
    return {
        key: round(scenario.get(key, 0.0) - baseline.get(key, 0.0), 2)
        for key in keys
    }


def customer_impacts(
    baseline_stops: list[dict[str, object]],
    scenario_stops: list[dict[str, object]],
) -> list[dict[str, object]]:
    baseline_by_customer = {row["customer_id"]: row for row in baseline_stops}
    scenario_by_customer = {row["customer_id"]: row for row in scenario_stops}
    impacts: list[dict[str, object]] = []
    for customer_id in sorted(set(baseline_by_customer) | set(scenario_by_customer)):
        base = baseline_by_customer.get(customer_id)
        scenario = scenario_by_customer.get(customer_id)
        if base == scenario:
            continue
        is_new = base is None
        changed_route = bool(base and scenario and base["route_id"] != scenario["route_id"])
        changed_day = bool(base and scenario and base["delivery_day"] != scenario["delivery_day"])
        changed_depot = bool(base and scenario and base["depot_id"] != scenario["depot_id"])
        shift = int(scenario["sequence"]) - int(base["sequence"]) if base and scenario else 0
        disruption_score = min(
            1.0,
            (0.25 if changed_route else 0)
            + (0.35 if changed_day else 0)
            + (0.4 if changed_depot else 0)
            + min(abs(shift) * 0.05, 0.25)
            + (0.4 if is_new else 0),
        )
        impacts.append(
            {
                "customer_id": customer_id,
                "customer_name": (scenario or base)["customer_name"],  # type: ignore[index]
                "is_new_customer": is_new or bool((scenario or {}).get("is_new_customer", False)),
                "changed_route": changed_route,
                "changed_day": changed_day,
                "changed_depot": changed_depot,
                "sequence_shift": shift,
                "baseline_day": base["delivery_day"] if base else None,
                "scenario_day": scenario["delivery_day"] if scenario else None,
                "baseline_route_id": base["route_id"] if base else None,
                "scenario_route_id": scenario["route_id"] if scenario else None,
                "window_risk": (scenario or base).get("window_risk", "none"),  # type: ignore[union-attr]
                "disruption_score": round(disruption_score, 2),
                "summary": "New customer added to the route plan." if is_new else "Customer assignment changed in the scenario.",
            }
        )
    return impacts


def constraint_violations_from_solution(
    scenario_id: str,
    solution: dict[str, object],
) -> list[dict[str, object]]:
    diagnostics = solution.get("diagnostics", [])
    violations: list[dict[str, object]] = []
    for idx, row in enumerate(diagnostics if isinstance(diagnostics, list) else [], start=1):
        if row.get("status") != "infeasible":
            continue
        violations.append(
            {
                "violation_id": f"VIO-{idx:03d}",
                "severity": "hard",
                "scope": "scenario",
                "ref_id": scenario_id,
                "route_id": None,
                "customer_id": None,
                "metric": "route_duration",
                "limit_value": 600,
                "actual_value": None,
                "message": row["message"],
                "recommendation": "Relax service windows, add a depot candidate, or keep the existing facility location.",
            }
        )
    return violations


def compare_scenario(
    *,
    scenario: dict[str, object],
    baseline_result: dict[str, object],
    solution: dict[str, object],
    baseline_depot: dict[str, object],
    scenario_depot: dict[str, object],
    matrix_source: str = MATRIX_SOURCE,
) -> dict[str, object]:
    baseline_kpis = baseline_result["kpis"]
    scenario_routes = solution.get("routes", [])
    for route in scenario_routes:
        if route.get("fulfillment_method") != "carrier" and int(route.get("overtime_minutes", 0)) > 0:
            route["fulfillment_method"] = "private_overtime"
            route["decision_reason"] = "Assigned to private fleet using permitted overtime capacity."
    scenario_stops = solution.get("route_stops", [])
    violations = constraint_violations_from_solution(str(scenario["scenario_id"]), solution)
    if violations:
        scenario_kpis = None
        deltas = None
        status = "infeasible"
    else:
        scenario_kpis = summarize_kpis(scenario_routes)  # type: ignore[arg-type]
        deltas = kpi_deltas(baseline_kpis, scenario_kpis)
        status = "succeeded"
    baseline_routes = baseline_result["routes"]
    baseline_stops = baseline_result["route_stops"]
    impacts = customer_impacts(baseline_stops, scenario_stops)
    routes_by_id = {str(route["route_id"]): route for route in scenario_routes}
    for impact in impacts:
        route = routes_by_id.get(str(impact.get("scenario_route_id")))
        if route:
            impact["fulfillment_method"] = route.get("fulfillment_method", "private_fleet")
            impact["carrier_name"] = route.get("carrier_name")
            impact["decision_reason"] = route.get("decision_reason")
    unassigned = solution.get("unassigned_stops", [])
    customer_names = {
        str(row["customer_id"]): str(row["customer_name"]) for row in scenario_stops
    }
    allocations = _transportation_allocations(scenario_routes, unassigned)
    decisions = [
        {
            "customer_id": str(stop["customer_id"]),
            "customer_name": str(stop["customer_name"]),
            "decision": str(route.get("fulfillment_method", "private_fleet")).replace("_", " ").title(),
            "reason": str(route.get("decision_reason", "Assigned to available private-fleet capacity.")),
        }
        for route in scenario_routes
        for stop in scenario_stops
        if stop["route_id"] == route["route_id"] and route.get("fulfillment_method") == "carrier"
    ] + [
        {
            "customer_id": str(row["customer_id"]),
            "customer_name": customer_names.get(str(row["customer_id"]), str(row["customer_id"])),
            "decision": "Unserved",
            "reason": str(row.get("reason", "No feasible transportation capacity.")),
        }
        for row in unassigned
    ]
    result = {
        "scenario_id": scenario["scenario_id"],
        "baseline_scenario_id": scenario["baseline_scenario_id"],
        "scenario_name": scenario["scenario_name"],
        "status": status,
        "matrix_source": matrix_source,
        "generated_at": DEFAULT_GENERATED_AT,
        "summary": "Scenario is infeasible under current constraints." if status == "infeasible" else "Scenario solved and compared against an optimized baseline.",
        "baseline_depot": {
            "depot_id": baseline_depot["depot_id"],
            "name": baseline_depot["depot_name"],
            "region": baseline_depot["region"],
            "sales_territory": baseline_depot["sales_territory"],
            "location": {"lat": baseline_depot["lat"], "lng": baseline_depot["lng"]},
        },
        "scenario_depot": {
            "depot_id": scenario_depot["depot_id"],
            "name": scenario_depot["depot_name"],
            "region": scenario_depot["region"],
            "sales_territory": scenario_depot["sales_territory"],
            "location": {"lat": scenario_depot["lat"], "lng": scenario_depot["lng"]},
        },
        "baseline_routes": [_route_contract(route, baseline_stops) for route in baseline_routes],
        "scenario_routes": [_route_contract(route, scenario_stops) for route in scenario_routes],
        "baseline_kpis": baseline_kpis,
        "scenario_kpis": scenario_kpis,
        "kpi_deltas": deltas,
        "customer_impacts": impacts,
        "constraint_violations": violations,
        "transportation_allocation": allocations,
        "decision_explanations": decisions,
        "rate_book_snapshot_id": next(
            (
                str(route.get("rate_book_snapshot_id"))
                for route in scenario_routes
                if route.get("rate_book_snapshot_id")
            ),
            None,
        ),
    }
    return result


def _transportation_allocations(
    routes: list[dict[str, object]], unassigned: object
) -> list[dict[str, object]]:
    labels = {
        "private_fleet": "Private fleet",
        "private_overtime": "Private overtime",
        "carrier": "Outsourced carrier",
        "unserved": "Unserved",
    }
    rows: list[dict[str, object]] = []
    for method in ("private_fleet", "private_overtime", "carrier"):
        selected = [row for row in routes if row.get("fulfillment_method", "private_fleet") == method]
        rows.append({
            "fulfillment_method": method,
            "label": labels[method],
            "deliveries": sum(int(row.get("stop_count", 0)) for row in selected),
            "cases": sum(int(row.get("total_cases", 0)) for row in selected),
            "miles": round(sum(float(row.get("total_miles", 0)) for row in selected), 1),
            "cost": round(sum(float(row.get("total_cost", 0)) for row in selected), 2),
        })
    dropped = unassigned if isinstance(unassigned, list) else []
    rows.append({
        "fulfillment_method": "unserved",
        "label": labels["unserved"],
        "deliveries": len(dropped),
        "cases": 0,
        "miles": 0.0,
        "cost": 0.0,
    })
    return rows
