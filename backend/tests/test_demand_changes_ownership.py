from unittest.mock import Mock

from backend.services import demand_changes as module
from backend.services.demand_changes import DemandChangeRepository


def test_ensure_table_skips_alter_when_column_already_exists(monkeypatch) -> None:
    postgres = Mock()
    postgres.qualified_table.return_value = '"app"."network_demand_changes"'
    postgres.query_one.return_value = {"present": 1}
    monkeypatch.setattr(module.lakebase_store, "postgres", postgres)

    DemandChangeRepository()._ensure_table()

    assert postgres.execute.call_count == 1
    assert "CREATE TABLE IF NOT EXISTS" in postgres.execute.call_args.args[0]
    postgres.query_one.assert_called_once_with(
        """SELECT 1 AS present
                 FROM pg_catalog.pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = %s
                  AND NOT attisdropped""",
        ('"app"."network_demand_changes"', "processing_started_at"),
    )


def test_ensure_table_adds_column_only_when_missing(monkeypatch) -> None:
    postgres = Mock()
    postgres.qualified_table.return_value = '"app"."network_demand_changes"'
    postgres.query_one.return_value = None
    monkeypatch.setattr(module.lakebase_store, "postgres", postgres)

    DemandChangeRepository()._ensure_table()

    assert postgres.execute.call_count == 2
    assert postgres.execute.call_args.args[0] == (
        'ALTER TABLE "app"."network_demand_changes" '
        'ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ'
    )
