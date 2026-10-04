from __future__ import annotations

import pytest

from backend.services.depot_plan_jobs import DepotPlanJobManager, DepotPlanQueueFullError


def test_job_manager_prioritizes_and_deduplicates_active_jobs() -> None:
    manager = DepotPlanJobManager(max_workers=1, start_workers=False)
    calls: list[str] = []
    low_key = ("plan", "2026-10-02", "default", "low")
    high_key = ("plan", "2026-10-01", "default", "high")

    assert manager.submit(low_key, lambda: calls.append("low"), priority=100)
    assert manager.submit(high_key, lambda: calls.append("high"), priority=0)
    assert not manager.submit(high_key, lambda: calls.append("duplicate"), priority=0)

    assert manager.run_next()
    assert manager.run_next()
    assert calls == ["high", "low"]
    assert manager.wait_for_idle(timeout=0.1)


def test_job_manager_releases_key_after_failure() -> None:
    manager = DepotPlanJobManager(max_workers=1, start_workers=False)
    key = ("plan", "2026-10-01", "default", "job")

    def fail() -> None:
        raise RuntimeError("expected")

    assert manager.submit(key, fail)
    try:
        manager.run_next()
    except RuntimeError as exc:
        assert str(exc) == "expected"
    assert not manager.is_active(key)
    assert manager.submit(key, lambda: None)


def test_job_manager_rejects_work_when_bounded_queue_is_full() -> None:
    manager = DepotPlanJobManager(
        max_workers=1, max_queue_size=1, start_workers=False
    )
    assert manager.submit(("plan", "2026-10-01", "default", "one"), lambda: None)
    with pytest.raises(DepotPlanQueueFullError, match="queue is full"):
        manager.submit(("plan", "2026-10-02", "default", "two"), lambda: None)
