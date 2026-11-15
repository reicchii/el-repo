# Phantom Worlds: data and resource links

Every link the project uses, with exact file names, table names and the queries that fetch them. Checked on 13 and 14 Nov 2026 unless marked `[check]`. Reasons and facts behind each item are in `PROJECT-CONTEXT.md`. Setup is in `SETUP.md`.

Some IRSA and DESI folders block automated web readers (robots). They open normally in a browser and download normally with `curl`, `wget` or Python. Use code, not a web-page reader, for every download.

## Contents

1. Challenge
2. SPHEREx documentation
3. SPHEREx services and endpoints
4. SPHEREx tutorials
5. SPHEREx calibration files
6. SPHEREx all-sky cube tiles
7. Machine learning data
8. Other surveys and services
9. Papers
10. Library documentation
11. Queries
12. Download order and sizes
13. DOIs, licences and credits

---

## 1. Challenge

| What | Link |
|---|---|
| Challenge page | https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/ |
| Resources tab | https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=resources |

Links listed on the Resources tab:

| Resource | Link |
|---|---|
| IRSA SPHEREx pages | https://irsa.ipac.caltech.edu/Missions/spherex.html |
| IRSA tutorials, full index (SPHEREx, Euclid, WISE, simulated data, techniques) | https://caltech-ipac.github.io/irsa-tutorials/ |
| SPHEREx tutorial notebooks | https://caltech-ipac.github.io/irsa-tutorials/spherex/ |
| WiseView (the model the challenge names) | http://byw.tools/wiseview |
| Gaia mission data (MAST, general page, no DR3 endpoint) | https://archive.stsci.edu/missions-and-data/gaia |
| Gaia DR3 release page (ESA), as listed | https://esdcdoi.esac.esa.int/esdc-dois/doi/html/data/astronomy/gaia/DR3.html |
| Gaia DR3 release page (ESA), the address that loads | https://esdcdoi.esac.esa.int/doi/html/data/astronomy/gaia/DR3.html |
| CSA NEOSSat overview | https://www.asc-csa.gc.ca/eng/satellites/neossat/ |
| Canadian Astronomy Data Centre | https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/ |
| NEOSSat data tutorial | https://github.com/asc-csa/NEOSSAT_Tutorial |
| NEOSSat dataset | https://data.asc-csa.gc.ca/dataset/neossat |

---

## 2. SPHEREx documentation

| Page | Link |
|---|---|
| Archive documentation, overview | https://caltech-ipac.github.io/spherex-archive-documentation/ |
| Data products | https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products |
| Data access (paths for images, calibration files, cube) | https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access |
| Explanatory Supplement v2.1, 10 Nov 2026 (the current one) | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf |
| Explanatory Supplement v2.0, Quick Release | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp_QR.pdf |
| Quick Release overview (acknowledgement text, release notes) | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html |
| Cutout notes | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html |
| Spectral calibration files | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/spherex_spectral_calibrations.html |
| Spectral files archive (per-band central wavelengths, transmission curves) | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/spectral_files_20260812/SPHERExSpectralFiles_202607.tar |
| Spectrophotometry Tool help | https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html |
| Program interfaces index | https://irsa.ipac.caltech.edu/voapi.html |
| TAP documentation | https://irsa.ipac.caltech.edu/docs/program_interface/TAP.html |
| SIA documentation | https://irsa.ipac.caltech.edu/ibe/sia.html |
| Cloud access (S3) | https://irsa.ipac.caltech.edu/cloud_access/#spherex |
| SPHEREx mission data products page | https://spherex.caltech.edu/page/data-products |
| SPHEREx mission data tools page | https://spherex.caltech.edu/page/data-tools |

---

## 3. SPHEREx services and endpoints

