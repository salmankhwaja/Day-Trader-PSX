#!/usr/bin/env python3
"""Copy the shared code into each psx-* skill folder, so every skill works on its own.

The code lives once, in psx-mufap/scripts/. Each desk skill (psx-scanner, psx-news, ...) needs its
own copy of the modules its tools import, because the Claude app installs every skill as a separate
folder. This script works out those modules (following every import, including ones inside
functions) and copies them into <skill>/scripts/, plus brokers.json when the broker charges are
needed. Run it after changing any code, before committing:

  python3 tools/sync_skills.py          copy
  python3 tools/sync_skills.py --check  only report skills whose copies are out of date (tests use this)
"""
import argparse
import filecmp
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "psx-mufap", "scripts")

# skill folder -> the tools it runs (pkdata and watchlist come with every skill: data in, list managed)
SKILLS = {
    "psx-scanner": ["scanner.py", "intraday.py"],
    "psx-news": ["news.py"],
    "psx-entry": ["entry.py", "intraday.py"],
    "psx-exit": ["exitplan.py"],
    "psx-timemachine": ["timemachine.py", "intraday.py"],
    "psx-risk": ["risk.py"],
    "psx-budget": ["budget.py"],
    "psx-broker": ["broker.py", "portfolio.py"],
    "psx-alerts": ["alerts.py"],
    "psx-analyst": ["analyst.py"],
    "psx-insiders": ["insiders.py"],
}
COMMON = ["pkdata.py", "watchlist.py"]
IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w, ]+?)(?:\s+as\s+\w+)?\s*(?:#.*)?$|from\s+(\w+)\s+import\b)", re.M)


def modules():
    return {f[:-3] for f in os.listdir(SRC) if f.endswith(".py")}


def deps(start):
    have, todo, mods = set(), list(start), modules()
    while todo:
        f = todo.pop()
        if f in have:
            continue
        have.add(f)
        with open(os.path.join(SRC, f), encoding="utf-8") as fh:
            text = fh.read()
        for m in IMPORT_RE.finditer(text):
            names = [x.strip().split(" as ")[0] for x in (m.group(1) or m.group(2)).split(",")]
            for n in names:
                if n in mods and n + ".py" not in have:
                    todo.append(n + ".py")
    return sorted(have)


def plan():
    out = {}
    for skill, tools in SKILLS.items():
        files = deps(tools + COMMON)
        out[skill] = files
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    stale = []
    for skill, files in plan().items():
        dst = os.path.join(ROOT, skill, "scripts")
        want = set(files)
        extra = ["brokers.json"] if "portfolio.py" in want else []
        if a.check:
            for f in files:
                p = os.path.join(dst, f)
                if not os.path.exists(p) or not filecmp.cmp(p, os.path.join(SRC, f), shallow=False):
                    stale.append("%s/scripts/%s" % (skill, f))
            if os.path.isdir(dst):
                for f in os.listdir(dst):
                    if f.endswith(".py") and f not in want:
                        stale.append("%s/scripts/%s (no longer needed)" % (skill, f))
            for f in extra:
                p = os.path.join(ROOT, skill, f)
                if not os.path.exists(p) or not filecmp.cmp(p, os.path.join(ROOT, "psx-mufap", f), shallow=False):
                    stale.append("%s/%s" % (skill, f))
            continue
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(dst):
            if f.endswith(".py") and f not in want:
                os.remove(os.path.join(dst, f))
        for f in files:
            shutil.copy2(os.path.join(SRC, f), os.path.join(dst, f))
        for f in extra:
            shutil.copy2(os.path.join(ROOT, "psx-mufap", f), os.path.join(ROOT, skill, f))
        print("%-16s %2d modules%s" % (skill, len(files), " + brokers.json" if extra else ""))
    if a.check:
        if stale:
            print("out of date (run python3 tools/sync_skills.py):\n  " + "\n  ".join(stale))
            return 1
        print("all skill copies are in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
