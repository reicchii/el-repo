"""Extract deeper metadata from the 10 CSVs for building realistic sample packs."""
import csv
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent
TARGETS = ["Barnards_Star", "Epsilon_Indi_B", "R_Draconis", "RW_Aurigae", "WISE_0855"]

# Gaia columns: 0 source_id,1 ra,2 dec,3 pmra,4 pmdec,5 parallax,6 G,7 BP,8 RP,9 ruwe
# SPHEREx columns: 4 energy_bandpassname,5 em_min,6 em_max,7 em_res_power,8 t_min,9 t_max,10 t_exptime


def fnum(s):
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def g_meta():
    for t in TARGETS:
        p = BASE / f"{t}_gaia_dr3.csv"
        rows = list(csv.reader(p.open(newline="", encoding="utf-8")))
        data = rows[1:]
        print(f"\n=== {t}_gaia_dr3.csv  ({len(data)} rows) ===")
        pars = [fnum(r[5]) for r in data]
        pars = [x for x in pars if x is not None]
        if pars:
            print(f"  parallax(mas): min={min(pars):.4f} max={max(pars):.4f} n={len(pars)}")
            big = [(r, fnum(r[5])) for r in data if (fnum(r[5]) or 0) > 20]
            print(f"  high-parallax (>20 mas) rows: {len(big)}")
            for r, plx in sorted(big, key=lambda x: -x[1])[:6]:
                print(f"    id={r[0]} ra={fnum(r[1]):.4f} dec={fnum(r[2]):.4f} plx={plx:.4f} "
                      f"pmra={fnum(r[3]):.2f} pmdec={fnum(r[4]):.2f} G={fnum(r[6]):.2f} RUWE={fnum(r[9]):.2f}")
        gmag = [fnum(r[6]) for r in data]
        gmag = [x for x in gmag if x is not None]
        if gmag:
            print(f"  G mag: min={min(gmag):.2f} max={max(gmag):.2f} (n={len(gmag)})")


def s_meta():
    for t in TARGETS:
        p = BASE / f"{t}_spherex_frames.csv"
        rows = list(csv.reader(p.open(newline="", encoding="utf-8")))
        data = rows[1:]
        print(f"\n=== {t}_spherex_frames.csv  ({len(data)} rows) ===")
        bp = defaultdict(list)
        for r in data:
            bp[r[4]].append(r)
        print(f"  distinct bandpasses ({len(bp)}):")
        for name, rs in sorted(bp.items()):
            emins = [fnum(x[5]) for x in rs]
            emins = [x for x in emins if x is not None]
            emaxs = [fnum(x[6]) for x in rs]
            emaxs = [x for x in emaxs if x is not None]
            rps = [fnum(x[7]) for x in rs]
            rps = [x for x in rps if x is not None]
            tmins = [fnum(x[8]) for x in rs]
            tmins = [x for x in tmins if x is not None]
            tmaxs = [fnum(x[9]) for x in rs]
            tmaxs = [x for x in tmaxs if x is not None]
            print(f"    {name}: n={len(rs)} wl={min(emins):.4e}-{max(emaxs):.4e} m R={rps[0] if rps else '?'} "
                  f"t={min(tmins):.2f}-{max(tmaxs):.2f} MJD")
        ts = [fnum(r[8]) for r in data]
        ts = [x for x in ts if x is not None]
        te = [fnum(r[9]) for r in data]
        te = [x for x in te if x is not None]
        print(f"  overall t_min={min(ts):.2f} t_max={max(te):.2f} MJD  span={max(te)-min(ts):.2f} days")


if __name__ == "__main__":
    g_meta()
    s_meta()