| Service | Link or pattern |
|---|---|
| TAP, synchronous (5 minute limit) | https://irsa.ipac.caltech.edu/TAP/sync |
| TAP, asynchronous (large queries) | https://irsa.ipac.caltech.edu/TAP/async |
| SIA | https://irsa.ipac.caltech.edu/SIA (collections `spherex_dr1`, `spherex_dr1_deep`, `spherex_dr1_cube`, `spherex_qr3`, `spherex_qr3_deep`, add `RESPONSEFORMAT=JSON`) |
| File root | https://irsa.ipac.caltech.edu/ibe/data/spherex/ (subfolders `dr1`, `qr3`, `qr2`) |
| Level 2 images, DR1 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/[Planning Period]/l2b-v[Version]-[Processing Date]/[Detector]/ |
| Level 2 images, QR3 | https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/[Planning Period]/l2b-v[Version]-[Processing Date]/[Detector]/ |
| Example file | https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_2026W21_2A_0001_2D1_spx_l2b-v27-2026-268.fits |
| S3 bucket | `nasa-irsa-spherex`, region `us-east-1`, anonymous, prefixes `dr1`, `qr3`, `qr2`. Key layout `[check by listing]` |
| Cutout (last resort) | file URL + `?center=<ra>,<dec>d&size=<deg>` |
| Spectrophotometry Tool (browser, login, no API) | https://irsa.ipac.caltech.edu/applications/spherex/tool-spectrophotometry |
| SPHEREx Data Explorer | https://irsa.ipac.caltech.edu/applications/spherex |
| Mosaic Tool | https://irsa.ipac.caltech.edu/applications/spherex/tool-mosaic |
| HiPS all-sky cube root (for Aladin) | https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube |
| Moving Object Search Tool | https://irsa.ipac.caltech.edu/applications/MOST |
| Moving Object Search Tool API docs | https://irsa.ipac.caltech.edu/applications/MOST/MOSTProgramInterface.html |
| Moving Object Search Tool API endpoint | https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most |
| Comet 3I/ATLAS images and per-frame positions | https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html (table `obscore_3I_Atlas.vot`) |
| SPLICES ice source list | https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/ |

---

## 4. SPHEREx tutorials

| Notebook | Link | What it gives |
|---|---|---|
| Introduction to Spectral Images | https://caltech-ipac.github.io/irsa-tutorials/spherex-intro | SIA search, file layout, units, FLAGS bits, spectral WCS key `W` |
| Spectral Image cutouts | https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts | TAP frame query, the cutout call, parallel download |
| The ePSF extension | https://caltech-ipac.github.io/irsa-tutorials/spherex-psf | PSF by file version, zone lookup, rendering to image pixels |
| Source Discovery Tool demo | https://caltech-ipac.github.io/irsa-tutorials/spherex-source-discovery-tool-demo | Detector minus detector, detection, aperture spectra |
| Mosaic cubes | https://caltech-ipac.github.io/irsa-tutorials/spherex-mosaic | Cube layout, feature map from one plane minus its neighbours |
| HiPS all-sky cubes | https://caltech-ipac.github.io/irsa-tutorials/spherex-hipscube | Tile URL pattern, 102 planes, quick spectrum by aperture |

---

## 5. SPHEREx calibration files

All under the DR1 root https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/ (the same folders exist under `qr3/`). Version and date parts change by release, so list the folder first.

| Folder pattern | What it is |
|---|---|
| `epsf/cal-epsf-v[Version]-[Processing Date]/[Detector]/` | Effective PSF per zone, for files below version 7.0 and for injections |
| `spectral_wcs/cal-wcs-v[Version]-[Processing Date]/[Detector]/` | `CWAVE`, `CBAND`: science wavelength and bandwidth per pixel |
| `solid_angle_pixel_map/cal-sapm-v[Version]-[Processing Date]/[Detector]/` | Pixel solid angle, converts MJy/sr to µJy |
| `l3_flux_corrections/cal-flxc-v[Version]-[Processing Date]/[Detector]/` | Lines up QR2-era fluxes (the SPIFF library) with DR1 |
| `shuttle_glow_template/base-[Processing Date]/[Detector]/` | Spacecraft glow |
| `he_template/base-[Processing Date]/[Detector]/` | Helium emission |
| `aurora_template/base-[Processing Date]/[Detector]/` | Aurora emission |
| `xtalk_class[Crosstalk Type]/base-[Processing Date]/[Detector]/` | Crosstalk ghosts and streaks. Exact type names `[check]` |
| `nonfunc_v2`, `dichroic`, `spectral_channels`, `sip`, `dark`, `abs_gain_matrix`, `nonlinear_pars`, `readnoise_pars` | Other calibration products |

