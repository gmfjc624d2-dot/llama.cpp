#!/usr/bin/env python3
"""Side-by-side table of classified replays; platforms stay in separate columns.

usage: python -I compare_replays.py LINUX_OUTCOMES_JSON [MACOS_OUTCOMES_JSON]
A missing macOS file is shown as NOT RUN. No outcome is copied between columns.
"""

import json
import sys


def cells(path):
    if not path:
        return None, {}
    d = json.load(open(path))
    out = {}
    for f in d["files"]:
        for a, e in f["per_arch"].items():
            out[(f["file"], a)] = "%s / %s" % (e["loadcommands"], e.get("dependencies", "-"))
    return d["platform"], out


def main():
    lp, lin = cells(sys.argv[1])
    mp, mac = cells(sys.argv[2] if len(sys.argv) > 2 else None)
    print("| file | arch | %s (-l / -L) | %s (-l / -L) | same |" % (lp, mp or "macos-native"))
    print("|---|---|---|---|---|")
    for k in sorted(set(lin) | set(mac)):
        a, b = lin.get(k, "absent"), mac.get(k, "NOT RUN" if not mp else "absent")
        print("| %s | %s | %s | %s | %s |" % (k[0], k[1], a, b, "-" if not mp else ("yes" if a == b else "no")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
