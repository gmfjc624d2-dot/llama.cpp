#!/usr/bin/env bash
# usage: logrun.sh <log-dir> <name> <cmd> [args...]
# Runs cmd, writes <name>.cmd, <name>.log (stdout+stderr), <name>.exit. Never overwrites.
set -u -o noclobber
dir=$1; name=$2; shift 2
mkdir -p "$dir"
for f in "$dir/$name.cmd" "$dir/$name.log" "$dir/$name.exit"; do
  if [ -e "$f" ]; then echo "logrun: refuse to overwrite $f" >&2; exit 97; fi
done
{
  printf 'cwd: %s\n' "$PWD"
  printf 'start_utc: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'argv:'; printf ' %q' "$@"; printf '\n'
} > "$dir/$name.cmd"
"$@" > "$dir/$name.log" 2>&1
rc=$?
printf 'end_utc: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/$name.cmd"
printf '%s\n' "$rc" > "$dir/$name.exit"
echo "logrun: $name exit=$rc log=$dir/$name.log"
exit $rc