---

## 6. SPHEREx all-sky cube tiles

Root: https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026

Pattern: `{root}/Norder5/Dir{(ipix // 10000) * 10000}/Npix{ipix}_cube.fits`. HEALPix order 5, nside 32, nested. Each tile covers 3.36 deg² and is about 300 MB.

```python
import healpy as hp
ipix = hp.ang2pix(32, ra_deg, dec_deg, nest=True, lonlat=True)
url = f"https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir{(ipix // 10000) * 10000}/Npix{ipix}_cube.fits"
```

Tiles for our fields, computed with healpy on 14 Nov. Positions for the test targets are approximate J2000 values used only to pick tiles. Resolve each name properly in the code.

| Field | Position used (RA, Dec) | Tile | Link |
|---|---|---|---|
| North Ecliptic Pole (SPHEREx deep field) | 270.0000, +66.5607 | 4010 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix4010_cube.fits |
| Euclid Deep Field North centre | 269.7329, +66.0177 | 2559 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix2559_cube.fits |
| Taurus, L1495 area (first guess, confirm by SPLICES counts) | 64.0, +28.0 | 292 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix292_cube.fits |
| Barnard's Star | 269.452, +4.693 | 7945 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix7945_cube.fits |
| Epsilon Indi B | 331.044, -56.783 | 11391 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir10000/Npix11391_cube.fits |
| WISE 0855 (challenge coordinates) | 133.79513, -7.24515 | 10226 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir10000/Npix10226_cube.fits |
| RW Aurigae | 76.9564, +30.4014 | 277 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix277_cube.fits |
| R Draconis | 248.1674, +66.7550 | 2928 | https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/hips5_cube/hips_20261026/Norder5/Dir0/Npix2928_cube.fits |

Neighbouring tiles, same pattern, for wider fields:

| Field | Neighbours |
|---|---|
| North Ecliptic Pole (4010) | 2559, 2901, 2903, 3837, 3839, 4008, 4009, 4011 (all in `Dir0`) |
| Euclid Deep Field North (2559) | 2556, 2557, 2558, 2900, 2901, 3838, 3839, 4010 (all in `Dir0`) |
| Taurus (292) | 267, 270, 271, 289, 291, 293, 294, 295 (all in `Dir0`) |
| Barnard's Star (7945) | 7938, 7939, 7942, 7944, 7946, 7947, 7948, 7950 (all in `Dir0`) |
| Epsilon Indi B (11391) | 11388, 11389, 11390, 11476, 11477, 11560, 11562, 11648 (all in `Dir10000`) |
| WISE 0855 (10226) | 10213, 10215, 10221, 10224, 10225, 10227, 10232, 10233 (all in `Dir10000`) |
| RW Aurigae (277) | 276, 278, 279, 320, 322, 6078, 6079, 6122 (all in `Dir0`) |
| R Draconis (2928) | 2895, 2906, 2907, 2917, 2919, 2929, 2930, 2931 (all in `Dir0`) |

Plane index inside a tile: plane = 17 × (detector - 1) + (band - 1). Planes 50 and 51 are blank.

---

## 7. Machine learning data

### 7.1 SPHEREx spectra: the SPIFF library

Record: https://zenodo.org/records/19051216 (DOI `10.5281/zenodo.19051216`). Version QR2-2026-04-24. CC BY 4.0. 6.7 GB in total.

Download these (about 57 MB):

