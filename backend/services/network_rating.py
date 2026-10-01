from __future__ import annotations

import math
from datetime import date
from dataclasses import dataclass
from typing import Any, Mapping, cast

from route_opt.rates import contract_status, quote_contract

from ..models import (
    NetworkFlowChargeDetail, NetworkTariffRule, RateChargeLine, RateContractDetail,
)
from .network_overview import NetworkRows, estimate_lane_daily_cost
from .rates import governed_linehaul_contract


@dataclass(frozen=True)
class NetworkRatingResult:
    cost_rows: list[dict[str, Any]]
    charge_details: list[NetworkFlowChargeDetail]
    missing_rate_lane_ids: tuple[str, ...]


def resolve_network_tariffs(
    rows: NetworkRows,
    rules: list[NetworkTariffRule],
    horizon_start: str,
    horizon_end: str,
) -> dict[tuple[str, str], tuple[float, str]]:
    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    resolved: dict[tuple[str, str], tuple[float, str]] = {}
    for lane in rows["dim_network_lanes"]:
        if str(lane["lane_type"]) != "LINEHAUL":
            continue
        origin = facilities.get(str(lane["origin_endpoint_id"]))
        destination = facilities.get(str(lane["destination_endpoint_id"]))
        if origin is None or destination is None:
            continue
        for rule in rules:
            if (rule.origin_country, rule.destination_country) != (
                str(origin.get("country_code", "")),
                str(destination.get("country_code", "")),
            ):
                continue
            first = date.fromisoformat(max(horizon_start, rule.effective_start))
            last = date.fromisoformat(min(horizon_end, rule.effective_end))
            while first <= last:
                resolved[(first.isoformat(), str(lane["lane_id"]))] = (
                    rule.amount_per_case, rule.rule_id,
                )
                first = date.fromordinal(first.toordinal() + 1)
    return resolved


def governed_contract_for_date(
    contracts: list[RateContractDetail], service_date: str, region_id: str
) -> RateContractDetail | None:
    """Select only from the caller's frozen contract snapshot."""

    governed = governed_linehaul_contract(region_id)
    if governed is None:
        return None
    candidates = [
        row
        for row in contracts
        if row.contract_id == governed[0]
        and contract_status(row.model_dump(mode="json"), service_date) == "published"
    ]
    return max(candidates, key=lambda row: row.version.version_number, default=None)


def objective_lane_unit_costs(
    rows: NetworkRows,
    service_date: str,
    contracts: list[RateContractDetail],
) -> dict[str, float]:
    """Return linear full-load costs for one date from frozen contracts."""

    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    result: dict[str, float] = {}
    for lane in rows["dim_network_lanes"]:
        if str(lane["lane_type"]) != "LINEHAUL":
            continue
        lane_id = str(lane["lane_id"])
        fallback = max(450.0, float(lane["distance_miles"]) * 3.4) * 1.12 / 900
        origin = facilities.get(str(lane["origin_endpoint_id"]))
        contract = (
            governed_contract_for_date(
                contracts, service_date, str(origin["region_id"])
            )
            if origin is not None
            else None
        )
        if contract is None:
            result[lane_id] = fallback
            continue
        quote = quote_contract(
            contract.model_dump(mode="json"),
            {
                "service_date": service_date,
                "origin": str(lane["origin_endpoint_id"]),
                "destination": str(lane["destination_endpoint_id"]),
                "miles": float(lane["distance_miles"]),
                "stops": 1,
                "cases": 900,
                "period_volume": 1,
                "commitment_policy": "honor",
            },
        )
        result[lane_id] = (
            float(quote["total_cost"]) / 900
            if quote["matched_lane_rule_id"]
            else fallback
        )
    return result


