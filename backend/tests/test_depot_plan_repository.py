from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from backend.services.depot_plan_repository import DepotPlanRepository


def _record(
    plan_set_id: str = "DPS-1",
    parent_run_id: str = "RUN-1",
    depot_id: str = "DPT-1",
) -> dict[str, object]:
    return {
        "plan_set_id": plan_set_id,
        "parent_run_id": parent_run_id,
        "depot_id": depot_id,
        "counter": 0,
        "days": {
            "2026-09-30": {
                "default_status": "queued",
                "override_status": None,
                "results": [],
            }
        },
    }


def test_create_find_get_and_unique_parent_depot_return_detached_copies() -> None:
    repository = DepotPlanRepository()
    original = _record()

    created = repository.create(original)
    original["counter"] = 99
    created["counter"] = 88

    assert repository.get("DPS-1")["counter"] == 0
    found = repository.find("RUN-1", "DPT-1")
    assert found is not None
    found["counter"] = 77
    assert repository.get("DPS-1")["counter"] == 0

    duplicate = repository.create(_record("DPS-2", "RUN-1", "DPT-1"))
    assert duplicate["plan_set_id"] == "DPS-1"
    assert repository.find("RUN-1", "DPT-1") == repository.get("DPS-1")


def test_mutate_is_atomic_and_returns_detached_copy() -> None:
    repository = DepotPlanRepository()
    repository.create(_record())

    def increment(_: int) -> None:
        repository.mutate(
            "DPS-1",
            lambda record: record.__setitem__(
                "counter", int(record["counter"]) + 1
            ),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(200)))

    assert repository.get("DPS-1")["counter"] == 200
    mutated = repository.mutate(
        "DPS-1", lambda record: record.__setitem__("counter", 201)
    )
    mutated["counter"] = -1
    assert repository.get("DPS-1")["counter"] == 201


def test_list_pending_tracks_queued_and_running_days() -> None:
    repository = DepotPlanRepository()
    repository.create(_record())
    completed = _record("DPS-2", "RUN-2", "DPT-2")
    completed["days"] = {
        "2026-09-30": {
            "default_status": "completed",
            "override_status": None,
        }
    }
    repository.create(completed)

    assert [row["plan_set_id"] for row in repository.list_pending()] == ["DPS-1"]

    repository.mutate(
        "DPS-1",
        lambda record: record["days"]["2026-09-30"].update(
            default_status="completed"
        ),
    )
    assert repository.list_pending() == []


def test_missing_record_errors_are_clear() -> None:
    repository = DepotPlanRepository()

    with pytest.raises(HTTPException) as get_error:
        repository.get("missing")
    assert get_error.value.status_code == 404
    assert get_error.value.detail == "Depot plan not found."

    with pytest.raises(HTTPException) as mutate_error:
        repository.mutate("missing", lambda _: None)
    assert mutate_error.value.status_code == 404

