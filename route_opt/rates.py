from __future__ import annotations

import hashlib
import math
import uuid
from datetime import date, datetime, timezone
from typing import Any


def _as_date(value: object | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _in_effect(service_date: date, start: object | None, end: object | None) -> bool:
    lower = _as_date(start)
    upper = _as_date(end)
    return (lower is None or lower <= service_date) and (upper is None or service_date <= upper)


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def contract_detail_from_legacy(
    contract: dict[str, object],
    carrier_name: str,
    *,
    freshness_at: str | None = None,
) -> dict[str, object]:
    """Expand the original flat contract into an auditable v1 rate book.

    Existing Lakebase deployments can therefore adopt the richer UI and rate
    engine before their legacy rows are migrated into the normalized child
    tables. The generated IDs are stable and are persisted on every quote.
    """

    contract_id = str(contract["contract_id"])
    capacity = max(1, int(contract.get("capacity_stops", 1)))
    rate_per_mile = float(contract.get("rate_per_mile", 0))
    rate_per_stop = float(contract.get("rate_per_stop", 0))
    minimum = float(contract.get("minimum_charge", 0))
    version_id = f"{contract_id}_V1"
    freshness = freshness_at or datetime.now(timezone.utc).isoformat()
    effective_start = contract.get("effective_start")
    effective_end = contract.get("effective_end")

    return {
        "contract_id": contract_id,
        "carrier_id": str(contract["carrier_id"]),
        "carrier_name": carrier_name,
        "contract_name": str(contract["contract_name"]),
        "version": {
            "version_id": version_id,
            "version_number": 1,
            "status": "published",
            "currency": "USD",
            "effective_start": str(effective_start) if effective_start else None,
            "effective_end": str(effective_end) if effective_end else None,
            "published_at": str(effective_start) if effective_start else freshness,
            "published_by": "Transportation Procurement",
        },
        "lane_rates": [
            {
                "rule_id": f"{contract_id}_LANE_NORTH",
                "lane_name": "North Depot → North Metro",
                "origin": "DPT_NORTH",
                "destination": "North Metro",
                "priority": 200,
                "flat_rate": _money(max(50.0, minimum * 0.22)),
                "rate_per_mile": rate_per_mile,
                "rate_per_stop": rate_per_stop,
                "included_stops": 1,
                "minimum_charge": minimum,
                "mileage_rounding": "up_to_mile",
            },
            {
                "rule_id": f"{contract_id}_LANE_REGIONAL",
                "lane_name": "Great Lakes regional fallback",
                "origin": "*",
                "destination": "*",
                "priority": 10,
                "flat_rate": _money(max(75.0, minimum * 0.28)),
                "rate_per_mile": _money(rate_per_mile * 1.05),
                "rate_per_stop": rate_per_stop,
                "included_stops": 0,
                "minimum_charge": _money(minimum * 1.1),
                "mileage_rounding": "up_to_mile",
            },
        ],
        "fuel_surcharges": [
            {
                "rule_id": f"{contract_id}_FUEL_1",
                "name": "Published diesel surcharge",
                "rate_pct": float(contract.get("fuel_surcharge_pct", 0)),
                "basis": "linehaul_and_minimum",
                "effective_start": str(effective_start) if effective_start else None,
                "effective_end": str(effective_end) if effective_end else None,
            }
        ],
        "accessorials": [
            {
                "rule_id": f"{contract_id}_ACC_LIFTGATE",
                "code": "LIFTGATE",
                "name": "Liftgate service",
                "charge_type": "flat",
                "rate": 65.0,
                "description": "Applied once when a route requires liftgate equipment.",
            },
            {
                "rule_id": f"{contract_id}_ACC_INSIDE",
                "code": "INSIDE_DELIVERY",
                "name": "Inside delivery",
                "charge_type": "per_stop",
                "rate": 32.0,
                "description": "Applied for each stop requiring inside delivery.",
            },
            {
                "rule_id": f"{contract_id}_ACC_DETENTION",
                "code": "DETENTION",
                "name": "Detention",
                "charge_type": "per_hour",
                "rate": 85.0,
                "description": "Applied to approved detention hours after free time.",
            },
        ],
        "volume_tiers": [
            {
                "rule_id": f"{contract_id}_TIER_1",
                "name": "Base monthly tier",
                "period": "month",
                "unit": "stops",
                "min_volume": 0,
                "max_volume": 49,
                "discount_pct": 0,
            },
            {
                "rule_id": f"{contract_id}_TIER_2",
                "name": "50–99 monthly stops",
                "period": "month",
                "unit": "stops",
                "min_volume": 50,
                "max_volume": 99,
                "discount_pct": 2,
            },
            {
                "rule_id": f"{contract_id}_TIER_3",
                "name": "100+ monthly stops",
                "period": "month",
                "unit": "stops",
                "min_volume": 100,
                "max_volume": None,
                "discount_pct": 4,
            },
        ],
        "capacity_commitments": [
            {
                "rule_id": f"{contract_id}_COMMIT_1",
                "name": "Monthly reserved stop capacity",
                "period": "month",
                "unit": "stops",
                "committed_quantity": capacity * 3,
                "capacity_quantity": capacity * 5,
                "current_utilization": capacity * 2,
                "shortfall_rate": 12.0,
                "overage_rate": 18.0,
            }
        ],
        "source": "Lakebase rate book",
        "freshness_at": freshness,
    }


def contract_status(detail: dict[str, object], service_date: str) -> str:
    as_of = _as_date(service_date)
    if as_of is None:
        raise ValueError("A service date is required to resolve a contract version.")
    version = detail["version"]
    if not isinstance(version, dict):
        return "draft"
    start = _as_date(version.get("effective_start"))
    end = _as_date(version.get("effective_end"))
    if end is not None and as_of > end:
        return "expired"
    if start is not None and as_of < start:
        return "draft"
    return str(version.get("status", "published"))


def contract_summary(detail: dict[str, object], service_date: str) -> dict[str, object]:
    commitments = detail.get("capacity_commitments") or []
    commitment = commitments[0] if commitments and isinstance(commitments[0], dict) else {}
    status = contract_status(detail, service_date)
    return {
        "contract_id": detail["contract_id"],
        "carrier_id": detail["carrier_id"],
        "carrier_name": detail["carrier_name"],
        "contract_name": detail["contract_name"],
        "version": detail["version"],
        "status": status,
        "lane_count": len(detail.get("lane_rates") or []),
        "accessorial_count": len(detail.get("accessorials") or []),
        "volume_tier_count": len(detail.get("volume_tiers") or []),
        "committed_quantity": float(commitment.get("committed_quantity", 0)),
        "capacity_quantity": float(commitment.get("capacity_quantity", 0)),
        "current_utilization": float(commitment.get("current_utilization", 0)),
        "coverage_status": "covered" if status == "published" and detail.get("lane_rates") else "unavailable",
        "freshness_at": detail["freshness_at"],
    }


def _matches(expected: object, actual: str) -> bool:
    value = str(expected).strip()
    return value == "*" or value.casefold() == actual.strip().casefold()


def _lane_rule(detail: dict[str, object], origin: str, destination: str) -> dict[str, object] | None:
    rules = [row for row in detail.get("lane_rates", []) if isinstance(row, dict)]
    matches = [
        row
        for row in rules
        if _matches(row.get("origin", "*"), origin)
        and _matches(row.get("destination", "*"), destination)
    ]
    if not matches:
        return None
    return max(
        matches,
        key=lambda row: (
            int(row.get("priority", 0)),
            int(row.get("origin") != "*") + int(row.get("destination") != "*"),
        ),
    )


def _rounded_miles(miles: float, method: object) -> float:
    if method == "nearest_mile":
        return float(round(miles))
    if method == "up_to_mile":
        return float(math.ceil(miles))
    return round(miles, 3)


def _line(
    category: str,
    label: str,
    formula: str,
    quantity: float,
    unit: str,
    rate: float,
    amount: float,
    rule_id: object,
) -> dict[str, object]:
    return {
        "category": category,
        "label": label,
        "formula": formula,
        "quantity": round(quantity, 3),
        "unit": unit,
        "rate": round(rate, 4),
        "amount": _money(amount),
        "rule_id": str(rule_id),
    }


def quote_contract(detail: dict[str, object], request: dict[str, object]) -> dict[str, object]:
    service_date_text = str(request.get("service_date", ""))
    service_date = _as_date(service_date_text)
    if service_date is None:
        raise ValueError("A service date is required.")
    version = detail["version"]
    if not isinstance(version, dict):
        raise ValueError("Contract version is invalid.")
    version_id = str(version["version_id"])
    snapshot_seed = f"{detail['contract_id']}|{version_id}|{service_date_text}"
    snapshot_id = "ratebook_" + hashlib.sha256(snapshot_seed.encode()).hexdigest()[:12]
    base_response: dict[str, object] = {
        "quote_id": f"quote_{uuid.uuid4().hex[:12]}",
        "contract_id": detail["contract_id"],
        "contract_name": detail["contract_name"],
        "carrier_id": detail["carrier_id"],
        "carrier_name": detail["carrier_name"],
        "contract_version_id": version_id,
        "service_date": service_date_text,
        "origin": str(request.get("origin", "")),
        "destination": str(request.get("destination", "")),
        "matched_lane": None,
        "matched_lane_rule_id": None,
        "matched_volume_tier": None,
        "eligible": False,
        "eligibility_message": "",
        "charge_lines": [],
        "transportation_subtotal": 0,
        "total_cost": 0,
        "commitment_remaining": 0,
        "capacity_remaining": 0,
        "rate_book_snapshot_id": snapshot_id,
        "warnings": [],
    }

    if not _in_effect(service_date, version.get("effective_start"), version.get("effective_end")):
        base_response["eligibility_message"] = "The contract version is not effective on the selected service date."
        return base_response

    lane = _lane_rule(
        detail,
        str(request.get("origin", "")),
        str(request.get("destination", "")),
    )
    if lane is None:
        base_response["eligibility_message"] = "No published lane rule covers this origin and destination."
        return base_response

    miles = _rounded_miles(float(request.get("miles", 0)), lane.get("mileage_rounding"))
    stops = max(0, int(request.get("stops", 0)))
    cases = max(0, int(request.get("cases", 0)))
    period_volume = max(float(request.get("period_volume", 0)), float(stops))
    lines: list[dict[str, object]] = []

    flat_rate = float(lane.get("flat_rate", 0))
    mileage_rate = float(lane.get("rate_per_mile", 0))
    stop_rate = float(lane.get("rate_per_stop", 0))
    billable_stops = max(0, stops - int(lane.get("included_stops", 0)))
    lane_amount = flat_rate
    mileage_amount = miles * mileage_rate
    stop_amount = billable_stops * stop_rate
    lines.append(_line("lane", "Lane base", f"1 lane × ${flat_rate:,.2f}", 1, "lane", flat_rate, lane_amount, lane["rule_id"]))
    lines.append(_line("mileage", "Billable mileage", f"{miles:g} mi × ${mileage_rate:,.2f}", miles, "mile", mileage_rate, mileage_amount, lane["rule_id"]))
    lines.append(_line("stops", "Stop charges", f"{billable_stops} billable stops × ${stop_rate:,.2f}", billable_stops, "stop", stop_rate, stop_amount, lane["rule_id"]))
    base_subtotal = lane_amount + mileage_amount + stop_amount

    tiers = [row for row in detail.get("volume_tiers", []) if isinstance(row, dict)]
    tier = next(
        (
            row
            for row in sorted(tiers, key=lambda item: float(item.get("min_volume", 0)), reverse=True)
            if period_volume >= float(row.get("min_volume", 0))
            and (row.get("max_volume") is None or period_volume <= float(row["max_volume"]))
        ),
        None,
    )
    volume_adjustment = 0.0
    if tier is not None:
        discount_pct = float(tier.get("discount_pct", 0))
        volume_adjustment = -(base_subtotal * discount_pct / 100)
        lines.append(
            _line(
                "volume_tier",
                str(tier["name"]),
                f"-{discount_pct:g}% × ${base_subtotal:,.2f}",
                period_volume,
                str(tier.get("unit", "stops")),
                -discount_pct,
                volume_adjustment,
                tier["rule_id"],
            )
        )

    discounted_subtotal = base_subtotal + volume_adjustment
    minimum = float(lane.get("minimum_charge", 0))
    minimum_adjustment = max(0.0, minimum - discounted_subtotal)
    lines.append(
        _line(
            "minimum",
            "Minimum-charge adjustment",
            f"max($0, ${minimum:,.2f} − ${discounted_subtotal:,.2f})",
            1,
            "route",
            minimum,
            minimum_adjustment,
            lane["rule_id"],
        )
    )
    transportation_subtotal = discounted_subtotal + minimum_adjustment

    fuel_amount = 0.0
    fuel_rules = [row for row in detail.get("fuel_surcharges", []) if isinstance(row, dict)]
    fuel_rule = next(
        (
            row
            for row in fuel_rules
            if _in_effect(service_date, row.get("effective_start"), row.get("effective_end"))
        ),
        None,
    )
    if fuel_rule is not None:
        basis_name = str(fuel_rule.get("basis", "linehaul_and_minimum"))
        if basis_name == "linehaul":
            fuel_basis = lane_amount + mileage_amount
        elif basis_name == "transportation_subtotal":
            fuel_basis = transportation_subtotal
        else:
            fuel_basis = lane_amount + mileage_amount + minimum_adjustment
        fuel_rate = float(fuel_rule.get("rate_pct", 0))
        fuel_amount = fuel_basis * fuel_rate / 100
        lines.append(_line("fuel", str(fuel_rule["name"]), f"{fuel_rate:g}% × ${fuel_basis:,.2f} {basis_name.replace('_', ' ')}", fuel_basis, "USD", fuel_rate, fuel_amount, fuel_rule["rule_id"]))

    accessorial_total = 0.0
    selected_codes = {str(code).upper() for code in request.get("accessorial_codes", []) if code}
    quantities_raw = request.get("accessorial_quantities")
    quantities = quantities_raw if isinstance(quantities_raw, dict) else {}
    for rule in [row for row in detail.get("accessorials", []) if isinstance(row, dict)]:
        code = str(rule.get("code", "")).upper()
        if code not in selected_codes:
            continue
        charge_type = str(rule.get("charge_type", "flat"))
        if charge_type == "per_stop":
            quantity, unit = float(quantities.get(code, stops)), "stop"
        elif charge_type == "per_hour":
            quantity, unit = float(quantities.get(code, 1)), "hour"
        elif charge_type == "per_case":
            quantity, unit = float(quantities.get(code, cases)), "case"
        else:
            quantity, unit = float(quantities.get(code, 1)), "route"
        rate = float(rule.get("rate", 0))
        amount = quantity * rate
        accessorial_total += amount
        lines.append(_line("accessorial", str(rule["name"]), f"{quantity:g} {unit} × ${rate:,.2f}", quantity, unit, rate, amount, rule["rule_id"]))

    commitment_total = 0.0
    commitment_remaining = 0.0
    capacity_remaining = 0.0
    warnings: list[str] = []
    commitments = [row for row in detail.get("capacity_commitments", []) if isinstance(row, dict)]
    commitment = commitments[0] if commitments else None
    if commitment is not None:
        committed = float(commitment.get("committed_quantity", 0))
        capacity = float(commitment.get("capacity_quantity", 0))
        current = float(commitment.get("current_utilization", 0))
        projected = max(period_volume, current + float(stops))
        commitment_remaining = max(0.0, committed - projected)
        capacity_remaining = max(0.0, capacity - projected)
        commitment_policy = str(request.get("commitment_policy", "honor"))
        if commitment_policy == "ignore":
            quantity = 0.0
            rate = 0.0
            formula = "Commitment rules ignored for this what-if"
        elif projected > capacity:
            warnings.append(f"Projected {projected:g} stops exceed contracted capacity of {capacity:g}.")
            quantity = projected - max(committed, current)
            rate = float(commitment.get("overage_rate", 0))
            commitment_total = max(0.0, quantity) * rate
            formula = f"{max(0.0, quantity):g} stops above commitment × ${rate:,.2f}"
        elif bool(request.get("period_close")) and projected < committed:
            quantity = committed - projected
            rate = float(commitment.get("shortfall_rate", 0))
            commitment_total = quantity * rate
            formula = f"{quantity:g} stop shortfall × ${rate:,.2f}"
        elif projected > committed:
            quantity = projected - max(committed, current)
            rate = float(commitment.get("overage_rate", 0))
            commitment_total = max(0.0, quantity) * rate
            formula = f"{max(0.0, quantity):g} stops above commitment × ${rate:,.2f}"
        else:
            quantity = 0.0
            rate = float(commitment.get("overage_rate", 0))
            formula = "Within committed capacity"
        lines.append(_line("commitment", str(commitment["name"]), formula, quantity, str(commitment.get("unit", "stops")), rate, commitment_total, commitment["rule_id"]))

    total = transportation_subtotal + fuel_amount + accessorial_total + commitment_total
    base_response.update(
        {
            "matched_lane": lane["lane_name"],
            "matched_lane_rule_id": lane["rule_id"],
            "matched_volume_tier": tier["name"] if tier else None,
            "eligible": not warnings,
            "eligibility_message": "Eligible published contract and lane rules matched." if not warnings else warnings[0],
            "charge_lines": lines,
            "transportation_subtotal": _money(transportation_subtotal),
            "total_cost": _money(total),
            "commitment_remaining": round(commitment_remaining, 2),
            "capacity_remaining": round(capacity_remaining, 2),
            "warnings": warnings,
        }
    )
    return base_response
