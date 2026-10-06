# Databricks notebook source
dbutils.widgets.text("VOLUME_PATH", "")
dbutils.widgets.text("REGION_ID", "michigan")
dbutils.widgets.text(
    "PBF_URL",
    "https://download.geofabrik.de/north-america/us/michigan-latest.osm.pbf",
)
dbutils.widgets.text("ARTIFACT_VERSION", "")
dbutils.widgets.text("COVERAGE_ID", "")
dbutils.widgets.dropdown("REBUILD_ENGINE", "false", ["false", "true"])

import os
import re

volume_path = dbutils.widgets.get("VOLUME_PATH").rstrip("/")
region_id = dbutils.widgets.get("REGION_ID").strip().lower()
pbf_url = dbutils.widgets.get("PBF_URL").strip()
artifact_version = dbutils.widgets.get("ARTIFACT_VERSION").strip()
coverage_id = dbutils.widgets.get("COVERAGE_ID").strip() or region_id
rebuild_engine = dbutils.widgets.get("REBUILD_ENGINE") == "true"
if not volume_path.startswith("/Volumes/"):
    raise ValueError("VOLUME_PATH must be /Volumes/<catalog>/<schema>/<volume>")
if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", region_id):
    raise ValueError("REGION_ID must contain lowercase letters, numbers, and hyphens")
if not pbf_url.startswith("https://"):
    raise ValueError("PBF_URL must use HTTPS")
if artifact_version and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", artifact_version):
    raise ValueError("ARTIFACT_VERSION contains unsupported characters")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", coverage_id):
    raise ValueError("COVERAGE_ID contains unsupported characters")
os.environ.update(
    VALHALLA_VOLUME_PATH=volume_path,
    VALHALLA_REGION_ID=region_id,
    VALHALLA_PBF_URL=pbf_url,
    VALHALLA_REBUILD_ENGINE=str(rebuild_engine).lower(),
)

# COMMAND ----------

# MAGIC %sh
# MAGIC set -euxo pipefail
# MAGIC sudo apt-get update -qq
# MAGIC sudo apt-get install -y -qq git cmake make g++ jq wget rsync
# MAGIC rm -rf /local_disk0/valhalla-build
# MAGIC git clone --depth 1 --branch 3.5.1 --recurse-submodules --shallow-submodules https://github.com/valhalla/valhalla.git /local_disk0/valhalla-build
# MAGIC cd /local_disk0/valhalla-build
# MAGIC ./scripts/install-linux-deps.sh
# MAGIC cmake -B build -DCMAKE_BUILD_TYPE=Release -DENABLE_PYTHON_BINDINGS=OFF -DENABLE_TESTS=OFF -DENABLE_BENCHMARKS=OFF
# MAGIC cmake --build build --parallel 16
# MAGIC sudo cmake --install build
# MAGIC sudo ldconfig

# COMMAND ----------

