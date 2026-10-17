#!/usr/bin/env python3
"""Consumer example: static pre-check on classify_replay.py output for one bundle.

usage: python -I consume_outcomes.py OUTCOMES_JSON ARCH PATH_PREFIX [FORBIDDEN_ROOT ...]
Exit 0 means "no static defect found" for ARCH under PATH_PREFIX. It does not mean
the dependencies resolve: @rpath, @loader_path and @executable_path names are not
resolved here (only @loader_path/.. escapes are checked lexically). The relocated
runtime test on macOS decides resolution.
"""

import base64
import json
import os
import sys

SYSTEM = (b"/usr/lib/", b"/System/Library/")
TOKENS = (b"@rpath/", b"@loader_path/", b"@executable_path/")


def under(v, roots):
    return any(v == r.rstrip(b"/") or v.startswith(r.rstrip(b"/") + b"/") for r in roots)


def main():
    path, arch, prefix, forbid = sys.argv[1], sys.argv[2], sys.argv[3], [r.encode() for r in sys.argv[4:]]
    d = json.load(open(path))
    bad, unsupported, unresolved = [], [], 0
    files = [f for f in d["files"] if f["file"].startswith(prefix)]
    if not files:
        bad.append("no files under %s" % prefix)
    for f in files:
        e = f["per_arch"][arch]
        if e["loadcommands"] == "not_object" and e["dependencies"] == "not_object" and not f["file"].endswith((".dylib", ".so")):
            continue  # classify_replay.py keeps not_object only when the magic is not Mach-O
        if not e.get("passing_parse"):
            bad.append("%s: %s / %s" % (f["file"], e["loadcommands"], e["dependencies"]))
            continue
        rpaths = []
        for s in e.get("strings", []):
            v, cmd, where = base64.b64decode(s["value"]["b64"]), s["cmd"], "%s: %s %s" % (f["file"], s["cmd"], s["value"]["text"])
            if forbid and under(v, forbid):
                bad.append(where + " (forbidden root)")
            elif cmd == "LC_DYLD_ENVIRONMENT":
                unsupported.append(where)
            elif cmd == "LC_RPATH":
                if v in rpaths:
                    unsupported.append(where + " (duplicate LC_RPATH)")
                rpaths.append(v)
                if v.startswith(b"/") and not under(v, SYSTEM):
                    bad.append(where + " (absolute external)")
                elif not (v.startswith(b"/") or v in (b"@loader_path", b"@executable_path") or v.startswith(TOKENS[1:])):
                    unsupported.append(where)
            elif cmd != "LC_ID_DYLIB":
                if cmd == "LC_LAZY_LOAD_DYLIB":
                    unsupported.append(where)
                if v.startswith(b"/"):
                    if not under(v, SYSTEM):
                        bad.append(where + " (absolute external)")
                elif v.startswith(TOKENS):
                    unresolved += 1
                    if v.startswith(TOKENS[1]):
                        j = os.path.normpath(os.path.join(os.path.dirname(f["file"]), v[len(TOKENS[1]):].decode("utf-8", "surrogateescape")))
                        if not (j + "/").startswith(prefix):
                            bad.append(where + " (leaves the bundle lexically)")
                else:
                    unsupported.append(where + " (cwd-relative or unknown token)")
    names = {x["link"]["text"] for x in d.get("symlinks", [])}
    regular = {f["file"] for f in d["files"]}
    for x in d.get("symlinks", []):
        link = x["link"]["text"]
        if not link.startswith(prefix):
            continue
        if x["target"] is None:
            bad.append("%s: readlink failed" % link)
            continue
        t = x["target"]["text"]
        joined = os.path.normpath(os.path.join(os.path.dirname(link), t))
        if t.startswith("/") or not (joined + "/").startswith(prefix):
            bad.append("%s -> %s: symlink leaves the bundle" % (link, t))
        elif joined in names:
            unsupported.append("%s -> %s: chained symlink not modelled" % (link, t))
        elif joined not in regular:
            unsupported.append("%s -> %s: broken or directory symlink not modelled" % (link, t))
    status = "fail" if bad else ("unsupported" if unsupported else "no static defect found")
    print("platform %s, arch %s, %s: %s; %d relative dependency names not resolved here" % (d["platform"], arch, prefix, status, unresolved))
    for b in bad:
        print("  fail: " + b)
    for u in unsupported:
        print("  unsupported: " + u)
    return 1 if bad else (3 if unsupported else 0)


if __name__ == "__main__":
    sys.exit(main())
