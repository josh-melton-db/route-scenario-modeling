"""Thin wrapper around databricks-sdk statement execution."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
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


def _parse_results(execution: Any, data_array=None) -> list[dict[str, Any]]:
    result = execution.result
    manifest = getattr(execution, "manifest", None)
    if not result or not manifest or not manifest.schema:
        return []

    if data_array is None:
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


def _read_results(client, execution):
    manifest = execution.manifest
    if not manifest or not execution.result:
        return []
    if getattr(manifest, "truncated", False):
        raise HTTPException(status_code=502, detail="SQL result was truncated; refusing an incomplete snapshot.")
    rows = []
    downloaded = set()
    for index in range(getattr(manifest, "total_chunk_count", None) or 1):
        if index in downloaded:
            continue
        chunk = (
            execution.result if index == 0
            else client.statement_execution.get_statement_result_chunk_n(execution.statement_id, index)
        )
        links = getattr(chunk, "external_links", None) or []
        if not links:
            rows.extend(_parse_results(execution, getattr(chunk, "data_array", None) or []))
            continue
        for link in links:
            if link.chunk_index in downloaded:
                continue
            parsed = urlsplit(link.external_link)
            app_storage_proxy = (
                bool(os.getenv("DATABRICKS_APP_NAME"))
                and parsed.scheme == "http"
                and parsed.hostname == "storage-proxy.databricks.com"
                and parsed.port in (None, 80)
            )
            if parsed.username or parsed.password or not (parsed.scheme == "https" or app_storage_proxy):
                raise HTTPException(
                    status_code=502,
                    detail="SQL download requires HTTPS or the Databricks App storage proxy.",
                )
            try:
                # Signed storage URLs must not receive workspace credentials.
                response = httpx.get(link.external_link, timeout=60)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list) or any(not isinstance(row, list) for row in data):
                    raise ValueError("Invalid result chunk")
            except (httpx.HTTPError, ValueError):
                raise HTTPException(status_code=502, detail="Could not download a complete SQL result chunk.") from None
            if link.row_count is not None and len(data) != link.row_count:
                raise HTTPException(status_code=502, detail="SQL result chunk row count mismatch.")
            rows.extend(_parse_results(execution, data))
            downloaded.add(link.chunk_index)
    expected = getattr(manifest, "total_row_count", None)
    if expected is not None and len(rows) != expected:
        raise HTTPException(status_code=502, detail="SQL result row count mismatch; refusing an incomplete snapshot.")
    return rows


def execute_sql(
    query: str,
    parameters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from databricks.sdk.service.sql import (
        Disposition,
        Format,
        StatementParameterListItem,
        StatementState,
    )

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

    client = get_workspace_client()
    options = dict(
        warehouse_id=resolve_sql_warehouse_id(),
        statement=query,
        parameters=sdk_params,
        format=Format.JSON_ARRAY,
        wait_timeout="30s",
    )
    execution = client.statement_execution.execute_statement(**options)
    error = str(execution.status.error) if execution.status and execution.status.error else ""
    if "Inline byte limit exceeded" in error and query.lstrip().upper().startswith("SELECT"):
        execution = client.statement_execution.execute_statement(
            **options, disposition=Disposition.EXTERNAL_LINKS,
        )
    state = execution.status.state if execution.status and execution.status.state else None
    if state != StatementState.SUCCEEDED:
        # Raw warehouse errors can contain catalog names, query text, and resource IDs.
        raise HTTPException(status_code=502, detail="The analytics query could not be completed.")
    return _read_results(client, execution)


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
