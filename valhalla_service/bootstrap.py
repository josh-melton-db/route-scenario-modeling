from __future__ import annotations

import os
import json
import shutil
import tarfile
from pathlib import Path

from databricks.sdk import WorkspaceClient
from volume_paths import volume_files_path

target = Path("/tmp/valhalla")
shutil.rmtree(target, ignore_errors=True)
target.mkdir(parents=True)

volume_path = volume_files_path(os.environ["VALHALLA_VOLUME_PATH"])
client = WorkspaceClient()


def download_json(path: str) -> dict:
    response = client.files.download(path)
    return json.load(response.contents)


def download_and_extract(relative_path: str, archive_name: str) -> int:
    if relative_path.startswith("/") or ".." in Path(relative_path).parts:
        raise RuntimeError(f"unsafe manifest archive path: {relative_path}")
    archive = Path("/tmp") / archive_name
    response = client.files.download(f"{volume_path}/{relative_path}")
    with archive.open("wb") as output:
        shutil.copyfileobj(response.contents, output)
    with tarfile.open(archive, "r:gz") as bundle:
        root = target.resolve()
        for member in bundle.getmembers():
            destination = (root / member.name).resolve()
            if not destination.is_relative_to(root):
                raise RuntimeError(f"unsafe archive member: {member.name}")
        bundle.extractall(target)
    return archive.stat().st_size


manifest = download_json(f"{volume_path}/manifest.json")
region_id = os.environ.get("VALHALLA_REGION", manifest.get("default_region", "")).strip()
region = manifest.get("regions", {}).get(region_id)
engine = manifest.get("engine")
if not isinstance(engine, dict) or not isinstance(region, dict):
    raise RuntimeError(f"region {region_id!r} is not present in the Valhalla manifest")
engine_bytes = download_and_extract(str(engine["archive"]), "valhalla-engine.tar.gz")
region_bytes = download_and_extract(str(region["archive"]), f"valhalla-region-{region_id}.tar.gz")

(target / "bin/valhalla_service").chmod(0o755)
active = {
    "coverage_id": region.get("coverage_id", region_id),
    "region": region_id,
    "artifact_version": region.get("artifact_version"),
    "engine_version": engine.get("version"),
    "built_at": region.get("built_at"),
    "engine_archive_bytes": engine_bytes,
    "region_archive_bytes": region_bytes,
}
(target / "active-region.json").write_text(json.dumps(active), encoding="utf-8")
print(f"Loaded Valhalla region {region_id!r} from {volume_path}: {engine_bytes + region_bytes} archive bytes")
