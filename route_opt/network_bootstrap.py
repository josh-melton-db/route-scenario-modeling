"""Create the network demo snapshot without replacing existing route data."""
from .network_synthetic import assert_valid_network_dataset
from .schemas import NETWORK_TABLES
from .spark_io import _normalize_rows


def bootstrap_network_tables(spark, dataset, *, catalog: str, schema: str) -> dict:
    if set(dataset) != set(NETWORK_TABLES):
        raise ValueError("Bootstrap accepts only the complete network table set")
    assert_valid_network_dataset(dataset)

    def quoted(value):
        if not value:
            raise ValueError("Catalog and schema must be nonempty")
        return "`" + value.replace("`", "``") + "`"

    names = {
        name: ".".join(quoted(part) for part in (catalog, schema, name))
        for name in NETWORK_TABLES
    }
    existing = [name for name, full_name in names.items() if spark.catalog.tableExists(full_name)]
    if existing and len(existing) != len(names):
        raise ValueError(
            "Partial network snapshot already exists; no tables were written. "
            "Reconcile the existing snapshot before bootstrapping: " + ", ".join(existing)
        )
    if existing:
        return {"created": [], "existing": existing}
    counts = {}
    for name, full_name in names.items():
        print(f"Creating {full_name}: {len(dataset[name])} rows", flush=True)
        view = "_network_bootstrap_" + name
        spark.createDataFrame(_normalize_rows(dataset[name])).createOrReplaceTempView(view)
        # CTAS fails if the table exists and is supported by serverless Spark.
        spark.sql(f"CREATE TABLE {full_name} USING DELTA AS SELECT * FROM {quoted(view)}")
        counts[name] = spark.table(full_name).count()
        if counts[name] != len(dataset[name]):
            raise RuntimeError(f"Published row count mismatch for {full_name}")
    return {"created": list(names), "existing": [], "row_counts": counts}
