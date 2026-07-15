from backend.services.ground_truth_store import GroundTruthStore, _ENTITY_SPECS
from backend.services.lakebase_migrations import _statements
from backend.services.postgres import PostgresService


def test_editor_migrations_create_session_scope_and_row_versions() -> None:
    statements = "\n".join(_statements(PostgresService(schema="editor_test")))

    assert '"editor_sessions"' in statements
    assert '"editor_session_rows"' in statements
    assert '"editor_audit_events"' in statements
    assert "ADD COLUMN IF NOT EXISTS row_version" in statements


def test_editor_validation_rejects_invalid_customer_window() -> None:
    normalized, issues = GroundTruthStore._validation_issues(
        _ENTITY_SPECS["customers"],
        "CUST_TEST",
        {
            "customer_id": "CUST_TEST",
            "customer_name": "Test Customer",
            "depot_id": "DPT_TEST",
            "region": "Great Lakes",
            "sales_territory": "Test Metro",
            "lat": 42.0,
            "lng": -83.0,
            "customer_priority": "standard",
            "delivery_frequency": 1,
            "eligible_delivery_days": "Tuesday",
            "receiving_window_start": "16:00",
            "receiving_window_end": "08:00",
            "service_minutes": 30,
            "special_handling": None,
        },
    )

    assert normalized is not None
    assert any(issue.code == "invalid_time_window" for issue in issues)
