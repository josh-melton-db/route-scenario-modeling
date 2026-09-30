from __future__ import annotations

import itertools
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field


JobKey = tuple[str, str, str, str]


@dataclass(order=True)
class _QueuedJob:
    priority: int
    sequence: int
    key: JobKey = field(compare=False)
    callback: Callable[[], None] | None = field(compare=False)


class DepotPlanJobManager:
    """Small bounded priority worker pool with active-job de-duplication."""

    def __init__(self, *, max_workers: int = 2, start_workers: bool = True) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1.")
        self._queue: queue.PriorityQueue[_QueuedJob] = queue.PriorityQueue()
        self._active: set[JobKey] = set()
        self._condition = threading.Condition()
        self._sequence = itertools.count()
        self._workers: list[threading.Thread] = []
        self._closed = False
        if start_workers:
            for worker_number in range(max_workers):
                worker = threading.Thread(
                    target=self._worker,
                    name=f"depot-plan-worker-{worker_number + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def submit(
        self,
        key: JobKey,
        callback: Callable[[], None],
        *,
        priority: int = 100,
    ) -> bool:
        with self._condition:
            if self._closed:
                raise RuntimeError("Depot plan job manager is closed.")
            if key in self._active:
                return False
            self._active.add(key)
            self._queue.put(
                _QueuedJob(
                    priority=priority,
                    sequence=next(self._sequence),
                    key=key,
                    callback=callback,
                )
            )
            self._condition.notify_all()
            return True

    def is_active(self, key: JobKey) -> bool:
        with self._condition:
            return key in self._active

    def wait_for_idle(self, timeout: float = 10.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._active, timeout=timeout)

    def run_next(self) -> bool:
        """Run one queued job synchronously; useful for deterministic tests."""

        try:
            job = self._queue.get_nowait()
        except queue.Empty:
            return False
        if job.callback is None:
            self._queue.task_done()
            return False
        self._execute(job)
        return True

    def shutdown(self) -> None:
        with self._condition:
            self._closed = True
        for _ in self._workers:
            self._queue.put(
                _QueuedJob(
                    priority=10**9,
                    sequence=next(self._sequence),
                    key=("", "", "", ""),
                    callback=None,
                )
            )
        for worker in self._workers:
            worker.join(timeout=1.0)

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            if job.callback is None:
                self._queue.task_done()
                return
            try:
                self._execute(job)
            except Exception:
                continue

    def _execute(self, job: _QueuedJob) -> None:
        try:
            if job.callback is not None:
                job.callback()
        finally:
            self._queue.task_done()
            with self._condition:
                self._active.discard(job.key)
                self._condition.notify_all()


depot_plan_job_manager = DepotPlanJobManager()
