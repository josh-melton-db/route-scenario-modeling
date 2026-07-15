from __future__ import annotations

import io

from fastapi.testclient import TestClient

from backend.main import app
from backend.routes.uploads import build_template_bytes, parse_deliveries_workbook
from backend.services.stub_store import store


def test_scenario_types_include_custom() -> None:
    types = {spec.scenario_type for spec in store.list_scenario_types()}
    assert "custom" in types


def test_parse_deliveries_workbook_happy_path() -> None:
    content = build_template_bytes()
    result = parse_deliveries_workbook(content)
    assert result.errors == []
    assert len(result.deliveries) == 1
    assert result.deliveries[0].customer_name == "Acme Market"
    assert result.deliveries[0].lat == 42.35


def test_upload_deliveries_endpoint() -> None:
    client = TestClient(app)
    content = build_template_bytes()
    response = client.post(
        "/api/scenarios/uploads/deliveries",
        files={
            "file": (
                "deliveries.xlsx",
                io.BytesIO(content),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["deliveries"]) == 1
    assert payload["errors"] == []


def test_download_template_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/scenarios/uploads/template")
    assert response.status_code == 200
    assert "spreadsheetml" in response.headers["content-type"]
    assert response.content[:2] == b"PK"


def test_custom_scenario_create_and_validate_in_stub() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/scenarios",
        json={
            "scenario_name": "Custom combo",
            "scenario_type": "custom",
            "baseline_scenario_id": "baseline",
            "depot_id": "DPT_NORTH",
            "delivery_day": "Tuesday",
            "parameters": {
                "changes": [
                    {
                        "kind": "driver_count_change",
                        "driver_delta": -1,
                        "allow_overtime": True,
                    },
                    {
                        "kind": "add_deliveries",
                        "deliveries": [
                            {
                                "customer_name": "Pinned Store",
                                "lat": 42.4,
                                "lng": -83.1,
                                "demand_cases": 70,
                                "service_minutes": 25,
                                "receiving_window_start": "09:00",
                                "receiving_window_end": "15:00",
                            }
                        ],
                    },
                ],
                "cost": {"cost_per_mile": 4.5},
            },
        },
    )
    assert created.status_code == 200
    scenario_id = created.json()["scenario"]["scenario_id"]
    validated = client.post(f"/api/scenarios/{scenario_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
