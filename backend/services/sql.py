"""Thin wrapper around databricks-sdk statement execution."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from ..config import (
    get_catalog,
    get_schema,
    get_sql_warehouse_id,
    get_sql_warehouse_name,
    get_workspace_client,
)


def resolve_sql_warehouse_id() -> str:
    configured_id = get_sql_warehouse_id()
    if configured_id:
        return configured_id

    client = get_workspace_client()
    desired_name = (get_sql_warehouse_name() or "").lower()
    for warehouse in client.warehouses.list():
        if not warehouse.id:
            continue
        if desired_name and (warehouse.name or "").lower() != desired_name:
            continue
        return warehouse.id

    for warehouse in client.warehouses.list():
        if warehouse.id:
            return warehouse.id

    raise HTTPException(status_code=500, detail="No SQL warehouse available.")


def _parse_results(execution: Any) -> list[dict[str, Any]]:
    result = execution.result
    manifest = getattr(execution, "manifest", None)
    if not result or not manifest or not manifest.schema:
        return []

    data_array = getattr(result, "data_array", None) or []
    columns = manifest.schema.columns
    col_names = [column.name for column in columns]

    def _resolve_type(column) -> str:
        raw = getattr(column, "type_name", "STRING")
        if hasattr(raw, "value"):
            raw = raw.value
        return str(raw or "STRING").upper()

    col_types = [_resolve_type(column) for column in columns]

    rows: list[dict[str, Any]] = []
    for row in data_array:
        parsed: dict[str, Any] = {}
        for idx, col_name in enumerate(col_names):
            value = row[idx] if idx < len(row) else None
            if value is None:
                parsed[col_name] = None
                continue
            col_type = col_types[idx]
            if col_type in {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "LONG"}:
                try:
                    parsed[col_name] = int(value)
                except (TypeError, ValueError):
                    parsed[col_name] = value
            elif col_type in {"DOUBLE", "FLOAT", "DECIMAL"}:
                try:
                    parsed[col_name] = float(value)
                except (TypeError, ValueError):
                    parsed[col_name] = value
            elif col_type == "BOOLEAN":
                parsed[col_name] = str(value).lower() in {"true", "1", "yes"}
            else:
                parsed[col_name] = value
        rows.append(parsed)
    return rows


def execute_sql(
    query: str,
    parameters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    sdk_params = None
    if parameters:
        sdk_params = [
            StatementParameterListItem(
                name=str(p["name"]),
                value=str(p["value"]) if p["value"] is not None else None,
                type=p.get("type"),
            )
            for p in parameters
        ]

    execution = get_workspace_client().statement_execution.execute_statement(
        warehouse_id=resolve_sql_warehouse_id(),
        statement=query,
        parameters=sdk_params,
        wait_timeout="30s",
    )
    state = execution.status.state if execution.status and execution.status.state else None
    if state != StatementState.SUCCEEDED:
        detail = (
            str(execution.status.error)
            if execution.status and execution.status.error
            else "SQL execution failed."
        )
        raise HTTPException(status_code=400, detail=detail)
    return _parse_results(execution)


class SqlService:
    def __init__(self) -> None:
        self.catalog = get_catalog()
        self.schema = get_schema()

    def table(self, name: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{name}`"

    def query(self, statement: str) -> list[dict[str, Any]]:
        return execute_sql(statement)

    def execute(self, statement: str) -> None:
        execute_sql(statement)

    def payload_json(self, statement: str) -> dict[str, Any]:
        rows = self.query(statement)
        if not rows:
            raise HTTPException(status_code=404, detail="Expected a payload_json row but query returned no rows.")
        value = rows[0]["payload_json"]
        return json.loads(value) if isinstance(value, str) else value


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("'", "''")
    return f"'{text}'"
