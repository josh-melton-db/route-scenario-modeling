from __future__ import annotations

import json
import threading
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from ..config import get_data_backend
from .lakebase_store import lakebase_store


class RouteMatrixCache:
    """Shared Lakebase matrix cache with a bounded process-local fallback."""

    def __init__(self, *, max_local_entries: int = 32, ttl_days: int = 7) -> None:
        self.max_local_entries = max_local_entries
        self.ttl_days = ttl_days
        self._local: OrderedDict[
            str, tuple[datetime, list[dict[str, object]]]
        ] = OrderedDict()
        self._lock = threading.Lock()

    def _table(self) -> str:
        return lakebase_store.postgres.qualified_table("route_matrix_cache")

    def get(self, key: str) -> list[dict[str, object]] | None:
        if get_data_backend() == "lakebase":
            try:
                row = lakebase_store.postgres.query_one(
                    f"UPDATE {self._table()} SET last_accessed_at = %s "
                    "WHERE cache_key = %s AND expires_at > %s RETURNING payload",
                    (datetime.now(timezone.utc), key, datetime.now(timezone.utc)),
                )
                if row is not None:
                    value = row["payload"]
                    decoded = json.loads(value) if isinstance(value, str) else value
                    if isinstance(decoded, list):
                        self._put_local(key, decoded)
                        return [dict(item) for item in decoded]
            except Exception:
                # Routing remains available during cache/database degradation.
                pass
        with self._lock:
            entry = self._local.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= datetime.now(timezone.utc):
                self._local.pop(key, None)
                return None
            self._local.move_to_end(key)
            return deepcopy(value)

    def put(self, key: str, matrix: Sequence[Mapping[str, object]]) -> None:
        detached = [dict(row) for row in matrix]
        self._put_local(key, detached)
        if get_data_backend() != "lakebase":
            return
        payload_bytes = len(json.dumps(detached, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        try:
            now = datetime.now(timezone.utc)
            lakebase_store.postgres.execute(
                f"""
                INSERT INTO {self._table()}
                    (cache_key, payload, byte_size, created_at, last_accessed_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (cache_key) DO UPDATE SET
                    payload = EXCLUDED.payload, byte_size = EXCLUDED.byte_size,
                    last_accessed_at = EXCLUDED.last_accessed_at,
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    key, lakebase_store.postgres.jsonb(detached), payload_bytes,
                    now, now, now + timedelta(days=self.ttl_days),
                ),
            )
        except Exception:
            pass

    def _put_local(self, key: str, matrix: Sequence[Mapping[str, object]]) -> None:
        with self._lock:
            self._local[key] = (
                datetime.now(timezone.utc) + timedelta(days=self.ttl_days),
                [dict(row) for row in matrix],
            )
            self._local.move_to_end(key)
            while len(self._local) > self.max_local_entries:
                self._local.popitem(last=False)


route_matrix_cache = RouteMatrixCache()
