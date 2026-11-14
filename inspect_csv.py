"""Step 1: Inspect column names, data types, and row counts of the 10 benchmark CSVs."""
import csv
import json
from pathlib import Path

BASE = Path(__file__).parent

TARGETS = ["Barnards_Star", "Epsilon_Indi_B", "R_Draconis", "RW_Aurigae", "WISE_0855"]
KINDS = ["gaia_dr3", "spherex_frames"]


def inspect(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return {"file": path.name, "rows": 0, "columns": [], "types": {}}
    header = rows[0]
    n_data = len(rows) - 1
    # infer types from first data row
    types = {}
    if n_data > 0:
        sample = rows[1]
        for col, val in zip(header, sample):
            types[col] = _infer(val)
    return {"file": path.name, "rows": n_data, "columns": header, "types": types}


def _infer(val: str) -> str:
    try:
        int(val)
        return "int"
    except ValueError:
        pass
    try:
        float(val)
        return "float"
    except ValueError:
        pass
    if val == "":
        return "empty"
    return "str"


def main() -> None:
    results = []
    for t in TARGETS:
        for k in KINDS:
            p = BASE / f"{t}_{k}.csv"
            if p.exists():
                results.append(inspect(p))
            else:
                results.append({"file": f"{t}_{k}.csv", "rows": None, "columns": None,
                                "types": None, "missing": True})

    for r in results:
        print("=" * 70)
        print(r["file"])
        if r.get("missing"):
            print("  FILE MISSING")
            continue
        if r["rows"] == 0:
            print("  (empty / header only)")
            print(f"  columns: {r['columns']}")
            continue
        print(f"  rows (data): {r['rows']}")
        print(f"  columns ({len(r['columns'])}): {r['columns']}")
        print(f"  inferred types: {json.dumps(r['types'], indent=2)}")

    # save machine-readable summary
    out = BASE / "csv_inspection_report.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("\nSaved report to", out)


if __name__ == "__main__":
    main()