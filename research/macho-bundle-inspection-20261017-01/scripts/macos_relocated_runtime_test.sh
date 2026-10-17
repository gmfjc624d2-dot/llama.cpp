#!/bin/bash
# SEPARATE runtime step on macOS for a REAL bundle (never a fixture): copy the bundle to a new
# place, run one of its programs with a clean environment and record which images dyld loaded.
#
# usage: macos_relocated_runtime_test.sh <bundle-dir> <program-rel-path> <arch> <new-run-dir> [timeout_s] -- [program args...]
#   e.g. ... ./dist bin/llama-cli arm64 ~/reloc-run-1 60 -- --version
# Exit 0 only if the program exited 0, dyld printed a load trace, and every loaded image is inside
# the copy or under /usr/lib/ or /System/Library/. The build tree is not moved or changed; hide it
# by hand before this step if the test should also prove that it is not needed.
set -u
[ "$(uname -s)" = Darwin ] || { echo "relocated test: needs macOS" >&2; exit 2; }
src=${1:-}; prog=${2:-}; arch=${3:-}; out=${4:-}; tmo=${5:-60}
shift 5 2>/dev/null || { echo "usage: see header" >&2; exit 2; }
[ "${1:-}" = "--" ] && shift
[ -d "$src" ] && [ -n "$prog" ] && [ -n "$arch" ] && [ -n "$out" ] || { echo "usage: see header" >&2; exit 2; }
[ -e "$out" ] && { echo "relocated test: $out exists; use a new run dir" >&2; exit 2; }
mkdir -p "$out" && out=$(cd "$out" && pwd)
set -o noclobber

dest=$(mktemp -d "${TMPDIR:-/tmp}/reloc.XXXXXX") || exit 2
dest=$(cd "$dest" && pwd -P)
ditto "$src" "$dest/bundle" || exit 2
{
  echo "start_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "source_bundle: $(cd "$src" && pwd -P)"
  echo "copy: $dest/bundle"
  echo "program: $prog"
  echo "arch: $arch"
  echo "timeout_s: $tmo"
  printf 'args:'; printf ' %q' "$@"; printf '\n'
  sw_vers 2>&1
  uname -a
} > "$out/run.txt"
(cd "$dest/bundle" && find . -type f -o -type l | LC_ALL=C sort) > "$out/copy.files"

# clean environment: no inherited DYLD_* or other variables; DYLD_PRINT_LIBRARIES only prints
env -i HOME="$HOME" PATH=/usr/bin:/bin TMPDIR="${TMPDIR:-/tmp}" DYLD_PRINT_LIBRARIES=1 \
  arch "-$arch" "$dest/bundle/$prog" "$@" > "$out/program.stdout" 2> "$out/program.stderr" < /dev/null &
pid=$! ticks=0
while kill -0 "$pid" 2>/dev/null; do
  if [ "$ticks" -ge $((tmo * 10)) ]; then kill -KILL "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; echo timeout > "$out/program.rc"; break; fi
  sleep 0.1; ticks=$((ticks + 1))
done
[ -e "$out/program.rc" ] || { wait "$pid"; echo $? > "$out/program.rc"; }

# dyld4 prints "dyld[pid]: <path>", older dyld "dyld: loaded: <path>"
sed -n -e 's/^dyld\[[0-9]*\]: \(\/.*\)$/\1/p' -e 's/^dyld: loaded: \(\/.*\)$/\1/p' "$out/program.stderr" > "$out/loaded.txt"
: > "$out/outside.txt"
while read -r p; do
  case "$p" in
    "$dest/bundle/"*|/usr/lib/*|/System/Library/*) ;;
    *) echo "$p" >> "$out/outside.txt" ;;
  esac
done < "$out/loaded.txt"
rc=$(cat "$out/program.rc")
verdict=pass
[ "$rc" = 0 ] || verdict="fail: program rc $rc"
[ -s "$out/loaded.txt" ] || verdict="fail: no dyld load trace"
[ -s "$out/outside.txt" ] && verdict="fail: images loaded from outside the copy"
grep -q "Library not loaded" "$out/program.stderr" && verdict="fail: Library not loaded"
echo "verdict: $verdict" | tee -a "$out/run.txt"
echo "end_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$out/run.txt"
echo "copy kept at $dest/bundle (remove by hand)"
[ "$verdict" = pass ]
