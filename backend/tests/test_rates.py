from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import (
    RateContractCreateRequest,
    RateDraftUpdateRequest,
    RatePublishRequest,
    RateQuoteRequest,
    RateVersionCreateRequest,
    ScenarioCreateRequest,
)
from backend.services.rates import (
    create_rate_contract,
    create_rate_version,
    discard_rate_draft,
    get_rate_contract_detail,
    preview_rate_quote,
    publish_rate_draft,
    save_rate_draft,
    validate_rate_draft,
)
from backend.services.stub_store import StubStore
from route_opt.rates import contract_detail_from_legacy, quote_contract
from route_opt.transportation import resolve_transportation_choices


client = TestClient(app)


def test_rate_contract_api_exposes_versioned_rule_families() -> None:
    response = client.get("/api/rates/contracts", params={"service_date": "2026-09-16"})
    assert response.status_code == 200
    contracts = response.json()
    assert contracts
    assert contracts[0]["version"]["status"] == "published"
    assert contracts[0]["lane_count"] >= 2

    detail = client.get(
        f"/api/rates/contracts/{contracts[0]['contract_id']}/versions/{contracts[0]['version']['version_id']}"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["lane_rates"]
    assert payload["fuel_surcharges"]
    assert payload["accessorials"]
    assert payload["volume_tiers"]
    assert payload["capacity_commitments"]
    assert payload["version_history"]


def test_rate_authoring_options_are_governed_by_existing_rate_books() -> None:
    response = client.get("/api/rates/authoring-options")
    assert response.status_code == 200
    payload = response.json()
    assert "North Metro" in payload["destinations"]
    assert {row["code"] for row in payload["accessorials"]} >= {
        "LIFTGATE",
        "INSIDE_DELIVERY",
        "DETENTION",
    }


def test_quote_api_returns_transparent_charge_ledger() -> None:
    response = client.post(
        "/api/rates/quote",
        json={
            "contract_id": "GL_STANDARD_2026",
            "service_date": "2026-09-16",
            "origin": "DPT_NORTH",
            "destination": "North Metro",
            "miles": 70.4,
            "stops": 6,
            "cases": 720,
            "period_volume": 54,
            "accessorial_codes": ["LIFTGATE", "DETENTION"],
            "accessorial_quantities": {"DETENTION": 1.5},
        },
    )
    assert response.status_code == 200
    quote = response.json()
    assert quote["eligible"] is True
    assert quote["matched_lane"] == "North Depot → North Metro"
    categories = {line["category"] for line in quote["charge_lines"]}
    assert {
        "lane",
        "mileage",
        "stops",
        "volume_tier",
        "minimum",
        "fuel",
        "accessorial",
        "commitment",
    } <= categories
    assert sum(line["amount"] for line in quote["charge_lines"]) == quote["total_cost"]


def test_effective_date_and_capacity_rules_can_make_quote_ineligible() -> None:
    detail = contract_detail_from_legacy(
        {
            "contract_id": "CONTRACT",
            "carrier_id": "CARRIER",
            "contract_name": "Contract",
            "capacity_stops": 10,
            "rate_per_mile": 4,
            "rate_per_stop": 20,
            "minimum_charge": 200,
            "fuel_surcharge_pct": 10,
            "effective_start": "2026-01-01",
            "effective_end": "2026-12-31",
        },
        "Carrier",
    )
    outside = quote_contract(
        detail,
        {
            "service_date": "2027-01-01",
            "origin": "DPT_NORTH",
            "destination": "North Metro",
            "miles": 20,
            "stops": 3,
        },
    )
    assert outside["eligible"] is False
    assert "not effective" in str(outside["eligibility_message"])

    over_capacity = quote_contract(
        detail,
        {
            "service_date": "2026-06-01",
            "origin": "DPT_NORTH",
            "destination": "North Metro",
            "miles": 20,
            "stops": 3,
            "period_volume": 51,
        },
    )
    assert over_capacity["eligible"] is False
    assert over_capacity["warnings"]

    ignored = quote_contract(
        detail,
        {
            "service_date": "2026-06-01",
            "origin": "DPT_NORTH",
            "destination": "North Metro",
            "miles": 20,
            "stops": 3,
            "period_volume": 51,
            "commitment_policy": "ignore",
        },
    )
    assert ignored["eligible"] is True
    assert ignored["warnings"] == []
    commitment_line = next(
        line for line in ignored["charge_lines"] if line["category"] == "commitment"
    )
    assert commitment_line["amount"] == 0
    assert "ignored" in str(commitment_line["formula"]).lower()


def test_transportation_resolution_uses_rich_version_and_empty_pool_means_all() -> None:
    carriers = [
        {"carrier_id": "A", "carrier_name": "Carrier A", "active": True},
        {"carrier_id": "B", "carrier_name": "Carrier B", "active": True},
    ]
    contracts = [
        {
            "contract_id": carrier,
            "carrier_id": carrier,
            "contract_name": f"Contract {carrier}",
            "capacity_stops": 10,
            "rate_per_mile": 4,
            "rate_per_stop": 20,
            "minimum_charge": 200,
            "fuel_surcharge_pct": 10,
            "effective_start": "2026-01-01",
            "effective_end": "2026-12-31",
            "active": True,
        }
        for carrier in ("A", "B")
    ]
    rich = contract_detail_from_legacy(contracts[0], "Carrier A")
    rich["version"]["version_id"] = "A_V2"
    rich["version"]["version_number"] = 2
    rich["lane_rates"][0]["flat_rate"] = 999

    resolved = resolve_transportation_choices(
        {
            "transportation_choices": {
                "allow_carrier": True,
                "contract_selection": "automatic",
                "carrier_id": "A",
                "eligible_carrier_ids": [],
            },
            "pricing_context": {"service_date": "2026-09-16"},
        },
        carriers,
        contracts,
        [rich],
    )

    candidates = resolved["candidate_contracts"]
    assert len(candidates) == 2
    rich_candidate = next(
        candidate
        for candidate in candidates
        if candidate["contract"]["contract_id"] == "A"
    )
    assert rich_candidate["detail"]["version"]["version_id"] == "A_V2"
    assert rich_candidate["detail"]["lane_rates"][0]["flat_rate"] == 999


def test_complete_contract_draft_to_publish_lifecycle() -> None:
    store = StubStore()
    draft = create_rate_contract(
        store,
        RateContractCreateRequest(
            carrier_id="GL_LOGISTICS",
            contract_name="Great Lakes Dedicated 2027",
            currency="USD",
            effective_start="2027-01-01",
            effective_end="2027-12-31",
        ),
    )
    assert draft.version.status == "draft"
    assert draft.version.version_number == 1

    contract_id = draft.contract_id
    version_id = draft.version.version_id
    saved = save_rate_draft(
        store,
        contract_id,
        version_id,
        RateDraftUpdateRequest(
            contract_name=draft.contract_name,
            currency="USD",
            effective_start="2027-01-01",
            effective_end="2027-12-31",
            change_reason="Initial dedicated agreement",
            lane_rates=[
                {
                    "rule_id": f"{version_id}_LANE_1",
                    "lane_name": "North Depot to Central",
                    "origin": "DPT_NORTH",
                    "destination": "Central Metro",
                    "priority": 200,
                    "flat_rate": 100,
                    "rate_per_mile": 3.5,
                    "rate_per_stop": 25,
                    "included_stops": 1,
                    "minimum_charge": 300,
                    "mileage_rounding": "up_to_mile",
                }
            ],
            fuel_surcharges=[
                {
                    "rule_id": f"{version_id}_FUEL_1",
                    "name": "2027 diesel schedule",
                    "rate_pct": 10,
                    "basis": "linehaul_and_minimum",
                    "effective_start": "2027-01-01",
                    "effective_end": "2027-12-31",
                }
            ],
            accessorials=[
                {
                    "rule_id": f"{version_id}_ACC_1",
                    "code": "LIFTGATE",
                    "name": "Liftgate",
                    "charge_type": "flat",
                    "rate": 55,
                    "description": "Applied once when liftgate equipment is required.",
                }
            ],
            volume_tiers=[
                {
                    "rule_id": f"{version_id}_TIER_1",
                    "name": "Base",
                    "period": "month",
                    "unit": "stops",
                    "min_volume": 0,
                    "max_volume": 49,
                    "discount_pct": 0,
                },
                {
                    "rule_id": f"{version_id}_TIER_2",
                    "name": "50+ stops",
                    "period": "month",
                    "unit": "stops",
                    "min_volume": 50,
                    "max_volume": None,
                    "discount_pct": 3,
                },
            ],
            capacity_commitments=[
                {
                    "rule_id": f"{version_id}_COMMIT_1",
                    "name": "Monthly stop commitment",
                    "period": "month",
                    "unit": "stops",
                    "committed_quantity": 60,
                    "capacity_quantity": 100,
                    "current_utilization": 40,
                    "shortfall_rate": 8,
                    "overage_rate": 12,
                }
            ],
        ),
    )
    assert len(saved.lane_rates) == 1
    assert len(saved.fuel_surcharges) == 1
    assert len(saved.accessorials) == 1
    assert len(saved.volume_tiers) == 2
    assert len(saved.capacity_commitments) == 1

    validation = validate_rate_draft(store, contract_id, version_id)
    assert validation.valid is True
    assert validation.issues == []

    published = publish_rate_draft(
        store,
        contract_id,
        version_id,
        RatePublishRequest(published_by="Test rate manager"),
    )
    assert published.version.status == "published"
    assert published.version.published_by == "Test rate manager"

    quote = preview_rate_quote(
        store,
        RateQuoteRequest(
            contract_id=contract_id,
            version_id=version_id,
            service_date="2027-04-10",
            origin="DPT_NORTH",
            destination="Central Metro",
            miles=40,
            stops=5,
            cases=300,
            period_volume=65,
            accessorial_codes=["LIFTGATE"],
        ),
    )
    assert quote.eligible is True
    assert {line.category for line in quote.charge_lines} >= {
        "lane",
        "mileage",
        "stops",
        "volume_tier",
        "minimum",
        "fuel",
        "accessorial",
        "commitment",
    }

    try:
        save_rate_draft(
            store,
            contract_id,
            version_id,
            RateDraftUpdateRequest(
                contract_name="Cannot change",
                currency="USD",
                effective_start="2027-01-01",
                effective_end="2027-12-31",
                change_reason="Should fail",
            ),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:  # pragma: no cover - protects the immutability invariant
        raise AssertionError("Published version unexpectedly accepted an edit")


def test_new_version_end_dates_prior_version_and_draft_can_be_discarded() -> None:
    store = StubStore()
    contract_id = "GL_STANDARD_2026"
    created = create_rate_version(
        store,
        contract_id,
        RateVersionCreateRequest(
            source_version_id="GL_STANDARD_2026_V1",
            effective_start="2026-10-01",
            effective_end="2027-09-30",
            change_reason="Fall renewal",
        ),
    )
    updated = RateDraftUpdateRequest(
        contract_name=created.contract_name,
        currency=created.version.currency,
        effective_start="2026-10-01",
        effective_end="2027-09-30",
        change_reason="Fall renewal",
        lane_rates=created.lane_rates,
        fuel_surcharges=[
            row.model_copy(
                update={
                    "effective_start": "2026-10-01",
                    "effective_end": "2027-09-30",
                }
            )
            for row in created.fuel_surcharges
        ],
        accessorials=created.accessorials,
        volume_tiers=created.volume_tiers,
        capacity_commitments=created.capacity_commitments,
    )
    save_rate_draft(store, contract_id, created.version.version_id, updated)
    validation = validate_rate_draft(store, contract_id, created.version.version_id)
    assert validation.valid is True
    assert any(issue.code == "prior_version_will_close" for issue in validation.issues)

    publish_rate_draft(
        store,
        contract_id,
        created.version.version_id,
        RatePublishRequest(published_by="Test rate manager"),
    )
    prior = get_rate_contract_detail(store, contract_id, "GL_STANDARD_2026_V1")
    assert prior.version.status == "published"
    assert prior.version.effective_end == "2026-09-30"

    scenario, _ = store.create_scenario(
        ScenarioCreateRequest(
            scenario_name="Published rate resolution",
            scenario_type="driver_count_change",
            baseline_scenario_id="baseline",
            depot_id="DPT_NORTH",
            delivery_day="Tuesday",
            parameters={
                "driver_delta": -1,
                "allow_overtime": True,
                "transportation_choices": {
                    "allow_carrier": True,
                    "contract_selection": "locked",
                    "carrier_id": "GL_LOGISTICS",
                    "contract_id": contract_id,
                    "eligible_carrier_ids": [],
                    "accessorial_codes": [],
                },
                "pricing_context": {
                    "service_date": "2026-11-01",
                    "projected_period_stops": 30,
                },
            },
        )
    )
    result = store.get_scenario_result(scenario.scenario_id)
    carrier_routes = [
        route for route in result.scenario_routes if route.fulfillment_method == "carrier"
    ]
    assert carrier_routes
    assert carrier_routes[0].contract_version_id == created.version.version_id

    next_draft = create_rate_version(
        store,
        contract_id,
        RateVersionCreateRequest(
            source_version_id=created.version.version_id,
            effective_start="2027-10-01",
            effective_end="2028-09-30",
            change_reason="Future renewal",
        ),
    )
    discard_rate_draft(store, contract_id, next_draft.version.version_id)
    assert all(
        row.version.version_id != next_draft.version.version_id
        for row in store.list_rate_contract_details()
    )


def test_validation_rejects_cross_rule_errors_without_publishing() -> None:
    store = StubStore()
    draft = create_rate_contract(
        store,
        RateContractCreateRequest(
            carrier_id="GL_LOGISTICS",
            contract_name="Invalid draft",
            currency="USD",
            effective_start="2027-01-01",
            effective_end="2027-12-31",
        ),
    )
    save_rate_draft(
        store,
        draft.contract_id,
        draft.version.version_id,
        RateDraftUpdateRequest(
            contract_name=draft.contract_name,
            currency="USD",
            effective_start="2027-01-01",
            effective_end="2027-12-31",
            change_reason="Invalid on purpose",
            lane_rates=[],
            volume_tiers=[
                {
                    "rule_id": f"{draft.version.version_id}_TIER_1",
                    "name": "Gap",
                    "period": "month",
                    "unit": "stops",
                    "min_volume": 10,
                    "max_volume": None,
                    "discount_pct": 2,
                }
            ],
            capacity_commitments=[
                {
                    "rule_id": f"{draft.version.version_id}_COMMIT_1",
                    "name": "Impossible",
                    "period": "month",
                    "unit": "stops",
                    "committed_quantity": 100,
                    "capacity_quantity": 50,
                    "current_utilization": 0,
                    "shortfall_rate": 1,
                    "overage_rate": 1,
                }
            ],
        ),
    )
    validation = validate_rate_draft(
        store, draft.contract_id, draft.version.version_id
    )
    assert validation.valid is False
    assert {issue.code for issue in validation.issues} >= {
        "required_lane",
        "tier_gap",
        "commitment_above_capacity",
    }
    try:
        publish_rate_draft(
            store,
            draft.contract_id,
            draft.version.version_id,
            RatePublishRequest(),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 422
    else:  # pragma: no cover
        raise AssertionError("Invalid draft unexpectedly published")
    assert get_rate_contract_detail(
        store, draft.contract_id, draft.version.version_id
    ).version.status == "draft"
