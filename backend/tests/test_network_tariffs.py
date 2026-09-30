from __future__ import annotations

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.models import NetworkScenarioAssumptions, NetworkTariffRule
from backend.services import network_scenarios
from backend.services.network_scenarios import NetworkScenarioService


client = TestClient(app)


def _network_rows() -> dict[str, list[dict[str, object]]]:
    return {
        "dim_facilities": [
            {
                "facility_id": "DC_MX",
                "facility_type": "distribution_center",
                "country_code": "MX",
                "region_id": "REGION_MX",
            },
            {
                "facility_id": "DPT_US",
                "facility_type": "depot",
                "country_code": "US",
                "region_id": "REGION_TX",
            },
            {
                "facility_id": "DC_US",
                "facility_type": "distribution_center",
                "country_code": "US",
                "region_id": "REGION_TX",
            },
        ],
        "dim_network_lanes": [
            {
                "lane_id": "LNE_MX_US",
                "lane_type": "LINEHAUL",
                "origin_endpoint_id": "DC_MX",
                "destination_endpoint_id": "DPT_US",
                "distance_miles": 100,
            },
            {
                "lane_id": "LNE_US_US",
                "lane_type": "LINEHAUL",
                "origin_endpoint_id": "DC_US",
                "destination_endpoint_id": "DPT_US",
                "distance_miles": 50,
            },
        ],
    }


def test_tariff_rule_contract_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        NetworkTariffRule(
            rule_id="bad-date",
            origin_country="MX",
            destination_country="US",
            effective_start="2026-09-30",
            effective_end="2026-09-29",
            amount_per_case=1,
        )
    with pytest.raises(ValidationError):
        NetworkScenarioAssumptions.model_validate(
            {
                "tariffs": [
                    {
                        "rule_id": "bad-country",
                        "origin_country": "GB",
                        "destination_country": "US",
                        "effective_start": "2026-09-21",
                        "effective_end": "2026-09-22",
                        "amount_per_case": 1,
                    }
                ]
            }
        )


def test_resolve_tariffs_is_directed_and_date_bounded() -> None:
    rule = NetworkTariffRule(
        rule_id="MX_US_2026",
        origin_country="MX",
        destination_country="US",
        effective_start="2026-09-22",
        effective_end="2026-09-23",
        amount_per_case=3.25,
    )

    resolved = NetworkScenarioService._resolve_tariffs(
        _network_rows(), [rule], "2026-09-21", "2026-09-24"  # type: ignore[arg-type]
    )

    assert resolved == {
        ("2026-09-22", "LNE_MX_US"): (3.25, "MX_US_2026"),
        ("2026-09-23", "LNE_MX_US"): (3.25, "MX_US_2026"),
    }


def test_tariff_charge_is_separate_and_reconciles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(network_scenarios, "list_rate_contract_details", lambda _store: [])
    service = NetworkScenarioService()

    cost_rows, charges, _ = service._rate_flows(
        _network_rows(),  # type: ignore[arg-type]
        [
            {
                "service_date": "2026-09-22",
                "lane_id": "LNE_MX_US",
                "assigned_units": 40,
            }
        ],
        {("2026-09-22", "LNE_MX_US"): (3.25, "MX_US_2026")},
    )

    assert len(charges) == 1
    charge = charges[0]
    assert charge.tariff_total == 130
    assert charge.tariff_rule_ids == ["MX_US_2026"]
    assert charge.total_cost == charge.freight_total + charge.tariff_total
    assert cost_rows[0]["total_cost"] == charge.total_cost


