"""Validate sample_packs JSON round-trips through app.schemas (Pydantic v2)."""
import json
from pathlib import Path

from app.schemas import CaseRecord, Manifest, SourceRecord

BASE = Path(__file__).parent
OUT = BASE / "sample_packs"


def main() -> None:
    sources = json.loads((OUT / "sources.json").read_text(encoding="utf-8"))
    cases = json.loads((OUT / "cases.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))

    parsed_sources = [SourceRecord.model_validate(s) for s in sources]
    parsed_cases = [CaseRecord.model_validate(c) for c in cases]
    parsed_manifest = Manifest.model_validate(manifest)

    print(f"OK  sources : {len(parsed_sources)} records validated")
    print(f"OK  cases   : {len(parsed_cases)} records validated")
    print(f"OK  manifest: {parsed_manifest.schema_version}, {parsed_manifest.source_count} sources, {parsed_manifest.case_count} cases")

    for s in parsed_sources:
        nb = len(s.readings.spectral_bands)
        mask = s.readings.coverage_mask
        nm = len(s.readings.molecules)
        covered = sum(mask)
        gaia = "yes" if (s.readings.gaia and s.readings.gaia.parallax_mas) else "no"
        print(f"  {s.target_name:<16} bands={nb} covered={covered}/{nb} molecules={nm} gaia_parallax={gaia} all_data_conf={s.identity.all_data.display_confidence:.2f} disc={s.identity.all_data.discovery_class}")

    assert all(len(s.readings.spectral_bands) == 102 for s in parsed_sources), "band count != 102"
    assert all(len(s.readings.coverage_mask) == 102 for s in parsed_sources), "mask len != 102"
    assert all(len(s.readings.molecules) == 4 for s in parsed_sources), "molecule count != 4"
    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()