def rate_network_flows(
    rows: NetworkRows,
    flow_rows: list[dict[str, Any]],
    tariff_by_date_lane: Mapping[tuple[str, str], tuple[float, str]],
    *,
    contracts: list[RateContractDetail],
) -> NetworkRatingResult:
    """Rate flows comparably using caller-pinned contracts and tariffs."""

    lanes = {str(row["lane_id"]): row for row in rows["dim_network_lanes"]}
    facilities = {str(row["facility_id"]): row for row in rows["dim_facilities"]}
    cost_rows: list[dict[str, Any]] = []
    charges: list[NetworkFlowChargeDetail] = []
    missing: set[str] = set()

    for flow in flow_rows:
        assigned = int(flow["assigned_units"])
        lane_id = str(flow["lane_id"])
        service_date = str(flow["service_date"])[:10]
        lane = lanes[lane_id]
        freight_total = estimate_lane_daily_cost(lane, assigned)
        rate_source = "planning_fallback"
        contract_id = contract_version_id = snapshot_id = None
        charge_lines: list[RateChargeLine] = []
        loads = math.ceil(assigned / 900) if assigned > 0 else 0
        tariff_rate, tariff_rule_id = tariff_by_date_lane.get(
            (service_date, lane_id), (0.0, "")
        )
        tariff_total = round(assigned * tariff_rate, 2)

        if str(lane["lane_type"]) == "LINEHAUL" and assigned > 0:
            origin = facilities[str(lane["origin_endpoint_id"])]
            contract = governed_contract_for_date(
                contracts, service_date, str(origin["region_id"])
            )
            if contract is not None:
                quote = quote_contract(
                    contract.model_dump(mode="json"),
                    {
                        "service_date": service_date,
                        "origin": str(lane["origin_endpoint_id"]),
                        "destination": str(lane["destination_endpoint_id"]),
                        "miles": float(lane["distance_miles"]),
                        "stops": 1,
                        # Network freight is purchased in whole 900-case loads.
                        # A partial final load therefore uses the same contract
                        # basis as a full load; assigned cases affect only the
                        # number of loads and per-case tariffs.
                        "cases": 900,
                        "period_volume": loads,
                        "commitment_policy": "honor",
                    },
                )
                if quote["matched_lane_rule_id"]:
                    freight_total = round(float(quote["total_cost"]) * loads, 2)
                    rate_source = "governed_contract"
                    contract_id = contract.contract_id
                    contract_version_id = contract.version.version_id
                    snapshot_id = str(quote["rate_book_snapshot_id"])
                    charge_lines = [
                        RateChargeLine.model_validate(
                            {
                                **line,
                                "formula": f"{loads} loads × ({line['formula']})",
                                "quantity": float(line["quantity"]) * loads,
                                "amount": round(float(line["amount"]) * loads, 2),
                            }
                        )
                        for line in cast(list[dict[str, Any]], quote["charge_lines"])
                    ]
                    # The persisted ledger is authoritative. Summing its
                    # individually rounded lines avoids a cent-level mismatch
                    # from multiplying the separately rounded quote total.
                    freight_total = round(
                        sum(line.amount for line in charge_lines), 2
                    )
            if rate_source == "planning_fallback":
                missing.add(lane_id)
                per_load = max(450.0, float(lane["distance_miles"]) * 3.4)
                base = per_load * loads
                fuel = base * 0.12
                freight_total = round(base + fuel, 2)
                charge_lines = [
                    RateChargeLine(
                        category="mileage", label="Planning linehaul estimate",
                        formula=f"{loads} loads × max($450, {float(lane['distance_miles']):,.1f} mi × $3.40)",
                        quantity=loads, unit="load", rate=round(per_load, 4),
                        amount=round(base, 2), rule_id="PLANNING_LINEHAUL_FALLBACK",
                    ),
                    RateChargeLine(
                        category="fuel", label="Planning fuel estimate",
                        formula=f"12% × ${base:,.2f}", quantity=base, unit="USD",
                        rate=12, amount=round(fuel, 2), rule_id="PLANNING_FUEL_FALLBACK",
                    ),
                ]
                freight_total = round(sum(line.amount for line in charge_lines), 2)
            charges.append(
                NetworkFlowChargeDetail(
                    service_date=service_date, lane_id=lane_id,
                    assigned_units=assigned, loads=loads,
                    rate_source=cast(Any, rate_source), contract_id=contract_id,
                    contract_version_id=contract_version_id,
                    rate_book_snapshot_id=snapshot_id,
                    freight_total=round(freight_total, 2), tariff_total=tariff_total,
                    tariff_rule_ids=[tariff_rule_id] if tariff_rule_id else [],
                    total_cost=round(freight_total + tariff_total, 2),
                    charge_lines=charge_lines,
                )
            )

        cost_rows.append(
            {
                "service_date": service_date, "lane_id": lane_id,
                "freight_total": round(freight_total, 2),
                "tariff_total": tariff_total,
                "tariff_rule_ids": [tariff_rule_id] if tariff_rule_id else [],
                "total_cost": round(freight_total + tariff_total, 2),
                "rate_source": rate_source, "contract_id": contract_id,
                "contract_version_id": contract_version_id,
                "rate_book_snapshot_id": snapshot_id,
            }
        )
    return NetworkRatingResult(cost_rows, charges, tuple(sorted(missing)))
