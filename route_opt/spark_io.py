from __future__ import annotations

import json
from numbers import Real
from collections.abc import Iterable


def _json_ready(row: dict[str, object]) -> dict[str, object]:
    converted: dict[str, object] = {}
    for key, value in row.items():
        if isinstance(value, (dict, list)):
            converted[key] = json.dumps(value, sort_keys=True)
        else:
            converted[key] = value
    return converted


def _normalize_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    ready = [_json_ready(row) for row in rows]
    if not ready:
        return []

    keys = sorted({key for row in ready for key in row})
    all_null_keys = {key for key in keys if all(row.get(key) is None for row in ready)}
    float_keys = {
        key
        for key in keys
        if any(isinstance(row.get(key), float) for row in ready)
        and all(
            row.get(key) is None
            or (isinstance(row.get(key), Real) and not isinstance(row.get(key), bool))
            for row in ready
        )
    }
    normalized: list[dict[str, object]] = []
    for row in ready:
        normalized_row: dict[str, object] = {}
        for key in keys:
            value = row.get(key)
            if key in all_null_keys:
                normalized_row[key] = ""
            elif key in float_keys and value is not None:
                normalized_row[key] = float(value)
            else:
                normalized_row[key] = value
        normalized.append(normalized_row)
    return normalized


def write_rows_as_table(
    spark,
    rows: Iterable[dict[str, object]],
    full_name: str,
    *,
    mode: str = "overwrite",
    replace_where: str | None = None,
) -> None:
    ready = _normalize_rows(rows)
    if not ready:
        if replace_where:
            spark.sql(f"DELETE FROM {full_name} WHERE {replace_where}")
        return
    writer = spark.createDataFrame(ready).write.mode(mode)
    if replace_where:
        writer = writer.option("replaceWhere", replace_where).option("mergeSchema", "true")
    elif mode == "overwrite":
        writer = writer.option("overwriteSchema", "true")
    else:
        writer = writer.option("mergeSchema", "true")
    writer.saveAsTable(full_name)


def write_rows_as_parquet(
    spark,
    rows: Iterable[dict[str, object]],
    path: str,
    *,
    mode: str = "overwrite",
) -> None:
    ready = _normalize_rows(rows)
    if not ready:
        return
    spark.createDataFrame(ready).write.mode(mode).parquet(path)


def collect_dicts(dataframe) -> list[dict[str, object]]:
    return [row.asDict(recursive=True) for row in dataframe.collect()]
