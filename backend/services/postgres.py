"""Lakebase PostgreSQL connectivity for the interactive application.

The pool is deliberately lazy: local stub and Unity Catalog fallback flows do
not import or connect through psycopg.  When an endpoint resource path is
available, every newly opened connection gets a fresh database OAuth token.
That is the supported refresh boundary for Lakebase credentials.
"""

from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from threading import RLock
from typing import Any, Iterator, Mapping, Sequence

from ..config import (
    get_lakebase_connect_retries,
    get_lakebase_connect_timeout_seconds,
    get_lakebase_endpoint,
    get_lakebase_pool_max_size,
    get_lakebase_pool_min_size,
    get_lakebase_schema,
    get_workspace_client,
)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LakebaseConfigurationError(RuntimeError):
    """Raised when the app has selected Lakebase without its connection inputs."""


class PostgresService:
    """Small psycopg3 pool wrapper with Lakebase-safe defaults.

    Databricks Apps inject ``PGHOST``, ``PGDATABASE``, ``PGUSER``, and usually
    ``PGPASSWORD`` for an attached Postgres resource.  Local development can
    instead set ``LAKEBASE_ENDPOINT`` and let the Databricks SDK mint a fresh
    database credential whenever the pool opens a new connection.
    """

    def __init__(self, schema: str | None = None) -> None:
        self.schema = schema or get_lakebase_schema()
        self._validate_identifier(self.schema, "LAKEBASE_APP_SCHEMA")
        self._pool: Any | None = None
        self._pool_lock = RLock()

    @staticmethod
    def _validate_identifier(value: str, setting: str) -> None:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise LakebaseConfigurationError(
                f"{setting} must be a PostgreSQL identifier containing only letters, numbers, and underscores."
            )

    def qualified_table(self, table_name: str) -> str:
        self._validate_identifier(table_name, "table name")
        return f'"{self.schema}"."{table_name}"'

    def initialize(self) -> None:
        """Open the pool early enough to surface configuration failures at startup."""
        self._get_pool()

    def close(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    def _get_pool(self) -> Any:
        with self._pool_lock:
            if self._pool is None:
                self._pool = self._create_pool()
            return self._pool

    def _create_pool(self) -> Any:
        try:
            import psycopg
            from psycopg.conninfo import make_conninfo
            from psycopg_pool import ConnectionPool  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on deployment environment
            raise LakebaseConfigurationError(
                "Lakebase requires psycopg[binary,pool]; install the application requirements first."
            ) from exc

        host = os.getenv("PGHOST", "").strip()
        database = os.getenv("PGDATABASE", "").strip()
        user = os.getenv("PGUSER", "").strip()
        password = os.getenv("PGPASSWORD", "").strip()
        endpoint = get_lakebase_endpoint()
        missing = [
            name
            for name, value in (("PGHOST", host), ("PGDATABASE", database), ("PGUSER", user))
            if not value
        ]
        if missing:
            raise LakebaseConfigurationError(
                "Lakebase is selected but missing required connection settings: "
                + ", ".join(missing)
                + ". Deploy the app with its Postgres resource before running locally."
            )
        if not endpoint and not password:
            raise LakebaseConfigurationError(
                "Set PGPASSWORD from a Lakebase credential or set LAKEBASE_ENDPOINT so the SDK can refresh OAuth credentials."
            )

        conninfo = make_conninfo(
            host=host,
            port=os.getenv("PGPORT", "5432").strip() or "5432",
            dbname=database,
            user=user,
            sslmode=os.getenv("PGSSLMODE", "require").strip() or "require",
            connect_timeout=get_lakebase_connect_timeout_seconds(),
        )
        connection_class: Any = psycopg.Connection
        if endpoint:
            workspace_client = get_workspace_client()

            class OAuthConnection(psycopg.Connection):
                @classmethod
                def connect(cls, conninfo: str = "", **kwargs: Any) -> Any:
                    credential = workspace_client.postgres.generate_database_credential(
                        endpoint=endpoint
                    )
                    kwargs["password"] = credential.token
                    return super().connect(conninfo, **kwargs)

            connection_class = OAuthConnection
        else:
            conninfo = make_conninfo(conninfo, password=password)

        return ConnectionPool(
            conninfo=conninfo,
            connection_class=connection_class,
            min_size=get_lakebase_pool_min_size(),
            max_size=get_lakebase_pool_max_size(),
            kwargs={"autocommit": True},
            open=True,
        )

    def _acquire_checked_connection(self) -> tuple[Any, Any]:
        """Acquire a checked connection, retrying the first wake-up from scale-to-zero."""
        pool = self._get_pool()
        attempts = get_lakebase_connect_retries()
        last_error: Exception | None = None
        for attempt in range(attempts):
            connection: Any | None = None
            try:
                connection = pool.getconn()
                connection.execute("SELECT 1")
                return pool, connection
            except Exception as exc:  # connection establishment errors are driver-specific
                last_error = exc
                if connection is not None:
                    try:
                        pool.putconn(connection, close=True)
                    except Exception:
                        pass
                if attempt + 1 < attempts:
                    time.sleep(min(0.25 * (2**attempt), 2.0))
        raise LakebaseConfigurationError(
            f"Unable to connect to Lakebase after {attempts} attempt(s): {last_error}"
        ) from last_error

    @contextmanager
    def connection(self) -> Iterator[Any]:
        pool, connection = self._acquire_checked_connection()
        try:
            yield connection
        finally:
            pool.putconn(connection)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self.connection() as connection:
            with connection.transaction():
                yield connection

    @staticmethod
    def jsonb(value: Any) -> Any:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - guarded by connection setup
            raise LakebaseConfigurationError(
                "Lakebase requires psycopg[binary,pool]; install the application requirements first."
            ) from exc
        return Jsonb(value)

    @staticmethod
    def _cursor(connection: Any) -> Any:
        from psycopg.rows import dict_row

        return connection.cursor(row_factory=dict_row)

    def query(
        self,
        statement: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
        *,
        connection: Any | None = None,
    ) -> list[dict[str, Any]]:
        if connection is None:
            with self.connection() as acquired:
                return self.query(statement, params, connection=acquired)
        with self._cursor(connection) as cursor:
            cursor.execute(statement, params)
            return [dict(row) for row in cursor.fetchall()]

    def query_one(
        self,
        statement: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
        *,
        connection: Any | None = None,
    ) -> dict[str, Any] | None:
        if connection is None:
            with self.connection() as acquired:
                return self.query_one(statement, params, connection=acquired)
        with self._cursor(connection) as cursor:
            cursor.execute(statement, params)
            row = cursor.fetchone()
            return dict(row) if row is not None else None

    def execute(
        self,
        statement: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
        *,
        connection: Any | None = None,
    ) -> int:
        if connection is None:
            with self.connection() as acquired:
                return self.execute(statement, params, connection=acquired)
        with self._cursor(connection) as cursor:
            cursor.execute(statement, params)
            return int(cursor.rowcount or 0)

    def executemany(
        self,
        statement: str,
        rows: Sequence[Sequence[Any] | Mapping[str, Any]],
        *,
        connection: Any,
    ) -> int:
        if not rows:
            return 0
        with self._cursor(connection) as cursor:
            cursor.executemany(statement, rows)
            return int(cursor.rowcount or 0)
