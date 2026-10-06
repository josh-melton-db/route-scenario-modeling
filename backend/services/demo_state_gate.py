from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException


class DemoStateGate:
    """Reject new mutable work for the full synchronous or asynchronous reset."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._resetting = False

    def begin_reset(self) -> None:
        with self._lock:
            if self._resetting:
                raise HTTPException(status_code=409, detail="A demo reset is already running.")
            self._resetting = True

    def end_reset(self) -> None:
        with self._lock:
            self._resetting = False

    @contextmanager
    def admission(self) -> Iterator[None]:
        with self._lock:
            if self._resetting:
                raise HTTPException(status_code=409, detail="Demo reset is in progress; retry when it completes.")
            yield


demo_state_gate = DemoStateGate()
