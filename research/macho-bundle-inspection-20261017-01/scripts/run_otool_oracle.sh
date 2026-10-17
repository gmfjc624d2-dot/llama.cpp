#!/usr/bin/env bash
# usage: run_otool_oracle.sh <otool> <fixture-dir> <log-dir>
# Runs <otool> -l (loadcommands__*) and -L (dependencies__*) on every parse fixture and regular bundle file (no symlinks).
# Log names must stay unique under case folding (macOS volumes).
# otool reads the files as data; nothing is executed.
set -u
otool=$1; fx=$2; out=$3
here=$(cd "$(dirname "$0")" && pwd)
cd "$fx" || exit 1
{ find parse -type f -name '*.bin'; find bundles -type f; } | LC_ALL=C sort | while read -r f; do
  n=$(printf '%s' "$f" | tr '/' '_')
  "$here/logrun.sh" "$out" "loadcommands__$n" "$otool" -l "$f" > /dev/null
  "$here/logrun.sh" "$out" "dependencies__$n" "$otool" -L "$f" > /dev/null
done
echo "run_otool_oracle: done"
