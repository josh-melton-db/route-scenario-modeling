from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CATALOG = "demos"
DEFAULT_SCHEMA = "route_scenario_modeling"
DEFAULT_RAW_VOLUME = "raw"
DEFAULT_MATRIX_SOURCE = "haversine_circuity"
DEFAULT_GENERATED_AT = "2026-07-02T12:00:00Z"


@dataclass(frozen=True)
class PipelineConfig:
    catalog: str = DEFAULT_CATALOG
    schema: str = DEFAULT_SCHEMA
    raw_volume: str = DEFAULT_RAW_VOLUME

    @property
    def raw_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.raw_volume}"

    def table(self, name: str) -> str:
        return f"{self.catalog}.{self.schema}.{name}"


def get_widget_value(name: str, default: str) -> str:
    """Read Databricks widget value when available, otherwise return a default.

    The notebooks also run as plain Python scripts in local tests, where
    `dbutils` is not defined.
    """

    try:
        value = dbutils.widgets.get(name)  # type: ignore[name-defined]
    except Exception:
        return default
    return value or default


def config_from_widgets() -> PipelineConfig:
    return PipelineConfig(
        catalog=get_widget_value("catalog", DEFAULT_CATALOG),
        schema=get_widget_value("schema", DEFAULT_SCHEMA),
        raw_volume=get_widget_value("raw_volume", DEFAULT_RAW_VOLUME),
    )
