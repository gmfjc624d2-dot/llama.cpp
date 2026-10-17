#!/bin/bash
# Static replay of the public fixtures with otool, lipo and file. Fixtures are only passed as
# arguments to these readers; no fixture is ever run.
#
# usage: replay_otool.sh <macos-native|linux-llvm> <fixture-dir> <new-run-dir> [timeout_s] [max_bytes] [mem_kib]
#   macos-native: otool and lipo from `xcrun --find`, /usr/bin/file. Refuses to run off macOS.
#   linux-llvm:   $OTOOL $LIPO $FILE (default llvm-otool-18 llvm-lipo-18 file). LLVM results, not macOS.
# Each case writes cases/cNNNNN.{cmd,stdout,stderr,rc}; rc is a number, "timeout" or "skipped_size".
# Case names are numbers so they stay unique on case-insensitive volumes; labels are in index.tsv.
set -u
plat=${1:-}; fx=${2:-}; out=${3:-}; tmo=${4:-20}; maxb=${5:-1048576}; memkb=${6:-1048576}
archs=${ARCHS:-"arm64 x86_64"}
case "$plat" in
  macos-native)
    [ "$(uname -s)" = Darwin ] || { echo "replay_otool: macos-native needs macOS" >&2; exit 2; }
    OTOOL=$(xcrun --find otool) || exit 2
    LIPO=$(xcrun --find lipo) || exit 2
    FILE=/usr/bin/file ;;
  linux-llvm)
    OTOOL=${OTOOL:-llvm-otool-18}; LIPO=${LIPO:-llvm-lipo-18}; FILE=${FILE:-file} ;;
  *)
    echo "usage: replay_otool.sh <macos-native|linux-llvm> <fixture-dir> <new-run-dir> [timeout_s] [max_bytes] [mem_kib]" >&2; exit 2 ;;
esac
[ -d "$fx/parse" ] && [ -d "$fx/bundles" ] || { echo "replay_otool: $fx has no parse/ and bundles/" >&2; exit 2; }
[ -e "$out" ] && { echo "replay_otool: $out exists; use a new run dir" >&2; exit 2; }
mkdir -p "$out/cases" || exit 2
out=$(cd "$out" && pwd)
set -o noclobber

n=0
run() {  # run <label> <cmd> [args...]
  local label=$1; shift
  n=$((n + 1))
  local id; id=$(printf 'c%05d' "$n")
  local b="$out/cases/$id"
  { printf 'label: %s\n' "$label"; printf 'argv:'; printf ' %q' "$@"; printf '\n'; } > "$b.cmd"
  ( ulimit -t "$tmo" 2>/dev/null; ulimit -v "$memkb" 2>/dev/null; exec "$@" ) > "$b.stdout" 2> "$b.stderr" < /dev/null &
  local pid=$! ticks=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$ticks" -ge $((tmo * 10)) ]; then
      kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      echo timeout > "$b.rc"
      printf '%s\t%s\n' "$id" "$label" >> "$out/index.tsv"
      return
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$pid"
  echo $? > "$b.rc"
  printf '%s\t%s\n' "$id" "$label" >> "$out/index.tsv"
}

skip() {  # skip <label> <reason>
  n=$((n + 1))
  local id; id=$(printf 'c%05d' "$n")
  printf 'label: %s\nskipped: %s\n' "$1" "$2" > "$out/cases/$id.cmd"
  echo skipped_size > "$out/cases/$id.rc"
  printf '%s\t%s\n' "$id" "$1" >> "$out/index.tsv"
}

{
  echo "platform: $plat"
  echo "start_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "timeout_s: $tmo"
  echo "max_bytes: $maxb"
  echo "mem_kib: $memkb"
  echo "archs: $archs"
  echo "otool: $OTOOL"
  echo "lipo: $LIPO"
  echo "file: $FILE"
  echo "limits_in_child: $( ( ulimit -t "$tmo" 2>/dev/null; ulimit -v "$memkb" 2>/dev/null; echo "cpu=$(ulimit -t) vmem=$(ulimit -v)" ) )"
} > "$out/run.txt"

# tool identity (bounded like every other case)
run "identity uname" uname -a
if [ "$plat" = macos-native ]; then
  run "identity sw_vers" sw_vers
  run "identity sysctl" sysctl -n hw.optional.arm64 machdep.cpu.brand_string
  run "identity xcode-select" xcode-select -p
  run "identity sdk" xcrun --show-sdk-version
  run "identity xcodebuild" xcodebuild -version
  run "identity clt" pkgutil --pkg-info=com.apple.pkg.CLTools_Executables
  run "identity otool --version" "$OTOOL" --version
  run "identity otool -version" "$OTOOL" -version
  run "identity lipo -version" "$LIPO" -version
  run "identity file --version" "$FILE" --version
  run "identity sha256" shasum -a 256 "$OTOOL" "$LIPO" "$FILE"
else
  run "identity otool --version" "$OTOOL" --version
  run "identity lipo --version" "$LIPO" --version
  run "identity file --version" "$FILE" --version
  run "identity sha256" sha256sum "$(command -v "$OTOOL")" "$(command -v "$LIPO")" "$(command -v "$FILE")"
fi

cd "$fx" || exit 2
if command -v sha256sum >/dev/null 2>&1; then sum="sha256sum"; else sum="shasum -a 256"; fi
find parse bundles -type f | LC_ALL=C sort > "$out/inputs.files"
find bundles -type l | LC_ALL=C sort > "$out/inputs.symlinks"
while read -r f; do $sum "$f"; done < "$out/inputs.files" > "$out/inputs.sha256"

while read -r l; do
  run "readlink $l" readlink "$l"
done < "$out/inputs.symlinks"

while read -r f; do
  size=$(wc -c < "$f" | tr -d ' ')
  if [ "$size" -gt "$maxb" ]; then
    skip "file $f" "size $size > $maxb"
    continue
  fi
  run "file $f" "$FILE" -b "$f"
  run "magic $f" od -An -tx1 -N4 "$f"
  run "lipo-info $f" "$LIPO" -info "$f"
  run "lipo-archs $f" "$LIPO" -archs "$f"
  run "otool-fatheaders $f" "$OTOOL" -f "$f"
  run "otool-loadcommands all $f" "$OTOOL" -arch all -l "$f"
  for a in $archs; do
    run "otool-loadcommands $a $f" "$OTOOL" -arch "$a" -l "$f"
    run "otool-dependencies $a $f" "$OTOOL" -arch "$a" -L "$f"
  done
done < "$out/inputs.files"

echo "end_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$out/run.txt"
echo "cases: $n" >> "$out/run.txt"
echo "replay_otool: $n cases in $out"
