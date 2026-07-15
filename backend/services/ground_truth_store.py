"""Session-isolated CRUD for solver planning inputs in Lakebase.

The editor deliberately snapshots data into app-owned session tables instead of
creating a Lakebase branch per browser session.  A session is private to its
authenticated principal, mutations are serialized with a session-row lock, and
the master-row version captured at open time is checked again on commit.
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, cast

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from route_opt.baseline import reconstruct_baseline
from route_opt.cost import CostParameters

from ..models import (
    BaselineNetwork,
    EditorCommitResponse,
    EditorDeleteRequest,
    EditorEntityType,
    EditorInsertRequest,
    EditorPage,
    EditorPatchRequest,
    EditorPreviewRequest,
    EditorPreviewResponse,
    EditorRow,
    EditorRowState,
    EditorSession,
    EditorSessionStatus,
    EditorValidationIssue,
    EditorValidationResponse,
    Kpis,
    StrictModel,
)
from .postgres import PostgresService


_ENTITY_TYPES: tuple[EditorEntityType, ...] = (
    "orders",
    "customers",
    "fleet",
    "depots",
    "cost_parameters",
)
_DELETE_PROMOTION_ORDER: tuple[EditorEntityType, ...] = (
    "orders",
    "fleet",
    "customers",
    "depots",
    "cost_parameters",
)
_WRITE_PROMOTION_ORDER: tuple[EditorEntityType, ...] = (
    "depots",
    "customers",
    "fleet",
    "cost_parameters",
    "orders",
)
_TIME_PATTERN = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$")


class _DepotInput(StrictModel):
    depot_id: str
    depot_name: str
    region: str
    sales_territory: str
    lat: float
    lng: float
    operating_calendar: str | None = None


class _CustomerInput(StrictModel):
    customer_id: str
    customer_name: str
    depot_id: str
    region: str
    sales_territory: str
    lat: float
    lng: float
    customer_priority: str | None = None
    delivery_frequency: int | None = None
    eligible_delivery_days: str
    receiving_window_start: str
    receiving_window_end: str
    service_minutes: int
    special_handling: str | None = None


class _FleetInput(StrictModel):
    vehicle_id: str
    depot_id: str
    vehicle_type: str | None = None
    capacity_cases: int
    fixed_truck_daily_cost: float | None = None
    cost_per_mile: float | None = None
    max_route_minutes: int | None = None
    available_days: str


class _OrderInput(StrictModel):
    order_id: str
    customer_id: str
    depot_id: str
    delivery_day: str
    route_date: date | None = None
    demand_cases: int
    product_family: str | None = None


class _CostParametersInput(StrictModel):
    parameter_set_id: str
    cost_per_mile: float
    labor_regular_hour: float
    overtime_multiplier: float
    overtime_threshold_minutes: int
    fixed_truck_daily_cost: float
    max_route_minutes: int
    late_delivery_penalty: float
    missed_delivery_penalty: float
    avg_speed_mph: float
    circuity: float


@dataclass(frozen=True)
class _EntitySpec:
    entity_type: EditorEntityType
    table_name: str
    id_column: str
    columns: tuple[str, ...]
    model: type[BaseModel]
    required_text_fields: tuple[str, ...]


_ENTITY_SPECS: dict[EditorEntityType, _EntitySpec] = {
    "depots": _EntitySpec(
        entity_type="depots",
        table_name="depots",
        id_column="depot_id",
        columns=(
            "depot_id",
            "depot_name",
            "region",
            "sales_territory",
            "lat",
            "lng",
            "operating_calendar",
        ),
        model=_DepotInput,
        required_text_fields=("depot_id", "depot_name", "region", "sales_territory"),
    ),
    "customers": _EntitySpec(
        entity_type="customers",
        table_name="customers",
        id_column="customer_id",
        columns=(
            "customer_id",
            "customer_name",
            "depot_id",
            "region",
            "sales_territory",
            "lat",
            "lng",
            "customer_priority",
            "delivery_frequency",
            "eligible_delivery_days",
            "receiving_window_start",
            "receiving_window_end",
            "service_minutes",
            "special_handling",
        ),
        model=_CustomerInput,
        required_text_fields=(
            "customer_id",
            "customer_name",
            "depot_id",
            "region",
            "sales_territory",
            "eligible_delivery_days",
            "receiving_window_start",
            "receiving_window_end",
        ),
    ),
    "fleet": _EntitySpec(
        entity_type="fleet",
        table_name="fleet",
        id_column="vehicle_id",
        columns=(
            "vehicle_id",
            "depot_id",
            "vehicle_type",
            "capacity_cases",
            "fixed_truck_daily_cost",
            "cost_per_mile",
            "max_route_minutes",
            "available_days",
        ),
        model=_FleetInput,
        required_text_fields=("vehicle_id", "depot_id", "available_days"),
    ),
    "orders": _EntitySpec(
        entity_type="orders",
        table_name="orders",
        id_column="order_id",
        columns=(
            "order_id",
            "customer_id",
            "depot_id",
            "delivery_day",
            "route_date",
            "demand_cases",
            "product_family",
        ),
        model=_OrderInput,
        required_text_fields=("order_id", "customer_id", "depot_id", "delivery_day"),
    ),
    "cost_parameters": _EntitySpec(
        entity_type="cost_parameters",
        table_name="cost_parameters",
        id_column="parameter_set_id",
        columns=(
            "parameter_set_id",
            "cost_per_mile",
            "labor_regular_hour",
            "overtime_multiplier",
            "overtime_threshold_minutes",
            "fixed_truck_daily_cost",
            "max_route_minutes",
            "late_delivery_penalty",
            "missed_delivery_penalty",
            "avg_speed_mph",
            "circuity",
        ),
        model=_CostParametersInput,
        required_text_fields=("parameter_set_id",),
    ),
}


def _plain_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise ValueError("Expected a JSON object.")
        return decoded
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    raise ValueError("Expected a JSON object.")


def _iso_timestamp(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _row_state(operation: str) -> EditorRowState:
    if operation == "insert":
        return "inserted"
    if operation == "update":
        return "updated"
    return "unchanged"


class GroundTruthStore:
    """Owns editor snapshots, mutations, validation, and atomic promotion."""

    def __init__(
        self,
        postgres: PostgresService | None = None,
        *,
        session_ttl_hours: int | None = None,
    ) -> None:
        self.postgres = postgres or PostgresService()
        configured_ttl = session_ttl_hours
        if configured_ttl is None:
            configured_ttl = int(os.getenv("DATA_EDITOR_SESSION_TTL_HOURS", "8"))
        self.session_ttl_hours = max(1, configured_ttl)

    def _table(self, table_name: str) -> str:
        return self.postgres.qualified_table(table_name)

    @staticmethod
    def _spec(entity_type: EditorEntityType) -> _EntitySpec:
        try:
            return _ENTITY_SPECS[entity_type]
        except KeyError as exc:  # pragma: no cover - FastAPI validates the literal first
            raise HTTPException(status_code=404, detail="Unsupported editor table.") from exc

    def _record_audit(
        self,
        *,
        connection: Any,
        session_id: str,
        principal: str,
        event_type: str,
        entity_type: EditorEntityType | None = None,
        row_id: str | None = None,
        before_data: Mapping[str, Any] | None = None,
        after_data: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.postgres.execute(
            f"""
            INSERT INTO {self._table("editor_audit_events")} (
                event_id, session_id, principal, event_type, entity_type, row_id,
                before_data, after_data, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"eda_{uuid.uuid4().hex}",
                session_id,
                principal,
                event_type,
                entity_type,
                row_id,
                self.postgres.jsonb(dict(before_data)) if before_data is not None else None,
                self.postgres.jsonb(dict(after_data)) if after_data is not None else None,
                self.postgres.jsonb(dict(metadata)) if metadata is not None else None,
            ),
            connection=connection,
        )

    def _expire_open_sessions(self, connection: Any) -> None:
        """Expire only session-scoped data while retaining metadata and audit history."""
        rows = self.postgres.query(
            f"""
            SELECT session_id, principal
            FROM {self._table("editor_sessions")}
            WHERE status = 'open' AND expires_at <= CURRENT_TIMESTAMP
            FOR UPDATE SKIP LOCKED
            """,
            connection=connection,
        )
        for row in rows:
            session_id = str(row["session_id"])
            principal = str(row["principal"])
            self.postgres.execute(
                f"""
                UPDATE {self._table("editor_sessions")}
                SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE session_id = %s
                """,
                (session_id,),
                connection=connection,
            )
            self.postgres.execute(
                f"DELETE FROM {self._table('editor_session_rows')} WHERE session_id = %s",
                (session_id,),
                connection=connection,
            )
            self._record_audit(
                connection=connection,
                session_id=session_id,
                principal=principal,
                event_type="expired",
            )

    def _session_summary(self, session: Mapping[str, Any], connection: Any) -> EditorSession:
        counts: dict[EditorEntityType, int] = {entity: 0 for entity in _ENTITY_TYPES}
        for row in self.postgres.query(
            f"""
            SELECT entity_type, COUNT(*) AS count
            FROM {self._table("editor_session_rows")}
            WHERE session_id = %s AND operation <> 'delete'
            GROUP BY entity_type
            """,
            (session["session_id"],),
            connection=connection,
        ):
            entity_type = str(row["entity_type"])
            if entity_type in _ENTITY_TYPES:
                counts[cast(EditorEntityType, entity_type)] = int(row["count"])
        changed = self.postgres.query_one(
            f"""
            SELECT COUNT(*) AS count
            FROM {self._table("editor_session_rows")}
            WHERE session_id = %s AND operation <> 'unchanged'
            """,
            (session["session_id"],),
            connection=connection,
        )
        return EditorSession(
            session_id=str(session["session_id"]),
            principal=str(session["principal"]),
            status=cast(EditorSessionStatus, str(session["status"])),
            created_at=_iso_timestamp(session["created_at"]),
            updated_at=_iso_timestamp(session["updated_at"]),
            expires_at=_iso_timestamp(session["expires_at"]),
            has_unsaved_changes=bool(changed and int(changed["count"]) > 0),
            entity_counts=counts,
        )

    def _locked_open_session(
        self,
        session_id: str,
        principal: str,
        connection: Any,
    ) -> Mapping[str, Any] | None:
        session = self.postgres.query_one(
            f"""
            SELECT session_id, principal, status, created_at, updated_at, expires_at
            FROM {self._table("editor_sessions")}
            WHERE session_id = %s AND principal = %s
            FOR UPDATE
            """,
            (session_id, principal),
            connection=connection,
        )
        if session is None:
            # Returning 404 rather than 403 does not reveal other users' session IDs.
            raise HTTPException(status_code=404, detail="Editor session was not found.")
        if str(session["status"]) == "expired":
            raise HTTPException(
                status_code=410,
                detail="Editor session expired. Its draft data was discarded; open a new session.",
            )
        if str(session["status"]) != "open":
            raise HTTPException(
                status_code=409,
                detail=f"Editor session is already {session['status']}. Open a new session to continue.",
            )
        expired = self.postgres.query_one(
            f"""
            SELECT session_id
            FROM {self._table("editor_sessions")}
            WHERE session_id = %s AND expires_at <= CURRENT_TIMESTAMP
            """,
            (session_id,),
            connection=connection,
        )
        if expired is None:
            return session
        self.postgres.execute(
            f"""
            UPDATE {self._table("editor_sessions")}
            SET status = 'expired', updated_at = CURRENT_TIMESTAMP
            WHERE session_id = %s
            """,
            (session_id,),
            connection=connection,
        )
        self.postgres.execute(
            f"DELETE FROM {self._table('editor_session_rows')} WHERE session_id = %s",
            (session_id,),
            connection=connection,
        )
        self._record_audit(
            connection=connection,
            session_id=session_id,
            principal=principal,
            event_type="expired",
        )
        return None

    @staticmethod
    def _raise_if_expired(expired: bool) -> None:
        if expired:
            raise HTTPException(
                status_code=410,
                detail="Editor session expired. Its draft data was discarded; open a new session.",
            )

    def _touch_session(
        self,
        session_id: str,
        connection: Any,
    ) -> Mapping[str, Any]:
        session = self.postgres.query_one(
            f"""
            UPDATE {self._table("editor_sessions")}
            SET updated_at = CURRENT_TIMESTAMP
            WHERE session_id = %s
            RETURNING session_id, principal, status, created_at, updated_at, expires_at
            """,
            (session_id,),
            connection=connection,
        )
        if session is None:  # pragma: no cover - protected by session lock
            raise RuntimeError("Editor session disappeared during an update.")
        return session

    @staticmethod
    def _validation_issues(
        spec: _EntitySpec,
        row_id: str,
        data: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, list[EditorValidationIssue]]:
        try:
            normalized = spec.model.model_validate(dict(data)).model_dump(mode="json")
        except ValidationError as exc:
            issues: list[EditorValidationIssue] = []
            for error in exc.errors(include_url=False):
                location = ".".join(str(part) for part in error.get("loc", ())) or None
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field=location,
                        code="invalid_value",
                        message=str(error.get("msg", "Invalid value.")),
                    )
                )
            return None, issues

        issues = []
        for field in spec.required_text_fields:
            value = normalized.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field=field,
                        code="required",
                        message="A non-empty value is required.",
                    )
                )
            elif value != value.strip():
                normalized[field] = value.strip()

        for field, lower, upper in (("lat", -90.0, 90.0), ("lng", -180.0, 180.0)):
            if field not in normalized:
                continue
            value = float(normalized[field])
            if not math.isfinite(value) or value < lower or value > upper:
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field=field,
                        code="out_of_range",
                        message=f"Value must be between {lower:g} and {upper:g}.",
                    )
                )

        positive_fields = (
            "delivery_frequency",
            "service_minutes",
            "capacity_cases",
            "max_route_minutes",
            "demand_cases",
            "overtime_threshold_minutes",
            "avg_speed_mph",
            "circuity",
        )
        nonnegative_fields = (
            "fixed_truck_daily_cost",
            "cost_per_mile",
            "labor_regular_hour",
            "late_delivery_penalty",
            "missed_delivery_penalty",
        )
        for field in positive_fields:
            value = normalized.get(field)
            if value is not None and float(value) <= 0:
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field=field,
                        code="must_be_positive",
                        message="Value must be greater than zero.",
                    )
                )
        for field in nonnegative_fields:
            value = normalized.get(field)
            if value is not None and float(value) < 0:
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field=field,
                        code="must_be_nonnegative",
                        message="Value cannot be negative.",
                    )
                )
        multiplier = normalized.get("overtime_multiplier")
        if multiplier is not None and float(multiplier) < 1:
            issues.append(
                EditorValidationIssue(
                    entity_type=spec.entity_type,
                    row_id=row_id,
                    field="overtime_multiplier",
                    code="out_of_range",
                    message="Overtime multiplier must be at least 1.",
                )
            )

        if {"receiving_window_start", "receiving_window_end"}.issubset(normalized):
            start = str(normalized["receiving_window_start"])
            end = str(normalized["receiving_window_end"])
            start_match = _TIME_PATTERN.fullmatch(start)
            end_match = _TIME_PATTERN.fullmatch(end)
            if start_match is None or end_match is None:
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field="receiving_window_start",
                        code="invalid_time_window",
                        message="Receiving windows must use 24-hour HH:MM values.",
                    )
                )
            elif start >= end:
                issues.append(
                    EditorValidationIssue(
                        entity_type=spec.entity_type,
                        row_id=row_id,
                        field="receiving_window_end",
                        code="invalid_time_window",
                        message="Receiving window end must be after its start.",
                    )
                )
        return normalized, issues

    def _normalized_or_raise(
        self,
        spec: _EntitySpec,
        row_id: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized, issues = self._validation_issues(spec, row_id, data)
        if issues:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Row validation failed.",
                    "issues": [issue.model_dump(mode="json") for issue in issues],
                },
            )
        if normalized is None:  # pragma: no cover - guarded above
            raise RuntimeError("A valid editor row did not normalize.")
        return normalized

    def _session_rows(
        self,
        session_id: str,
        connection: Any,
        *,
        include_deleted: bool = True,
    ) -> dict[EditorEntityType, list[dict[str, Any]]]:
        where = "" if include_deleted else "AND operation <> 'delete'"
        rows = self.postgres.query(
            f"""
            SELECT entity_type, row_id, source_row_version, row_version, operation, original_data, row_data
            FROM {self._table("editor_session_rows")}
            WHERE session_id = %s {where}
            ORDER BY entity_type, row_id
            """,
            (session_id,),
            connection=connection,
        )
        grouped: dict[EditorEntityType, list[dict[str, Any]]] = {
            entity: [] for entity in _ENTITY_TYPES
        }
        for row in rows:
            entity_type = str(row["entity_type"])
            if entity_type not in _ENTITY_TYPES:
                continue
            editor_entity_type = cast(EditorEntityType, entity_type)
            grouped[editor_entity_type].append(
                {
                    **row,
                    "entity_type": editor_entity_type,
                    "row_id": str(row["row_id"]),
                    "source_row_version": (
                        int(row["source_row_version"])
                        if row["source_row_version"] is not None
                        else None
                    ),
                    "row_version": int(row["row_version"]),
                    "operation": str(row["operation"]),
                    "original_data": (
                        _json_object(row["original_data"])
                        if row["original_data"] is not None
                        else None
                    ),
                    "row_data": _json_object(row["row_data"]),
                }
            )
        return grouped

    def _validate_session_rows(
        self,
        session_id: str,
        connection: Any,
    ) -> tuple[dict[EditorEntityType, list[dict[str, Any]]], list[EditorValidationIssue]]:
        rows_by_entity = self._session_rows(
            session_id,
            connection,
            include_deleted=False,
        )
        issues: list[EditorValidationIssue] = []
        normalized_rows: dict[EditorEntityType, list[dict[str, Any]]] = {
            entity: [] for entity in _ENTITY_TYPES
        }
        for entity_type, rows in rows_by_entity.items():
            spec = self._spec(entity_type)
            for row in rows:
                normalized, row_issues = self._validation_issues(
                    spec,
                    row["row_id"],
                    row["row_data"],
                )
                issues.extend(row_issues)
                if normalized is not None:
                    normalized_rows[entity_type].append({**row, "row_data": normalized})

        depots = {
            str(row["row_data"]["depot_id"])
            for row in normalized_rows["depots"]
        }
        customers = {
            str(row["row_data"]["customer_id"]): row["row_data"]
            for row in normalized_rows["customers"]
        }
        for entity_type in ("customers", "fleet"):
            for row in normalized_rows[entity_type]:
                depot_id = str(row["row_data"]["depot_id"])
                if depot_id not in depots:
                    issues.append(
                        EditorValidationIssue(
                            entity_type=entity_type,
                            row_id=row["row_id"],
                            field="depot_id",
                            code="missing_reference",
                            message=f"Depot {depot_id!r} does not exist in this session.",
                        )
                    )
        for row in normalized_rows["orders"]:
            data = row["row_data"]
            customer_id = str(data["customer_id"])
            depot_id = str(data["depot_id"])
            customer = customers.get(customer_id)
            if customer is None:
                issues.append(
                    EditorValidationIssue(
                        entity_type="orders",
                        row_id=row["row_id"],
                        field="customer_id",
                        code="missing_reference",
                        message=f"Customer {customer_id!r} does not exist in this session.",
                    )
                )
            elif str(customer["depot_id"]) != depot_id:
                issues.append(
                    EditorValidationIssue(
                        entity_type="orders",
                        row_id=row["row_id"],
                        field="depot_id",
                        code="inconsistent_reference",
                        message="Order depot must match its customer's assigned depot.",
                    )
                )
            if depot_id not in depots:
                issues.append(
                    EditorValidationIssue(
                        entity_type="orders",
                        row_id=row["row_id"],
                        field="depot_id",
                        code="missing_reference",
                        message=f"Depot {depot_id!r} does not exist in this session.",
                    )
                )
        return normalized_rows, issues

    def open_session(self, principal: str) -> EditorSession:
        with self.postgres.transaction() as connection:
            self._expire_open_sessions(connection)
            session_id = f"eds_{uuid.uuid4().hex}"
            session = self.postgres.query_one(
                f"""
                INSERT INTO {self._table("editor_sessions")} (
                    session_id, principal, status, expires_at
                ) VALUES (
                    %s, %s, 'open', CURRENT_TIMESTAMP + (%s * INTERVAL '1 hour')
                )
                RETURNING session_id, principal, status, created_at, updated_at, expires_at
                """,
                (session_id, principal, self.session_ttl_hours),
                connection=connection,
            )
            if session is None:  # pragma: no cover - INSERT RETURNING always returns
                raise RuntimeError("Unable to create editor session.")

            snapshot_counts: dict[str, int] = {}
            for entity_type in _ENTITY_TYPES:
                spec = self._spec(entity_type)
                source_rows = self.postgres.query(
                    f"""
                    SELECT {", ".join(spec.columns)}, row_version
                    FROM {self._table(spec.table_name)}
                    ORDER BY {spec.id_column}
                    """,
                    connection=connection,
                )
                snapshot_counts[entity_type] = len(source_rows)
                self.postgres.executemany(
                    f"""
                    INSERT INTO {self._table("editor_session_rows")} (
                        session_id, entity_type, row_id, source_row_version, row_version,
                        operation, original_data, row_data
                    ) VALUES (%s, %s, %s, %s, 1, 'unchanged', %s, %s)
                    """,
                    [
                        (
                            session_id,
                            entity_type,
                            str(source_row[spec.id_column]),
                            int(source_row.get("row_version") or 1),
                            self.postgres.jsonb(
                                {
                                    column: _plain_value(source_row.get(column))
                                    for column in spec.columns
                                }
                            ),
                            self.postgres.jsonb(
                                {
                                    column: _plain_value(source_row.get(column))
                                    for column in spec.columns
                                }
                            ),
                        )
                        for source_row in source_rows
                    ],
                    connection=connection,
                )
            self._record_audit(
                connection=connection,
                session_id=session_id,
                principal=principal,
                event_type="opened",
                metadata={"snapshot_counts": snapshot_counts},
            )
            return self._session_summary(session, connection)

    def get_session(self, session_id: str, principal: str) -> EditorSession:
        expired = False
        with self.postgres.transaction() as connection:
            session: Mapping[str, Any] | None = self.postgres.query_one(
                f"""
                SELECT session_id, principal, status, created_at, updated_at, expires_at
                FROM {self._table("editor_sessions")}
                WHERE session_id = %s AND principal = %s
                FOR UPDATE
                """,
                (session_id, principal),
                connection=connection,
            )
            if session is None:
                raise HTTPException(status_code=404, detail="Editor session was not found.")
            if str(session["status"]) == "open":
                locked = self._locked_open_session(session_id, principal, connection)
                expired = locked is None
                if locked is not None:
                    session = locked
            if not expired:
                summary = self._session_summary(session, connection)
        self._raise_if_expired(expired)
        return summary

    def list_rows(
        self,
        session_id: str,
        principal: str,
        entity_type: EditorEntityType,
        *,
        page: int,
        page_size: int,
    ) -> EditorPage:
        self._spec(entity_type)
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                total_row = self.postgres.query_one(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM {self._table("editor_session_rows")}
                    WHERE session_id = %s AND entity_type = %s AND operation <> 'delete'
                    """,
                    (session_id, entity_type),
                    connection=connection,
                )
                total = int(total_row["count"]) if total_row else 0
                rows = self.postgres.query(
                    f"""
                    SELECT row_id, row_version, operation, row_data
                    FROM {self._table("editor_session_rows")}
                    WHERE session_id = %s AND entity_type = %s AND operation <> 'delete'
                    ORDER BY row_id
                    LIMIT %s OFFSET %s
                    """,
                    (session_id, entity_type, page_size, (page - 1) * page_size),
                    connection=connection,
                )
                response = EditorPage(
                    session=self._session_summary(session, connection),
                    entity_type=entity_type,
                    page=page,
                    page_size=page_size,
                    total=total,
                    rows=[
                        EditorRow(
                            entity_type=entity_type,
                            row_id=str(row["row_id"]),
                            row_version=int(row["row_version"]),
                            state=_row_state(str(row["operation"])),
                            data=_json_object(row["row_data"]),
                        )
                        for row in rows
                    ],
                )
        self._raise_if_expired(expired)
        return response

    def insert_row(
        self,
        session_id: str,
        principal: str,
        entity_type: EditorEntityType,
        payload: EditorInsertRequest,
    ) -> EditorRow:
        spec = self._spec(entity_type)
        proposed_id = str(payload.data.get(spec.id_column, "<new row>"))
        normalized = self._normalized_or_raise(spec, proposed_id, payload.data)
        row_id = str(normalized[spec.id_column])
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                existing = self.postgres.query_one(
                    f"""
                    SELECT row_id
                    FROM {self._table("editor_session_rows")}
                    WHERE session_id = %s AND entity_type = %s AND row_id = %s
                    """,
                    (session_id, entity_type, row_id),
                    connection=connection,
                )
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"{spec.id_column} {row_id!r} already exists in this editor session.",
                    )
                self.postgres.execute(
                    f"""
                    INSERT INTO {self._table("editor_session_rows")} (
                        session_id, entity_type, row_id, source_row_version, row_version,
                        operation, original_data, row_data
                    ) VALUES (%s, %s, %s, NULL, 1, 'insert', NULL, %s)
                    """,
                    (session_id, entity_type, row_id, self.postgres.jsonb(normalized)),
                    connection=connection,
                )
                self._touch_session(session_id, connection)
                self._record_audit(
                    connection=connection,
                    session_id=session_id,
                    principal=principal,
                    event_type="row_inserted",
                    entity_type=entity_type,
                    row_id=row_id,
                    after_data=normalized,
                )
                response = EditorRow(
                    entity_type=entity_type,
                    row_id=row_id,
                    row_version=1,
                    state="inserted",
                    data=normalized,
                )
        self._raise_if_expired(expired)
        return response

    def patch_row(
        self,
        session_id: str,
        principal: str,
        entity_type: EditorEntityType,
        row_id: str,
        payload: EditorPatchRequest,
    ) -> EditorRow:
        spec = self._spec(entity_type)
        if not payload.changes:
            raise HTTPException(status_code=422, detail="Provide at least one field to update.")
        attempted_id = payload.changes.get(spec.id_column)
        if attempted_id is not None:
            raise HTTPException(
                status_code=422,
                detail=f"{spec.id_column} is immutable. Add a new row instead of changing its identity.",
            )
        unknown_fields = sorted(set(payload.changes) - set(spec.columns))
        if unknown_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported fields for {entity_type}: {', '.join(unknown_fields)}.",
            )
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                row = self.postgres.query_one(
                    f"""
                    SELECT row_version, operation, row_data
                    FROM {self._table("editor_session_rows")}
                    WHERE session_id = %s AND entity_type = %s AND row_id = %s
                    FOR UPDATE
                    """,
                    (session_id, entity_type, row_id),
                    connection=connection,
                )
                if row is None:
                    raise HTTPException(status_code=404, detail="Editor row was not found.")
                if str(row["operation"]) == "delete":
                    raise HTTPException(status_code=409, detail="Editor row was already deleted.")
                current_version = int(row["row_version"])
                if current_version != payload.row_version:
                    raise HTTPException(
                        status_code=409,
                        detail="This row changed in another editor tab. Reload it before saving.",
                    )
                before_data = _json_object(row["row_data"])
                normalized = self._normalized_or_raise(
                    spec,
                    row_id,
                    {**before_data, **payload.changes},
                )
                operation = "insert" if str(row["operation"]) == "insert" else "update"
                updated = self.postgres.query_one(
                    f"""
                    UPDATE {self._table("editor_session_rows")}
                    SET row_data = %s,
                        row_version = row_version + 1,
                        operation = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = %s AND entity_type = %s AND row_id = %s
                    RETURNING row_version, operation
                    """,
                    (
                        self.postgres.jsonb(normalized),
                        operation,
                        session_id,
                        entity_type,
                        row_id,
                    ),
                    connection=connection,
                )
                if updated is None:  # pragma: no cover - protected by row lock
                    raise RuntimeError("Editor row disappeared during an update.")
                self._touch_session(session_id, connection)
                self._record_audit(
                    connection=connection,
                    session_id=session_id,
                    principal=principal,
                    event_type="row_updated",
                    entity_type=entity_type,
                    row_id=row_id,
                    before_data=before_data,
                    after_data=normalized,
                )
                response = EditorRow(
                    entity_type=entity_type,
                    row_id=row_id,
                    row_version=int(updated["row_version"]),
                    state=_row_state(str(updated["operation"])),
                    data=normalized,
                )
        self._raise_if_expired(expired)
        return response

    def delete_row(
        self,
        session_id: str,
        principal: str,
        entity_type: EditorEntityType,
        row_id: str,
        payload: EditorDeleteRequest,
    ) -> EditorSession:
        self._spec(entity_type)
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                row = self.postgres.query_one(
                    f"""
                    SELECT row_version, operation, row_data
                    FROM {self._table("editor_session_rows")}
                    WHERE session_id = %s AND entity_type = %s AND row_id = %s
                    FOR UPDATE
                    """,
                    (session_id, entity_type, row_id),
                    connection=connection,
                )
                if row is None:
                    raise HTTPException(status_code=404, detail="Editor row was not found.")
                if int(row["row_version"]) != payload.row_version:
                    raise HTTPException(
                        status_code=409,
                        detail="This row changed in another editor tab. Reload it before deleting.",
                    )
                before_data = _json_object(row["row_data"])
                if str(row["operation"]) == "insert":
                    self.postgres.execute(
                        f"""
                        DELETE FROM {self._table("editor_session_rows")}
                        WHERE session_id = %s AND entity_type = %s AND row_id = %s
                        """,
                        (session_id, entity_type, row_id),
                        connection=connection,
                    )
                else:
                    self.postgres.execute(
                        f"""
                        UPDATE {self._table("editor_session_rows")}
                        SET operation = 'delete',
                            row_version = row_version + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE session_id = %s AND entity_type = %s AND row_id = %s
                        """,
                        (session_id, entity_type, row_id),
                        connection=connection,
                    )
                session = self._touch_session(session_id, connection)
                self._record_audit(
                    connection=connection,
                    session_id=session_id,
                    principal=principal,
                    event_type="row_deleted",
                    entity_type=entity_type,
                    row_id=row_id,
                    before_data=before_data,
                )
                response = self._session_summary(session, connection)
        self._raise_if_expired(expired)
        return response

    def validate_session(
        self,
        session_id: str,
        principal: str,
    ) -> EditorValidationResponse:
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                _, issues = self._validate_session_rows(session_id, connection)
                session = self._touch_session(session_id, connection)
                self._record_audit(
                    connection=connection,
                    session_id=session_id,
                    principal=principal,
                    event_type="validated",
                    metadata={"valid": not issues, "issue_count": len(issues)},
                )
                response = EditorValidationResponse(
                    session=self._session_summary(session, connection),
                    valid=not issues,
                    issues=issues,
                )
        self._raise_if_expired(expired)
        return response

    def preview_baseline(
        self,
        session_id: str,
        principal: str,
        payload: EditorPreviewRequest,
    ) -> EditorPreviewResponse:
        expired = False
        validation_issues: list[EditorValidationIssue] = []
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                rows, validation_issues = self._validate_session_rows(session_id, connection)
                if not validation_issues:
                    depots = [row["row_data"] for row in rows["depots"]]
                    customers = [row["row_data"] for row in rows["customers"]]
                    fleet = [row["row_data"] for row in rows["fleet"]]
                    orders = [row["row_data"] for row in rows["orders"]]
                    costs = [row["row_data"] for row in rows["cost_parameters"]]
                    if payload.depot_id not in {str(row["depot_id"]) for row in depots}:
                        validation_issues.append(
                            EditorValidationIssue(
                                entity_type="depots",
                                row_id=payload.depot_id,
                                field="depot_id",
                                code="missing_reference",
                                message="The selected depot does not exist in this session.",
                            )
                        )
                    if not validation_issues:
                        baseline = reconstruct_baseline(
                            depots=depots,
                            customers=customers,
                            orders=orders,
                            fleet=fleet,
                            depot_id=payload.depot_id,
                            delivery_day=payload.delivery_day,
                            params=CostParameters.from_row(costs[0] if costs else None),
                        )
                        session = self._touch_session(session_id, connection)
                        self._record_audit(
                            connection=connection,
                            session_id=session_id,
                            principal=principal,
                            event_type="previewed",
                            metadata={
                                "depot_id": payload.depot_id,
                                "delivery_day": payload.delivery_day,
                            },
                        )
                        response = EditorPreviewResponse(
                            session=self._session_summary(session, connection),
                            network=BaselineNetwork.model_validate(baseline["network"]),
                            kpis=Kpis.model_validate(baseline["kpis"]),
                        )
                if validation_issues:
                    session = self._touch_session(session_id, connection)
                    self._record_audit(
                        connection=connection,
                        session_id=session_id,
                        principal=principal,
                        event_type="preview_rejected",
                        metadata={"issue_count": len(validation_issues)},
                    )
        self._raise_if_expired(expired)
        if validation_issues:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Fix validation issues before previewing the baseline.",
                    "issues": [issue.model_dump(mode="json") for issue in validation_issues],
                },
            )
        return response

    def _commit_conflicts(
        self,
        rows_by_entity: Mapping[EditorEntityType, list[dict[str, Any]]],
        connection: Any,
    ) -> list[EditorValidationIssue]:
        conflicts: list[EditorValidationIssue] = []
        for entity_type, rows in rows_by_entity.items():
            spec = self._spec(entity_type)
            for row in rows:
                operation = str(row["operation"])
                if operation == "unchanged":
                    continue
                current = self.postgres.query_one(
                    f"""
                    SELECT row_version
                    FROM {self._table(spec.table_name)}
                    WHERE {spec.id_column} = %s
                    FOR UPDATE
                    """,
                    (row["row_id"],),
                    connection=connection,
                )
                if operation == "insert":
                    if current is not None:
                        conflicts.append(
                            EditorValidationIssue(
                                entity_type=entity_type,
                                row_id=row["row_id"],
                                field=spec.id_column,
                                code="conflict",
                                message="A master row with this identifier was created after this session opened.",
                            )
                        )
                    continue
                expected_version = row["source_row_version"]
                if current is None:
                    conflicts.append(
                        EditorValidationIssue(
                            entity_type=entity_type,
                            row_id=row["row_id"],
                            field=spec.id_column,
                            code="conflict",
                            message="The master row was deleted after this session opened.",
                        )
                    )
                elif expected_version != int(current["row_version"]):
                    conflicts.append(
                        EditorValidationIssue(
                            entity_type=entity_type,
                            row_id=row["row_id"],
                            field=None,
                            code="conflict",
                            message="The master row changed after this session opened.",
                        )
                    )
        return conflicts

    def _promote_rows(
        self,
        rows_by_entity: Mapping[EditorEntityType, list[dict[str, Any]]],
        connection: Any,
    ) -> None:
        # Children must be removed before their parent rows. Inserts/updates do
        # the inverse so database foreign keys remain valid throughout.
        for entity_type in _DELETE_PROMOTION_ORDER:
            spec = self._spec(entity_type)
            for row in rows_by_entity[entity_type]:
                if str(row["operation"]) != "delete":
                    continue
                changed = self.postgres.execute(
                    f"""
                    DELETE FROM {self._table(spec.table_name)}
                    WHERE {spec.id_column} = %s AND row_version = %s
                    """,
                    (row["row_id"], row["source_row_version"]),
                    connection=connection,
                )
                if changed != 1:  # pragma: no cover - locked version checks run first
                    raise RuntimeError("Master row changed while applying an editor delete.")

        for entity_type in _WRITE_PROMOTION_ORDER:
            spec = self._spec(entity_type)
            mutable_columns = tuple(column for column in spec.columns if column != spec.id_column)
            for row in rows_by_entity[entity_type]:
                operation = str(row["operation"])
                if operation not in {"insert", "update"}:
                    continue
                data = row["row_data"]
                if operation == "insert":
                    columns = (*spec.columns, "row_version")
                    placeholders = ", ".join("%s" for _ in columns)
                    self.postgres.execute(
                        f"""
                        INSERT INTO {self._table(spec.table_name)} ({", ".join(columns)})
                        VALUES ({placeholders})
                        """,
                        tuple(data[column] for column in spec.columns) + (1,),
                        connection=connection,
                    )
                    continue
                assignments = ", ".join(f"{column} = %s" for column in mutable_columns)
                changed = self.postgres.execute(
                    f"""
                    UPDATE {self._table(spec.table_name)}
                    SET {assignments},
                        row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE {spec.id_column} = %s AND row_version = %s
                    """,
                    tuple(data[column] for column in mutable_columns)
                    + (row["row_id"], row["source_row_version"]),
                    connection=connection,
                )
                if changed != 1:  # pragma: no cover - locked version checks run first
                    raise RuntimeError("Master row changed while applying an editor update.")

    def _rebuild_persisted_baseline_snapshots(self, connection: Any) -> int:
        master_rows: dict[EditorEntityType, list[dict[str, Any]]] = {}
        for entity_type in _ENTITY_TYPES:
            spec = self._spec(entity_type)
            master_rows[entity_type] = [
                {
                    column: _plain_value(row.get(column))
                    for column in spec.columns
                }
                for row in self.postgres.query(
                    f"""
                    SELECT {', '.join(spec.columns)}
                    FROM {self._table(spec.table_name)}
                    ORDER BY {spec.id_column}
                    """,
                    connection=connection,
                )
            ]
        self.postgres.execute(
            f"DELETE FROM {self._table('baseline_network_snapshots')}",
            connection=connection,
        )
        costs = master_rows["cost_parameters"]
        parameters = CostParameters.from_row(costs[0] if costs else None)
        partitions = sorted(
            {
                (str(order["depot_id"]), str(order["delivery_day"]))
                for order in master_rows["orders"]
            }
        )
        for depot_id, delivery_day in partitions:
            baseline = reconstruct_baseline(
                depots=master_rows["depots"],
                customers=master_rows["customers"],
                orders=master_rows["orders"],
                fleet=master_rows["fleet"],
                depot_id=depot_id,
                delivery_day=delivery_day,
                params=parameters,
            )
            self.postgres.execute(
                f"""
                INSERT INTO {self._table("baseline_network_snapshots")} (
                    depot_id, delivery_day, network_payload, kpis_payload, generated_at
                ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    depot_id,
                    delivery_day,
                    self.postgres.jsonb(baseline["network"]),
                    self.postgres.jsonb(baseline["kpis"]),
                ),
                connection=connection,
            )
        return len(partitions)

    def commit_session(self, session_id: str, principal: str) -> EditorCommitResponse:
        expired = False
        validation_issues: list[EditorValidationIssue] = []
        conflicts: list[EditorValidationIssue] = []
        response: EditorCommitResponse | None = None
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                normalized_rows, validation_issues = self._validate_session_rows(session_id, connection)
                all_rows = self._session_rows(session_id, connection, include_deleted=True)
                if validation_issues:
                    session = self._touch_session(session_id, connection)
                    self._record_audit(
                        connection=connection,
                        session_id=session_id,
                        principal=principal,
                        event_type="commit_rejected",
                        metadata={"reason": "validation", "issue_count": len(validation_issues)},
                    )
                else:
                    # Preserve the original operation/source version metadata while
                    # applying the validated row payloads.
                    for entity_type, rows in all_rows.items():
                        validated_by_id = {
                            row["row_id"]: row["row_data"]
                            for row in normalized_rows[entity_type]
                        }
                        for row in rows:
                            if row["row_id"] in validated_by_id:
                                row["row_data"] = validated_by_id[row["row_id"]]
                    conflicts = self._commit_conflicts(all_rows, connection)
                    if conflicts:
                        session = self._touch_session(session_id, connection)
                        self._record_audit(
                            connection=connection,
                            session_id=session_id,
                            principal=principal,
                            event_type="commit_rejected",
                            metadata={"reason": "conflict", "issue_count": len(conflicts)},
                        )
                    else:
                        self._promote_rows(all_rows, connection)
                        snapshot_count = self._rebuild_persisted_baseline_snapshots(connection)
                        for entity_type, rows in all_rows.items():
                            for row in rows:
                                if str(row["operation"]) == "unchanged":
                                    continue
                                self._record_audit(
                                    connection=connection,
                                    session_id=session_id,
                                    principal=principal,
                                    event_type="row_committed",
                                    entity_type=entity_type,
                                    row_id=row["row_id"],
                                    before_data=row["original_data"],
                                    after_data=(
                                        row["row_data"]
                                        if str(row["operation"]) != "delete"
                                        else None
                                    ),
                                    metadata={"operation": row["operation"]},
                                )
                        self.postgres.execute(
                            f"DELETE FROM {self._table('editor_session_rows')} WHERE session_id = %s",
                            (session_id,),
                            connection=connection,
                        )
                        session = self.postgres.query_one(
                            f"""
                            UPDATE {self._table("editor_sessions")}
                            SET status = 'committed',
                                committed_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE session_id = %s
                            RETURNING session_id, principal, status, created_at, updated_at, expires_at
                            """,
                            (session_id,),
                            connection=connection,
                        )
                        if session is None:  # pragma: no cover - protected by session lock
                            raise RuntimeError("Editor session disappeared during commit.")
                        self._record_audit(
                            connection=connection,
                            session_id=session_id,
                            principal=principal,
                            event_type="committed",
                            metadata={"baseline_snapshot_count": snapshot_count},
                        )
                        response = EditorCommitResponse(
                            session=self._session_summary(session, connection),
                            baseline_snapshot_count=snapshot_count,
                        )
        self._raise_if_expired(expired)
        if validation_issues:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Fix validation issues before committing.",
                    "issues": [issue.model_dump(mode="json") for issue in validation_issues],
                },
            )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Master data changed after this session opened. Reload into a new session.",
                    "issues": [issue.model_dump(mode="json") for issue in conflicts],
                },
            )
        if response is None:  # pragma: no cover - guarded by terminal outcomes above
            raise RuntimeError("Editor session completed without a commit response.")

        # The solver keeps a short-lived base-table cache. Clear it only after
        # this transaction has committed so the next run observes the promoted
        # planning data and rebuilt baseline immediately.
        from .solver import solver_service

        solver_service.invalidate_base_cache()
        return response

    def discard_session(self, session_id: str, principal: str) -> EditorSession:
        expired = False
        with self.postgres.transaction() as connection:
            session = self._locked_open_session(session_id, principal, connection)
            expired = session is None
            if session is not None:
                self.postgres.execute(
                    f"DELETE FROM {self._table('editor_session_rows')} WHERE session_id = %s",
                    (session_id,),
                    connection=connection,
                )
                session = self.postgres.query_one(
                    f"""
                    UPDATE {self._table("editor_sessions")}
                    SET status = 'discarded',
                        discarded_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE session_id = %s
                    RETURNING session_id, principal, status, created_at, updated_at, expires_at
                    """,
                    (session_id,),
                    connection=connection,
                )
                if session is None:  # pragma: no cover - protected by session lock
                    raise RuntimeError("Editor session disappeared during discard.")
                self._record_audit(
                    connection=connection,
                    session_id=session_id,
                    principal=principal,
                    event_type="discarded",
                )
                response = self._session_summary(session, connection)
        self._raise_if_expired(expired)
        return response


ground_truth_store = GroundTruthStore()
