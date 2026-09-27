#!/usr/bin/env python3
"""List commits that have no entry in frontend/public/updates.json (the in-app Update page).

Run after committing, then add an entry per commit listed (newest first):
  {"commit", "date", "type": feature|improvement|fix|security|maintenance,
   "title", "what", "benefit", "where"}  — written in Thai for end users.
Commits that only change updates.json itself are skipped.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATES = ROOT / "frontend" / "public" / "updates.json"


def main() -> None:
    known = {entry["commit"] for entry in json.loads(UPDATES.read_text(encoding="utf-8"))}
    # Full hashes, matched by prefix: git lengthens abbreviated hashes as the repo grows,
    # so the short ids stored in updates.json would otherwise stop matching.
    log = subprocess.run(["git", "log", "--no-merges", "--format=%H%x09%ad%x09%s", "--date=short"],
                         cwd=ROOT, check=True, capture_output=True, text=True).stdout.splitlines()
    missing = []
    for line in log:
        commit, date, subject = line.split("\t", 2)
        if any(commit.startswith(short) for short in known):
            continue
        files = subprocess.run(["git", "show", "--name-only", "--format=", commit],
                               cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
        if files == ["frontend/public/updates.json"]:
            continue
        missing.append(f"{commit[:7]}  {date}  {subject}")
    print("\n".join(missing) if missing else "All commits have an entry.")


if __name__ == "__main__":
    main()
