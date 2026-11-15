"""Build the two distribution ZIP archives for Phantom Worlds.

Run from the project root (or anywhere — paths are resolved from this file):

    .venv/Scripts/python.exe build_zips.py

Produces, in the workspace root:
  1. phantom-worlds-sample-packs.zip
       sample_packs/  +  BENCHMARK_REPORT_CARD.md  +  DATA_INSPECTION_SUMMARY.md
  2. phantom-worlds-backend-full.zip
       the whole project minus .venv/, .git/, __pycache__/, .pytest_cache/,
       and *_tmp.py scratch scripts.
"""

from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent

# Paths that must never enter an archive (relative to ROOT, case-insensitive).
EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# Never archive the archives themselves (they live in ROOT).
EXCLUDE_FILES = {
    "phantom-worlds-sample-packs.zip",
    "phantom-worlds-backend-full.zip",
}
# Extra directories to skip in the "full" archive only.
FULL_ONLY_EXCLUDE = {".claude", ".codex", ".devcontainer", ".github", "prompts"}


def _iter_files(extra_skip: set[str] = frozenset()):
    """Yield (relative_path, absolute_path) for every file worth archiving."""
    skip = EXCLUDE_DIRS | set(extra_skip)
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Prune excluded directories in place so os.walk never descends into them.
        dirnames[:] = [
            d for d in dirnames
            if d not in skip and not d.endswith(("_tmp", "_scratch"))
        ]
        for name in filenames:
            if name in EXCLUDE_FILES:
                continue
            if name.endswith(("_tmp.py", "_scratch.py")):
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(ROOT)
            yield rel.as_posix(), full


def _write_zip(out_name: str, members: list[tuple[str, Path]]) -> Path:
    out = ROOT / out_name
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        for arcname, path in sorted(members):
            zf.write(path, arcname=arcname)
    return out


def main() -> None:
    # Remove stale archives first so they are never picked up as members.
    for stale in ("phantom-worlds-sample-packs.zip", "phantom-worlds-backend-full.zip"):
        p = ROOT / stale
        if p.exists():
            p.unlink()

    # 1. Sample packs (Frontend + Pitch): tiny, self-contained.
    pack_members: list[tuple[str, Path]] = []
    for rel, full in _iter_files():
        if rel.startswith("sample_packs/"):
            pack_members.append((rel, full))
    for name in ("BENCHMARK_REPORT_CARD.md", "DATA_INSPECTION_SUMMARY.md"):
        p = ROOT / name
        if p.exists():
            pack_members.append((name, p))
    pack_zip = _write_zip("phantom-worlds-sample-packs.zip", pack_members)

    # 2. Full backend: everything except venv/git/caches/scratch.
    full_members = list(_iter_files())
    full_zip = _write_zip("phantom-worlds-backend-full.zip", full_members)

    print(f"Wrote {pack_zip}  ({len(pack_members)} files)")
    print(f"Wrote {full_zip}  ({len(full_members)} files)")


if __name__ == "__main__":
    main()
