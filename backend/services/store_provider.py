from __future__ import annotations

from ..config import get_data_backend
from .databricks_store import databricks_store
from .stub_store import store as stub_store


def get_store():
    return databricks_store if get_data_backend() == "databricks" else stub_store
