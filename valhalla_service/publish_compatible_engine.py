# Databricks notebook source
dbutils.widgets.text("VOLUME_PATH", "")

import os
import shutil
import tarfile
from pathlib import Path

volume_path = dbutils.widgets.get("VOLUME_PATH").rstrip("/")
if not volume_path.startswith("/Volumes/"):
    raise ValueError("VOLUME_PATH must be /Volumes/<catalog>/<schema>/<volume>")

source = Path(volume_path) / "runtime"
if not (source / "bin" / "valhalla_service").exists():
    raise FileNotFoundError("The proven DBR 15.4 runtime tree is missing")

staging = Path("/local_disk0/valhalla-compatible-engine")
shutil.rmtree(staging, ignore_errors=True)
shutil.copytree(source / "bin", staging / "bin", symlinks=False)
shutil.copytree(source / "lib", staging / "lib", symlinks=False)

destination = Path(volume_path) / "engine" / "valhalla-3.5.1"
destination.mkdir(parents=True, exist_ok=True)
temporary_archive = destination / "runtime.tar.gz.tmp"
with tarfile.open(temporary_archive, "w:gz") as bundle:
    bundle.add(staging / "bin", arcname="bin")
    bundle.add(staging / "lib", arcname="lib")
os.replace(temporary_archive, destination / "runtime.tar.gz")

print(f"Published compatible engine archive: {(destination / 'runtime.tar.gz').stat().st_size} bytes")
