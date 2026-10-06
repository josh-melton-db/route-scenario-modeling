"""Normalize Databricks App UC Volume resource injection values."""


def volume_files_path(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("/Volumes/"):
        return value
    parts = value.split(".")
    if len(parts) == 3 and all(parts):
        return "/Volumes/" + "/".join(parts)
    raise ValueError(
        "VALHALLA_VOLUME_PATH must be /Volumes/catalog/schema/volume or catalog.schema.volume"
    )