def test_validation_rejects_overlapping_directed_tariffs() -> None:
    options = client.get("/api/network/options").json()
    start = options["default_horizon_start"]
    middle = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
    end = (date.fromisoformat(start) + timedelta(days=2)).isoformat()
    created = client.post(
        "/api/network/scenarios",
        json={
            "scenario_name": "Overlapping tariffs",
            "demand_plan_version_id": options["default_demand_plan_version_id"],
            "capacity_plan_version_id": options["default_capacity_plan_version_id"],
            "horizon_start": start,
            "horizon_end": end,
            "assumptions": {
                "tariffs": [
                    {
                        "rule_id": "MX_US_A",
                        "origin_country": "MX",
                        "destination_country": "US",
                        "effective_start": start,
                        "effective_end": middle,
                        "amount_per_case": 2,
                    },
                    {
                        "rule_id": "MX_US_B",
                        "origin_country": "MX",
                        "destination_country": "US",
                        "effective_start": middle,
                        "effective_end": end,
                        "amount_per_case": 3,
                    },
                ]
            },
        },
    )
    assert created.status_code == 201

    validated = client.post(
        f"/api/network/scenarios/{created.json()['scenario_id']}/validate"
    ).json()

    assert validated["validation"]["valid"] is False
    assert any(
        issue["code"] == "overlapping_tariff_rules"
        for issue in validated["validation"]["issues"]
    )


def test_run_reports_tariff_economics_separately() -> None:
    options = client.get("/api/network/options").json()
    start = options["default_horizon_start"]
    end = (date.fromisoformat(start) + timedelta(days=2)).isoformat()
    common = {
        "demand_plan_version_id": options["default_demand_plan_version_id"],
        "capacity_plan_version_id": options["default_capacity_plan_version_id"],
        "horizon_start": start,
        "horizon_end": end,
        "region_id": "REGION_TOLA",
    }
    baseline_created = client.post(
        "/api/network/scenarios",
        json={"scenario_name": "TOLA no tariff", **common},
    )
    baseline_result = client.post(
        f"/api/network/scenarios/{baseline_created.json()['scenario_id']}/run"
    ).json()["result"]
    created = client.post(
        "/api/network/scenarios",
        json={
            "scenario_name": "Mexico to US tariff",
            **common,
            "assumptions": {
                "tariffs": [
                    {
                        "rule_id": "MX_US_TEST",
                        "origin_country": "MX",
                        "destination_country": "US",
                        "effective_start": start,
                        "effective_end": end,
                        "amount_per_case": 0.1,
                    }
                ]
            },
        },
    )
    result = client.post(
        f"/api/network/scenarios/{created.json()['scenario_id']}/run"
    ).json()["result"]
    tariff_charges = [
        row for row in result["charge_details"] if row["tariff_rule_ids"]
    ]

    assert tariff_charges
    assert baseline_result["cross_border_assigned_units"] > result[
        "cross_border_assigned_units"
    ]
    assert result["baseline_cross_border_assigned_units"] == baseline_result[
        "cross_border_assigned_units"
    ]
    assert result["overview"]["kpis"]["unmet_units"] == 0
    assert result["cross_border_assigned_units"] > 0
    assert result["domestic_shift_units"] > 0
    assert all(row["tariff_rule_ids"] == ["MX_US_TEST"] for row in tariff_charges)
    assert all(
        row["tariff_total"] == round(row["assigned_units"] * 0.1, 2)
        for row in tariff_charges
    )
    assert all(row["freight_total"] == row["loads"] * 450 for row in tariff_charges)
    assert result["tariff_total_cost"] == sum(
        row["tariff_total"] for row in result["charge_details"]
    )
    assert result["baseline_tariff_exposure"] == round(
        result["baseline_cross_border_assigned_units"] * 0.1, 2
    )
    assert result["cross_border_assigned_units"] >= sum(
        row["assigned_units"] for row in tariff_charges
    )
    assert isinstance(result["domestic_shift_units"], int)

    updated = client.patch(
        f"/api/network/scenarios/{created.json()['scenario_id']}",
        json={
            "assumptions": {
                "tariffs": [
                    {
                        "rule_id": "MX_US_TEST",
                        "origin_country": "MX",
                        "destination_country": "US",
                        "effective_start": start,
                        "effective_end": end,
                        "amount_per_case": 5,
                    }
                ]
            }
        },
    )
    assert updated.status_code == 200
    high_tariff = client.post(
        f"/api/network/scenarios/{created.json()['scenario_id']}/run"
    ).json()["result"]
    assert high_tariff["tariff_total_cost"] == 0
    assert high_tariff["baseline_tariff_exposure"] == (
        high_tariff["baseline_cross_border_assigned_units"] * 5
    )
    assert high_tariff["domestic_shift_units"] > 0
