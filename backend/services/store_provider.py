from __future__ import annotations

from ..config import get_data_backend
from .databricks_store import databricks_store
from .lakebase_store import lakebase_store
from .stub_store import store as stub_store


def get_store():
    backend = get_data_backend()
    if backend == "lakebase":
        return lakebase_store
    if backend == "databricks":
        return databricks_store
    if backend == "stub":
        return stub_store
    raise RuntimeError(
        f"Unsupported DATA_BACKEND={backend!r}. Expected lakebase, databricks, or stub."
    )
