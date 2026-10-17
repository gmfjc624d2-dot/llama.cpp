#!/usr/bin/env bash
# usage: run_otool_oracle.sh <otool> <fixture-dir> <log-dir>
# Runs <otool> -l and -L on every parse fixture and every regular bundle file (no symlinks).
# otool reads the files as data; nothing is executed.
set -u
otool=$1; fx=$2; out=$3
here=$(cd "$(dirname "$0")" && pwd)
cd "$fx" || exit 1
{ find parse -type f -name '*.bin'; find bundles -type f; } | LC_ALL=C sort | while read -r f; do
  n=$(printf '%s' "$f" | tr '/' '_')
  "$here/logrun.sh" "$out" "l__$n" "$otool" -l "$f" > /dev/null
  "$here/logrun.sh" "$out" "L__$n" "$otool" -L "$f" > /dev/null
done
echo "run_otool_oracle: done"