# MAGIC %sh
# MAGIC set -eux
# MAGIC root=/local_disk0/valhalla-artifacts
# MAGIC engine="$root/engine"
# MAGIC region="$root/region"
# MAGIC region_id="${VALHALLA_REGION_ID:?}"
# MAGIC rm -rf "$root"
# MAGIC mkdir -p "$engine/bin" "$engine/lib" "$region/regions/$region_id/tiles"
# MAGIC pbf="$root/$region_id.osm.pbf"
# MAGIC wget -q -O "$pbf" "${VALHALLA_PBF_URL:?}"
# MAGIC tile_dir="$region/regions/$region_id/tiles"
# MAGIC valhalla_build_config \
# MAGIC   --mjolnir-tile-dir "$tile_dir" \
# MAGIC   --mjolnir-tile-extract "$tile_dir/tiles.tar" \
# MAGIC   --mjolnir-timezone "$tile_dir/timezones.sqlite" \
# MAGIC   --mjolnir-admin "$tile_dir/admins.sqlite" > "$root/valhalla.build.json"
# MAGIC valhalla_build_timezones > "$tile_dir/timezones.sqlite"
# MAGIC valhalla_build_admins -c "$root/valhalla.build.json" "$pbf"
# MAGIC valhalla_build_tiles -c "$root/valhalla.build.json" "$pbf"
# MAGIC valhalla_build_extract -c "$root/valhalla.build.json" -v
# MAGIC runtime_tile_dir="/tmp/valhalla/regions/$region_id/tiles"
# MAGIC jq --arg from "$tile_dir" --arg to "$runtime_tile_dir" \
# MAGIC   'walk(if type == "string" and startswith($from) then $to + (.[($from|length):]) else . end) | .service_limits.auto.max_locations = 500 | .service_limits.auto.max_matrix_location_pairs = 250000 | .service_limits.auto.max_matrix_distance = 1000000 | .service_limits.taxi.max_locations = 500 | .service_limits.taxi.max_matrix_location_pairs = 250000 | .service_limits.taxi.max_matrix_distance = 1000000 | .service_limits.truck.max_locations = 500 | .service_limits.truck.max_matrix_location_pairs = 250000 | .service_limits.truck.max_matrix_distance = 1000000' \
# MAGIC   "$root/valhalla.build.json" > "$tile_dir/valhalla.json"
# MAGIC rm "$pbf" "$root/valhalla.build.json"
# MAGIC cp /usr/local/bin/valhalla_service "$engine/bin/"
# MAGIC for seed in liblapack.so.3 libblas.so.3 libgfortran.so.5 libquadmath.so.0; do
# MAGIC   path=$(ldconfig -p | awk -v name="$seed" '$1 == name && !found {found=$NF} END {print found}')
# MAGIC   test -z "$path" || cp -L "$path" "$engine/lib/"
# MAGIC done
# MAGIC for pass in 1 2 3 4; do
# MAGIC   find "$engine/bin" "$engine/lib" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' binary; do
# MAGIC     { ldd "$binary" 2>/dev/null || true; } | awk '/=> \//|^\s*\// {for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}' | while read -r dependency; do
# MAGIC       case "$dependency" in
# MAGIC         */libc.so.*|*/libm.so.*|*/libpthread.so.*|*/libdl.so.*|*/librt.so.*|*/ld-linux-*.so.*) ;;
# MAGIC         *) test -e "$engine/lib/$(basename "$dependency")" || cp -L "$dependency" "$engine/lib/" ;;
# MAGIC       esac
# MAGIC     done
# MAGIC   done
# MAGIC done

# COMMAND ----------

# MAGIC %sh
# MAGIC set -euxo pipefail
# MAGIC root=/local_disk0/valhalla-artifacts
# MAGIC region_id="${VALHALLA_REGION_ID:?}"
# MAGIC volume="${VALHALLA_VOLUME_PATH:?}"
# MAGIC mkdir -p "$volume/engine/valhalla-3.5.1" "$volume/regions/$region_id"
# MAGIC engine_archive="$volume/engine/valhalla-3.5.1/runtime.tar.gz"
# MAGIC region_tmp="$volume/regions/$region_id/region.tar.gz.tmp"
# MAGIC if test "${VALHALLA_REBUILD_ENGINE:-false}" != "true" && test -s "$engine_archive"; then
# MAGIC   echo "Preserving existing validated engine archive: $engine_archive"
# MAGIC else
# MAGIC   engine_tmp="$engine_archive.tmp"
# MAGIC   tar -C "$root/engine" -czf "$engine_tmp" .
# MAGIC   mv "$engine_tmp" "$engine_archive"
# MAGIC fi
# MAGIC tar -C "$root/region" -czf "$region_tmp" .
# MAGIC mv "$region_tmp" "$volume/regions/$region_id/region.tar.gz"
# MAGIC du -sh "$engine_archive" "$volume/regions/$region_id/region.tar.gz"

# COMMAND ----------

import json
from datetime import datetime, timezone

manifest_path = f"{volume_path}/manifest.json"
manifest = {}
if os.path.exists(manifest_path):
    with open(manifest_path, encoding="utf-8") as existing:
        manifest = json.load(existing)
regions = manifest.setdefault("regions", {})
regions[region_id] = {
    "archive": f"regions/{region_id}/region.tar.gz",
    "pbf_url": pbf_url,
    "artifact_version": artifact_version or f"{region_id}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "coverage_id": coverage_id,
    "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
manifest.update(
    schema_version=1,
    engine={
        "version": "3.5.1",
        "archive": "engine/valhalla-3.5.1/runtime.tar.gz",
        "rebuild_requested": rebuild_engine,
    },
    default_region=region_id,
)
temporary_manifest_path = f"{manifest_path}.tmp"
with open(temporary_manifest_path, "w", encoding="utf-8") as output:
    json.dump(manifest, output, indent=2, sort_keys=True)
os.replace(temporary_manifest_path, manifest_path)

# COMMAND ----------

manifest_path = f"{volume_path}/manifest.json"
assert os.path.exists(manifest_path)
assert os.path.exists(f"{volume_path}/regions/{region_id}/region.tar.gz")
print(f"Valhalla region {region_id!r} is ready: {manifest_path}")