| File | Size | Link |
|---|---|---|
| `00_README.txt` | 2.3 kB | https://zenodo.org/records/19051216/files/00_README.txt?download=1 |
| `spiff_known_bds_binned_csv.zip` (known ultracool dwarfs, 2,050 sources) | 7.5 MB | https://zenodo.org/records/19051216/files/spiff_known_bds_binned_csv.zip?download=1 |
| `spiff_new_bds_binned_csv.zip` (newly identified, 947 sources) | 6.7 MB | https://zenodo.org/records/19051216/files/spiff_new_bds_binned_csv.zip?download=1 |
| `spiff_new_candidate_bds_binned_csv.zip` (peculiar, young, subdwarf candidates, 3,739 sources) | 14.5 MB | https://zenodo.org/records/19051216/files/spiff_new_candidate_bds_binned_csv.zip?download=1 |
| `spiff_photo_known_bds_binned_csv.zip` (photometric candidates, 3,008 sources) | 26.7 MB | https://zenodo.org/records/19051216/files/spiff_photo_known_bds_binned_csv.zip?download=1 |
| `spiff_tables.zip` | 784.9 kB | https://zenodo.org/records/19051216/files/spiff_tables.zip?download=1 |
| `spiff_templates_hybrid_csv.zip` (47 subtypes) | 81.3 kB | https://zenodo.org/records/19051216/files/spiff_templates_hybrid_csv.zip?download=1 |
| `spiff_templates_raw_csv.zip` (47 subtypes) | 75.9 kB | https://zenodo.org/records/19051216/files/spiff_templates_raw_csv.zip?download=1 |
| `spiff_zenodo_manifest.csv` | 4.2 kB | https://zenodo.org/records/19051216/files/spiff_zenodo_manifest.csv?download=1 |

Later, for models that work on raw wavelengths (about 2 GB):

| File | Size |
|---|---|
| `spiff_known_bds_unbinned_csv.zip` | 245.7 MB |
| `spiff_new_bds_unbinned_csv.zip` | 252.6 MB |
| `spiff_new_candidate_bds_unbinned_csv.zip` | 512.4 MB |
| `spiff_photo_known_bds_unbinned_csv.zip` | 1.0 GB |

Same URL pattern: `https://zenodo.org/records/19051216/files/<name>?download=1`. Skip the `_autotype_png.zip` files (4.6 GB of plots).

Sample names come from the file names and the counts on the record page. Read `00_README.txt` to confirm the mapping and the CSV columns.

Other SPIFF routes: code https://github.com/jgagneastro/SPIFF (licence `[check]`), database https://mocadb.ca.

### 7.2 Labels

**UltracoolSheet v2.1.0** (3 Jul 2025, CC BY 4.0). Record: https://zenodo.org/records/15802304 (cite the concept DOI `10.5281/zenodo.4169084`). Live sheet: http://bit.ly/UltracoolSheet

| File | Size | Link |
|---|---|---|
| Main table (3,890 objects) | 6.6 MB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20Main.csv?download=1 |
| Main, in progress (adds 67 Pleiades objects) | 6.7 MB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20Main%20-%20In%20Progress.csv?download=1 |
| Fundamental properties | 830.8 kB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20FundamentalProperties.csv?download=1 |
| Binaries | 101.7 kB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20Binaries.csv?download=1 |
| Age values | 24.9 kB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20AgeValues.csv?download=1 |
| References | 206.4 kB | https://zenodo.org/records/15802304/files/UltracoolSheet%20-%20References.csv?download=1 |

Subdwarfs: the `literature_flag` column holds `subd`, or negative values in `sptnum_formula`.

**SPLICES**

| What | Link |
|---|---|
| Catalogue (3.1 GB FITS) | https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/20241107_SPLICESv8.6.fits.gz |
| Release notes | https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/SPLICES_Release_Notes.pdf |
| Column descriptions | https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/gator_docs/splices_colDescriptions.html |

Class columns: `CLASS_1`, `YSO_PUB`, `STYPE_ML`, `STYPE_ML_PROB1`, `STYPE_ML_PROB2`, `VarClassGaia`. Extinction: `Av`.

**DESI DR1** (CC BY 4.0)

| What | Link |
|---|---|
| TAP, anonymous, schema `desi_dr1` (recommended) | https://datalab.noirlab.edu/tap |
| Tables | `desi_dr1.zpix` (types and redshifts), `desi_dr1.mws` (stellar parameters), `desi_dr1.agngal` (AGN and galaxy classes) |
| Data Lab DESI page | https://datalab.noirlab.edu/desi/ |
| Data Lab DESI access page | https://datalab.noirlab.edu/desi/access.php |
| Full redshift catalogue file (large, size `[check]`) | https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/zcatalog/v1/zall-pix-iron.fits |
| Milky Way Survey catalogue file | https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0/mwsall-pix-iron.fits |
| AGN and galaxy catalogue folder (holds `agngal_desi.fits`) | https://data.desi.lbl.gov/public/dr1/vac/dr1/agngal/ |
| Same catalogue on VizieR | https://vizier.cds.unistra.fr/viz-bin/VizieR-2?-source=V/161 |
| DR1 documentation | https://data.desi.lbl.gov/doc/releases/dr1/ |
| MWS documentation | https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/ |
| AGN and galaxy documentation | https://data.desi.lbl.gov/doc/releases/dr1/vac/agngal/ |
| Data access documentation | https://data.desi.lbl.gov/doc/access |
| Acknowledgement text | https://data.desi.lbl.gov/doc/acknowledgments |

