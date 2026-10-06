"""Compact, integrity-checked persistence helpers for network run snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import zlib
from copy import deepcopy
from typing import Any, cast

from .network_overview import NetworkRows

_MAX_UNCOMPRESSED_BYTES = int(
    os.getenv("NETWORK_SNAPSHOT_MAX_UNCOMPRESSED_BYTES", str(512 * 1024 * 1024))
)
_MAX_COMPRESSED_BYTES = int(
    os.getenv("NETWORK_SNAPSHOT_MAX_COMPRESSED_BYTES", str(64 * 1024 * 1024))
)
_MUTABLE_TABLES = (
    "dim_network_lanes",
    "network_customer_assignments_daily",
    "facility_capacity_daily",
    "facility_supply_daily",
    "lane_capacity_daily",
)
_TABLE_KEYS = {
    "dim_network_lanes": ("lane_id",),
    "network_customer_assignments_daily": (
        "demand_plan_version_id", "capacity_plan_version_id", "service_date", "customer_id",
    ),
    "facility_capacity_daily": (
        "capacity_plan_version_id", "service_date", "facility_id",
    ),
    "facility_supply_daily": (
        "capacity_plan_version_id", "service_date", "facility_id",
    ),
    "lane_capacity_daily": ("capacity_plan_version_id", "service_date", "lane_id"),
}


def _row_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        str(row.get(field, ""))[:10] if field == "service_date" else str(row.get(field, ""))
        for field in fields
    )


def _table_delta(
    before: list[dict[str, Any]], after: list[dict[str, Any]], fields: tuple[str, ...]
) -> dict[str, Any] | None:
    prior = {_row_key(row, fields): row for row in before}
    current = {_row_key(row, fields): row for row in after}
    upserts = [deepcopy(row) for row in after if prior.get(_row_key(row, fields)) != row]
    deletes = [list(key) for key in prior.keys() - current.keys()]
    return {"key_fields": list(fields), "upserts": upserts, "deletes": deletes} if upserts or deletes else None


def apply_table_delta(rows: list[dict[str, Any]], delta: dict[str, Any]) -> list[dict[str, Any]]:
    fields = tuple(str(field) for field in delta["key_fields"])
    deleted = {tuple(str(value) for value in key) for key in delta.get("deletes", [])}
    upserts = {_row_key(row, fields): deepcopy(row) for row in delta.get("upserts", [])}
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = _row_key(row, fields)
        if key in deleted:
            continue
        result.append(upserts.get(key, deepcopy(row)))
        seen.add(key)
    result.extend(row for key, row in upserts.items() if key not in seen)
    return result


def manifest_with_deltas(
    manifest: dict[str, Any], source_rows: NetworkRows, network_rows: NetworkRows
) -> dict[str, Any]:
    encoded = deepcopy(manifest)
    encoded["table_deltas"] = {
        table: delta
        for table in _MUTABLE_TABLES
        if (delta := _table_delta(source_rows.get(table, []), network_rows.get(table, []), _TABLE_KEYS[table]))
        is not None
    }
    return encoded


def encode_envelope(
    flow_rows: list[dict[str, Any]], cost_rows: list[dict[str, Any]]
) -> tuple[bytes, int, str]:
    raw = json.dumps(
        {"version": 1, "flow_rows": flow_rows, "cost_rows": cost_rows},
        separators=(",", ":"), default=str,
    ).encode()
    if len(raw) > _MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Network snapshot exceeds the uncompressed safety limit.")
    compressed = zlib.compress(raw, level=9)
    if len(compressed) > _MAX_COMPRESSED_BYTES:
        raise ValueError("Network snapshot exceeds the compressed safety limit.")
    return compressed, len(raw), hashlib.sha256(raw).hexdigest()


def decode_envelope(
    payload: bytes | bytearray | memoryview,
    *,
    codec: str,
    uncompressed_bytes: int,
    expected_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    compressed = bytes(payload)
    if codec != "zlib-json-v1":
        raise RuntimeError(f"Unsupported network snapshot codec: {codec!r}")
    if not 0 <= uncompressed_bytes <= _MAX_UNCOMPRESSED_BYTES:
        raise RuntimeError("Network snapshot declares an unsafe uncompressed size.")
    if len(compressed) > _MAX_COMPRESSED_BYTES:
        raise RuntimeError("Network snapshot compressed payload exceeds the safety limit.")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, _MAX_UNCOMPRESSED_BYTES + 1)
        if decoder.unconsumed_tail or len(raw) > _MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("Network snapshot expands beyond the safety limit.")
        raw += decoder.flush(_MAX_UNCOMPRESSED_BYTES + 1 - len(raw))
    except zlib.error as exc:
        raise RuntimeError("Network snapshot envelope is corrupt.") from exc
    if not decoder.eof or decoder.unused_data or len(raw) != uncompressed_bytes:
        raise RuntimeError("Network snapshot envelope length check failed.")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError("Network snapshot envelope integrity check failed.")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Network snapshot envelope is not valid JSON.") from exc
    if document.get("version") != 1:
        raise RuntimeError("Network snapshot envelope version is unsupported.")
    return (
        cast(list[dict[str, Any]], document["flow_rows"]),
        cast(list[dict[str, Any]], document["cost_rows"]),
    )
