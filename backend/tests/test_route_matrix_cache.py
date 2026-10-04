from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.services import route_matrix_cache as cache_module
from backend.services.route_matrix_cache import RouteMatrixCache


class _FakePostgres:
    def __init__(self) -> None:
        self.row: dict[str, object] | None = None
        self.error: Exception | None = None
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    @staticmethod
    def qualified_table(name: str) -> str:
        return name

    @staticmethod
    def jsonb(value: object) -> object:
        return value

    def query_one(self, _sql: str, _params: tuple[object, ...]) -> dict[str, object] | None:
        if self.error is not None:
            raise self.error
        return self.row

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        if self.error is not None:
            raise self.error
        self.executed.append((sql, params))


def _use_lakebase(monkeypatch, postgres: _FakePostgres) -> None:
    monkeypatch.setattr(cache_module, "get_data_backend", lambda: "lakebase")
    monkeypatch.setattr(cache_module.lakebase_store, "postgres", postgres)


def test_shared_cache_hit_is_returned_and_detached(monkeypatch) -> None:
    postgres = _FakePostgres()
    postgres.row = {"payload": [{"origin_id": "A", "destination_id": "B"}]}
    _use_lakebase(monkeypatch, postgres)
    cache = RouteMatrixCache()

    hit = cache.get("matrix-1")

    assert hit == [{"origin_id": "A", "destination_id": "B"}]
    hit[0]["origin_id"] = "changed"
    postgres.error = RuntimeError("database unavailable")
    assert cache.get("matrix-1")[0]["origin_id"] == "A"


def test_database_failure_falls_back_to_bounded_local_cache(monkeypatch) -> None:
    postgres = _FakePostgres()
    postgres.error = RuntimeError("database unavailable")
    _use_lakebase(monkeypatch, postgres)
    cache = RouteMatrixCache(max_local_entries=1)

    cache.put("first", [{"value": 1}])
    assert cache.get("first") == [{"value": 1}]
    cache.put("second", [{"value": 2}])

    assert cache.get("first") is None
    assert cache.get("second") == [{"value": 2}]


def test_expired_local_entry_is_a_cache_miss(monkeypatch) -> None:
    monkeypatch.setattr(cache_module, "get_data_backend", lambda: "stub")
    cache = RouteMatrixCache()
    cache.put("expired", [{"value": 1}])
    _expires_at, value = cache._local["expired"]
    cache._local["expired"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1),
        value,
    )

    assert cache.get("expired") is None
    assert "expired" not in cache._local
