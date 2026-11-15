"""Checks that every relative link in the tracked Markdown files points at a file that exists.

    python3 scripts/check-docs.py

Run by CI on every push and pull request. Web links are not fetched.
"""

import pathlib
import re
import subprocess
import sys

LINK = re.compile(r"\]\(([^)\s]+)\)")
SKIP = ("http://", "https://", "mailto:", "#")

root = pathlib.Path(__file__).resolve().parent.parent
tracked = subprocess.run(
    ["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True
).stdout.split()

broken = []
for name in tracked:
    path = root / name
    fenced = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for target in LINK.findall(line):
            if target.startswith(SKIP):
                continue
            file_part = target.split("#", 1)[0]
            if not (path.parent / file_part).exists():
                broken.append(f"{name}:{number}: {target}")

if broken:
    print("Broken relative links:")
    print("\n".join(broken))
    sys.exit(1)
print(f"{len(tracked)} Markdown files checked, every relative link resolves.")