Quality cut: `ZWARN = 0`. Broad-line AGN: bit 12 (`BROAD_LINE`) of `AGN_MASKBITS`.

**Gaia DR3, ESA archive** (tables not on IRSA)

| What | Link |
|---|---|
| Archive web interface | https://gea.esac.esa.int/archive/ |
| TAP | https://gea.esac.esa.int/tap-server/tap |
| Data model documentation | https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/ |
| Table metadata mirror (AIP) | https://gaia.aip.de/metadata/gaiadr3/ |
| XP spectra package (GaiaXPy) `[check]` | https://pypi.org/project/GaiaXPy/ |

Tables: `gaiadr3.vari_classifier_result` (variability class, about 10 million rows), `gaiadr3.vari_long_period_variable` (evolved giants), `gaiadr3.qso_candidates` (6,649,162 rows), `gaiadr3.galaxy_candidates`.

**SIMBAD**

| What | Link |
|---|---|
| TAP (table `basic`: `main_id`, `ra`, `dec`, `otype`, `sp_type`) | https://simbad.cds.unistra.fr/simbad/sim-tap |

**Euclid** (on IRSA TAP, deep fields)

| What | Link or table |
|---|---|
| Euclid DR1 page | https://euclid.caltech.edu/page/euclid-dr1 |
| IRSA Euclid user guide | https://irsa.ipac.caltech.edu/data/Euclid/docs/euclid_archive_at_irsa_user_guide.pdf |
| Classification, photometric | `euclid_dr1_phz_classification_deep_survey`, `euclid_q1_phz_classification` |
| Classification, spectroscopic | `euclid_dr1_spectro_z_spe_classification_deep`, `euclid_q1_spectro_zcatalog_spe_classification` |
| Candidates by type (Q1) | `euclid_q1_spectro_zcatalog_spe_star_candidates`, `_galaxy_candidates`, `_qso_candidates` |
| Main catalogue | `euclid_dr1_mer_catalogue_deep_survey`, `euclid_q1_mer_catalogue` |
| Cutouts (Q1) | `euclid_q1_mer_cutouts` |

### 7.3 Survey features on IRSA TAP

All on https://irsa.ipac.caltech.edu/TAP/sync (table names `[VERIFIED 14 Nov]`).

| Survey | Tables |
|---|---|
| SPHEREx frames | `spherex.artifact`, `spherex.plane`, `spherex.observation`, `spherex.obscore`, `spherex.provenance_input` |
| Gaia DR3 | `gaia_dr3_source`, `gaia_dr3_astrophys_param`, `gaia_dr3_astrophys_supp`, `gaia_dr3_allwise_best_neighbour`, `gaia_dr3_total_galactic_extinction_map` |
| CatWISE2020 | `catwise_2020` |
| AllWISE | `allwise_p3as_psd` |
| NEOWISE single exposures | `neowiser_p1bs_psd` |
| unWISE | `unwise_2019` |
| 2MASS | `fp_psc` (point sources), `fp_xsc` (extended sources) |
| ZTF | `ztf_objects_dr24` |
| Euclid | see section 7.2 |

### 7.4 Model grids (stretch comparison only, never training data)

| Grid | Link |
|---|---|
| Sonora Elf Owl | https://zenodo.org/records/15150881 |
| Sonora Diamondback | https://zenodo.org/records/12735103 |

### 7.5 Simulated data

| What | Link |
|---|---|
| Simulated SPHEREx galaxy spectra used in the star and galaxy study `[check]` | https://zenodo.org/records/11406518 |

---

## 8. Other surveys and services

