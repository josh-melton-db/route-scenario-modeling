"""Route optimization pipeline package.

The package keeps Databricks notebooks thin: generation, baseline reconstruction,
scenario materialization, solving, comparison, metric view publishing, and tests
all use the same Python functions.
"""

from .config import DEFAULT_CATALOG, DEFAULT_SCHEMA

__all__ = ["DEFAULT_CATALOG", "DEFAULT_SCHEMA"]
