# Databricks notebook source
dbutils.widgets.text("VOLUME_PATH", "")

import os

volume_path = dbutils.widgets.get("VOLUME_PATH").rstrip("/")
if not volume_path.startswith("/Volumes/"):
    raise ValueError("VOLUME_PATH must be /Volumes/<catalog>/<schema>/<volume>")
os.environ["VALHALLA_VOLUME_PATH"] = volume_path

# COMMAND ----------

# MAGIC %sh
# MAGIC set -eux
# MAGIC runtime="${VALHALLA_VOLUME_PATH:?}/runtime"
# MAGIC libdir="$runtime/lib"
# MAGIC for seed in liblapack.so.3 libblas.so.3 libgfortran.so.5 libquadmath.so.0; do
# MAGIC   path=$(ldconfig -p | awk -v name="$seed" '$1 == name {print $NF; exit}')
# MAGIC   test -z "$path" || cp -L "$path" "$libdir/"
# MAGIC done
# MAGIC for pass in 1 2 3 4; do
# MAGIC   find "$runtime/bin" "$libdir" -maxdepth 1 -type f -print0 | while IFS= read -r -d '' binary; do
# MAGIC     { ldd "$binary" 2>/dev/null || true; } | awk '/=> \/|^\s*\// {for(i=1;i<=NF;i++) if ($i ~ /^\//) print $i}' | while read -r dependency; do
# MAGIC       case "$dependency" in
# MAGIC         */libc.so.*|*/libm.so.*|*/libpthread.so.*|*/libdl.so.*|*/librt.so.*|*/ld-linux-*.so.*) ;;
# MAGIC         *) test -e "$libdir/$(basename "$dependency")" || cp -L "$dependency" "$libdir/" ;;
# MAGIC       esac
# MAGIC     done
# MAGIC   done
# MAGIC done
# MAGIC tar -C "$runtime" -czf "${VALHALLA_VOLUME_PATH}/runtime.tar.gz" .
# MAGIC du -sh "$runtime" "${VALHALLA_VOLUME_PATH}/runtime.tar.gz"