| Service | Link |
|---|---|
| Canadian archive services index | https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/services/ |
| Canadian archive TAP | https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus/ |
| Canadian archive SIA | https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia/ |
| Canadian archive cutouts | https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/caom2ops/ |
| Canadian Solar System Object Image Search | https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/ssois/ |
| CDS Sesame name resolver `[check]` | https://cds.unistra.fr/cgi-bin/nph-sesame/-oJ?<name> |
| VizieR | https://vizier.cds.unistra.fr/ |
| VizieR TAP | https://tapvizier.cds.unistra.fr/TAPVizieR/tap |
| Aladin Lite `[check]` | https://aladin.cds.unistra.fr/AladinLite/ |
| IMCCE SkyBoT `[check]` | https://ssp.imcce.fr/webservices/skybot/ |
| AAVSO VSX `[check]` | https://www.aavso.org/vsx/ |
| WiseView | http://byw.tools/wiseview |

---

## 9. Papers

**SPHEREx mission and pipeline**
- Bock et al. 2025, The SPHEREx Satellite Mission: https://arxiv.org/abs/2511.02985
- Akeson et al. 2025, The SPHEREx Image and Spectrophotometry Processing Pipeline: https://arxiv.org/abs/2511.15823
- SPHEREx all-sky survey overview: https://arxiv.org/abs/2404.11017
- SMDET-1 paper (crowding costs about 1.5 magnitudes): https://arxiv.org/abs/2608.00046

**Papers on real SPHEREx spectra**
- Gagné et al. 2026, SPIFF pipeline and ultracool dwarf library: https://arxiv.org/abs/2604.22012
- Rustamkulov et al. 2026, 37 brown dwarfs against model grids: https://arxiv.org/abs/2607.00543
- Tu et al. 2026, SUDA atlas of 1,675 ultracool dwarfs: https://arxiv.org/abs/2604.26771
- Melnick et al. 2026, SPHEREx ice investigation overview: https://arxiv.org/abs/2603.22135
- Hora et al. 2026, ice and emission maps: https://arxiv.org/abs/2603.12390
- Ren et al. 2026, galaxy and AGN templates: https://arxiv.org/abs/2609.02167
- Comet 3I/ATLAS with SPHEREx: https://arxiv.org/abs/2508.15469

**Methods**
- Spectrum and image contrastive learning for star and galaxy separation (simulated SPHEREx): https://arxiv.org/abs/2607.20797
- Photometric redshift with autoencoders and simulation-based inference: https://arxiv.org/abs/2603.24668
- Typing ultracool dwarfs from 2MASS and WISE with machine learning: https://arxiv.org/abs/2605.20146
- The Cannon at low resolution: https://arxiv.org/abs/2203.13829
- Neural posterior estimation for atmospheric retrieval: https://arxiv.org/abs/2301.06575
- Conformal prediction with anomaly awareness for spectra (ASTRANet): https://arxiv.org/abs/2607.08044
- Conformal inference for open-set and imbalanced classes: https://arxiv.org/abs/2510.13037
- TabPFN: https://doi.org/10.1038/s41586-024-08328-6
- AION-1: https://arxiv.org/abs/2510.17960
- SpecCLIP: https://arxiv.org/abs/2507.01939
- Improved Gaia classifier: https://arxiv.org/abs/2405.01340
- Gaia DR3 classification of 12.4 million variable sources: https://arxiv.org/abs/2211.17238
- Asteroid rotation correction for SPHEREx: https://arxiv.org/abs/2602.08037
- Nitric oxide band strengths (Breeze and Ferriso 1964): https://doi.org/10.1063/1.1725743

---

## 10. Library documentation

| Library | Link |
|---|---|
| Astropy | https://docs.astropy.org |
| astroquery | https://astroquery.readthedocs.io |
| photutils | https://photutils.readthedocs.io |
| scikit-learn | https://scikit-learn.org |
| XGBoost | https://xgboost.readthedocs.io |
| LightGBM | https://lightgbm.readthedocs.io |
| CatBoost | https://catboost.ai |
| Optuna | https://optuna.readthedocs.io |
| SHAP | https://shap.readthedocs.io |
| MAPIE | https://mapie.readthedocs.io |
| PyTorch | https://pytorch.org |
| TabPFN | https://pypi.org/project/tabpfn |
| xcavation (aperture photometry for SPHEREx, licence `[check]`) | https://pypi.org/project/xcavation/ |
| spxquery (licence `[check]`) | https://pypi.org/project/spxquery/ |

