"""Produce proof/report.json and proof/report.md from real SPHEREx data and pipeline code."""

import argparse
import json
import os
import sys

PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)

from phantom_worlds.tier_b_proof import DEFAULT_PROOF_DIR, generate_proof_report, render_proof_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate Phantom Worlds Proof v2 report.json & report.md.")
    parser.add_argument("--out-dir", default=DEFAULT_PROOF_DIR, help="Directory where report.json and report.md are written.")
    parser.add_argument("--include-skybot", action="store_true", help="Query live IMCCE SkyBoT for B3 asteroid check.")
    args = parser.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)
    report = generate_proof_report(include_skybot=args.include_skybot, write_searched=True)
    json_path = os.path.join(args.out_dir, "report.json")
    md_path = os.path.join(args.out_dir, "report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_proof_markdown(report))
    print(
        f"Wrote {json_path} and {md_path}: "
        f"{report['counts']['pass']} PASS, {report['counts']['fail']} FAIL, {report['counts']['not_measured']} NOT_MEASURED."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
