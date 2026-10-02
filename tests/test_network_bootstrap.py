from types import SimpleNamespace

import pytest

from route_opt import network_bootstrap as bootstrap


def test_bootstrap_writes_only_network_tables_without_overwrite(monkeypatch):
    dataset = {name: [{"id": name}] for name in bootstrap.NETWORK_TABLES}
    monkeypatch.setattr(bootstrap, "assert_valid_network_dataset", lambda rows: None)
    writes = []
    spark = SimpleNamespace(
        catalog=SimpleNamespace(tableExists=lambda name: False),
        table=lambda name: SimpleNamespace(count=lambda: 1),
        createDataFrame=lambda rows: SimpleNamespace(createOrReplaceTempView=lambda name: None),
        sql=lambda statement: writes.append(statement),
    )
    result = bootstrap.bootstrap_network_tables(spark, dataset, catalog="demos", schema="demo")
    assert len(writes) == len(bootstrap.NETWORK_TABLES)
    assert all(statement.startswith("CREATE TABLE ") for statement in writes)
    assert all("REPLACE" not in statement and "IF NOT EXISTS" not in statement for statement in writes)
    assert set(result["created"]) == set(bootstrap.NETWORK_TABLES)


@pytest.mark.parametrize("existing_count", [1, len(bootstrap.NETWORK_TABLES)])
def test_existing_tables_are_never_written(monkeypatch, existing_count):
    dataset = {name: [{"id": name}] for name in bootstrap.NETWORK_TABLES}
    monkeypatch.setattr(bootstrap, "assert_valid_network_dataset", lambda rows: None)
    existing = set(bootstrap.NETWORK_TABLES[:existing_count])
    spark = SimpleNamespace(catalog=SimpleNamespace(
        tableExists=lambda full_name: full_name.split(".")[-1].strip("`") in existing
    ))

    def reject_write(*args, **kwargs):
        raise AssertionError("Never overwrite existing data")

    spark.sql = reject_write
    spark.createDataFrame = reject_write
    if existing_count == len(bootstrap.NETWORK_TABLES):
        assert bootstrap.bootstrap_network_tables(
            spark, dataset, catalog="demos", schema="demo"
        )["created"] == []
    else:
        with pytest.raises(ValueError, match="Partial network snapshot"):
            bootstrap.bootstrap_network_tables(spark, dataset, catalog="demos", schema="demo")