---

## 11. Queries

**SPHEREx frames covering a position** (from the cutouts tutorial. Confirm the extra columns in `TAP_SCHEMA.columns`, K1)

```sql
SELECT a.uri, p.energy_bandpassname, p.time_bounds_lower
FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', 133.79513, -7.24515), p.poly)
```

**List real column names before writing code**

```sql
SELECT table_name, column_name, datatype, unit, description
FROM TAP_SCHEMA.columns WHERE table_name LIKE 'spherex.%'
```

**Cone pull from any IRSA catalogue table**

```sql
SELECT * FROM gaia_dr3_source
WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 270.0, 66.56, 1.5))
```

**DESI tiles with the most spectra** (assumes `healpix` is nside 64, nested, so dividing by 4 gives our order-5 tile `[check, K29]`)

```sql
SELECT healpix/4 AS cube_tile, COUNT(*) AS n FROM desi_dr1.zpix
WHERE zwarn = 0 GROUP BY healpix/4 ORDER BY n DESC
```

**DESI labels in one field**

```sql
SELECT targetid, target_ra, target_dec, z, spectype, zwarn FROM desi_dr1.zpix
WHERE zwarn = 0 AND 1 = CONTAINS(POINT('ICRS', target_ra, target_dec), CIRCLE('ICRS', 270.0, 66.56, 1.5))
```

Column names `targetid`, `target_ra`, `target_dec` are `[check]` in `TAP_SCHEMA` before use.

**Moving Object Search Tool by name**

```
https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most?catalog=spherex&input_type=name_input&obj_name=Ceres&obs_begin=2025+05+01&obs_end=2026+11+14&output_mode=Brief
```

The page shows both `output_mode` and `outfmt` as the format parameter. Test which works.

**Calling TAP by URL.** Encode spaces as `+`, quotes as `%27`, `%` as `%25`. Long URLs fail. From code, use POST (pyvo or httpx) with `QUERY`, `LANG=ADQL`, `FORMAT=csv`.

---

## 12. Download order and sizes

| Order | What | Size |
|---|---|---|
| 1 | SPIFF binned CSVs, templates, tables, README, manifest | about 57 MB |
| 2 | UltracoolSheet CSVs | about 15 MB |
| 3 | SPLICES catalogue | 3.1 GB |
| 4 | Cube tiles for the chosen fields | about 300 MB each |
| 5 | Per-field TAP pulls: Gaia, CatWISE, AllWISE, 2MASS, DESI, Euclid, SIMBAD | small per field |
| 6 | Calibration files: `spectral_wcs`, `solid_angle_pixel_map`, `epsf`, `l3_flux_corrections`, glow templates, crosstalk | `[check]` |
| Later | SPIFF unbinned CSVs | about 2 GB |
| Optional | Spectrophotometry Tool spectra (browser login, 20 positions a job) | small |

Keep every download in `data/`, which git ignores. Record name, size, checksum and source URL in `data/manifest.csv`.

---

## 13. DOIs, licences and credits

| Data | DOI or licence |
|---|---|
| SPHEREx QR2 | `10.26131/IRSA652` |
| SPHEREx QR3 | `10.26131/IRSA662` |
| SPHEREx DR1 | `[check]` |
| SPLICES | `10.26131/IRSA554`, cite Ashby et al. 2023 |
| SPIFF library | `10.5281/zenodo.19051216`, CC BY 4.0, cite Gagné et al. 2026 |
| UltracoolSheet | `10.5281/zenodo.4169084`, CC BY 4.0, cite the individual papers and the sheet |
| DESI DR1 | CC BY 4.0, acknowledgement text at https://data.desi.lbl.gov/doc/acknowledgments |
| Gaia DR3 | ESA acknowledgement `[check wording]` |
| IRSA | fixed acknowledgement sentence on the Quick Release overview page |

Code licences we cannot use: The Tractor (GPL-2), tractorjax-spherex (GPL-3). Our code is Apache-2.0.
