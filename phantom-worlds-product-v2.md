# 01. Product: what Phantom Worlds is and why each part exists

Agreed on Fri 13 Nov 2026. Replaces the scope parts of earlier docs. Where an earlier doc disagrees, this one wins.

## 1. What NASA asks for

Source: the challenge page, Details and Resources tabs, read on 13 Nov 2026.

**The one required objective.** A public web tool that displays SPHEREx images of the sky so anyone can quickly see how they change over time. The user enters Right Ascension and declination. The tool shows a series of images of that patch like a short video, so moving objects are easy to spot.

**The five test targets.** Barnard's Star, Epsilon Indi B (a pair of brown dwarfs orbiting a star), WISE 0855 (given as RA 08h55m10.831s, Dec -7d14m42.53s), and the variable stars RW Aurigae and R Draconis.

**Eight optional considerations.**
1. Easy to update with the latest data releases.
2. Creative display of the 102 bands so users can make discoveries. The page suggests adding together all data from each of the six detector arrays to raise signal to noise. Spectra on the fly earn extra credit.
3. Options to add together or subtract images taken at different times.
4. User-chosen field of view. Larger fields track faster movers and take longer to load.
5. Overlays from other telescopes such as Gaia or WISE.
6. Coordinates in the URL, so the tool can be embedded elsewhere.
7. Metadata such as contamination flags.
8. Existing tools such as Astropy and Aladin (CDS).

**Resources the page names.** The NASA/IPAC Infrared Science Archive (IRSA) SPHEREx pages, the SPHEREx tutorial notebooks, WiseView as a model, Gaia Data Release 3. Partner resources from the Canadian Space Agency (NEOSSat, CADC) are optional.

**Three sentences in the Background that we answer beyond the objective.**
- SPHEREx is especially sensitive to objects rich in hydrogen, water, carbon dioxide, carbon monoxide and other molecules.
- There will be "too much data for any one person or even computer code".
- The billion objects often overlap or vary in brightness. NASA wants creative new tools so that as many people as possible can help make discoveries.

Judges score five criteria with equal weight: Influence, Creativity, Validity, Relevance, Presentation. Relevance is judged against the objective first.

## 2. Our answer in one sentence

Phantom Worlds lets anyone search NASA's SPHEREx sky by the light each object gives off in 102 infrared bands, to find moving and unexplained objects that no catalogue lists yet, including in the crowded Milky Way.

## 3. Three steps, each tied to NASA's text

| Step | What the user gets | NASA text it answers |
|---|---|---|
| 1. Look | Any position plays as a time series, in each detector, with every optional consideration done | The objective and all eight considerations |
| 2. Search by light | Filter sources by molecule features and motion. Remove every known star | The molecule sentence, and "often overlap" |
| 3. Check, then review | Machine checks on every leftover, a dated prediction the next survey pass settles, then review by people | "Too much data for any one person or even computer code" |

Each step works when the next one is unfinished.

## 4. What makes us better on the test itself

Other teams are pointed at WiseView as the model, and many will call the IRSA cutout service. These are the gaps we close. Test targets and validation checks are tracked in `phantom_worlds_dataset_kit/csv_tables/nasa_5_test_targets.csv`, `phantom-worlds-ml-research.md` (§8–9), and `phantom_worlds_dataset_kit/tests/`.

1. **Speed.** We read only the bytes we need from the archive files. The five targets load from prepared data in under 3 seconds and work with our API off.
2. **Like with like.** Each SPHEREx frame sees a sky position in one band. Blinking raw frames mixes bands, so brightness jumps for reasons unrelated to time. We compare only matching band ranges.
3. **Sub-pixel motion.** The test targets move about one pixel between visits. We upsample, align frames to a fraction of a pixel, mark the measured position per visit, and offer a Difference view.
4. **WISE 0855 needs stacks.** It appears only in detector 6 and faintly in detector 5. Per-detector visit stacks are required to see it at all.
5. **Positions at the right date.** Catalogue coordinates of fast movers are years old. We move them to each frame's date and show both the entered position and where the object is now.
6. **Bright stars.** Three of five targets saturate or come close. Fits and stacks drop pixels that IRSA itself rejects, report overflow pixels separately, and measure position from the part of the star's image that is not overflowed.
7. **A report card.** One script measures every target against a pass mark set before the build, and publishes the result, pass or fail.

## 5. What is new in our build

Chosen from the brainstorm on 13 Nov. None has been checked against prior work yet. Say "we built", never "first".

| Idea | What it does | Tier |
|---|---|---|
| Observation matrix as the control | Every frame of a spot as a dot, date across, wavelength up. Drag across dates to play, across wavelengths to stack | A |
| Visits as colour | Visits 1, 2, 3 in the red, green, blue channels. Fixed stars come out white, movers as coloured dots. One still shows motion | A |
| Change spectrum | For a variable, the ratio of its spectrum between two visits, band by band | A |
| Follow motion | Stack frames along a chosen motion, so a faint mover adds up | A |
| Solar-system objects by name | Type an asteroid or comet name. IRSA's Moving Object Search Tool gives its SPHEREx frames and path | A |
| Comet 3I/ATLAS showcase | An interstellar comet with a gas feature, followed frame by frame | A |
| Same-season play, Colour difference, Test source | Parallax-free play, one detector minus another, a synthetic mover to practise on | A |
| Other telescopes | Every other mission's images of the position, from NASA's and Canada's archives | A |
| Remove known | Fit every catalogued star at positions from sharper surveys and subtract it | B |
| Deciding bands | Highlight the bands where the top two explanations disagree most, and say whether they are measured | B |
| Prediction check | Each moving case carries a locked, dated prediction of where it will be in the next visit. New data settles it | B |
| Searched map | Each patch records how deeply it has been searched, from injected test objects. Finding nothing becomes a stated limit | B |
| Edge check | The last band of one detector and the first band of the next sit close in wavelength and are measured at different times. A mismatch flags change within one visit. Kept only if the edge bands prove close enough | B, conditional |
| Pinned evidence, reputation from forecasts, refutation role, draw the light, recipes, spectrum time series, distance slider | Post-hackathon roadmap in `phantom-worlds-ml-research.md` (§10) | C |

## 6. Scope tiers

**Tier A, the test.** Done by Sat 22:00 WIB.
Position input in any common format and by name. Frame list for any position. Range-read cutouts. Alignment to Gaia. Per-detector visit stacks. Viewer with Play, Difference, Stack, Visits as colour, Follow motion. Observation matrix. Field of view choice. Gaia and CatWISE overlays, WISE imagery layer, flags. URL contract and embed mode. Spectrum on the fly. Light curve and change spectrum. Frame metadata. Weekly update job. Report card for the five targets. Every state designed. Then, as time allows inside Tier A: solar-system objects by name, Comet 3I/ATLAS, Same-season play, Colour difference, Test source, Other telescopes.

**Tier B, the signature.** Done by Sun 14:00 WIB, the feature freeze.
Remove known on two fields (W1925 in the Galactic plane, RW Aurigae off the plane). Band features and Search by light with presets. Identity panel with class estimate, confidence word, blend share and deciding bands. Detectors for movers, label mismatch and variability, with the edge check. Machine checks including the ghost check. Signals and cases list. Prediction check. Searched map. History strip. Benchmark test on known T and Y dwarfs.

**Tier C, stretch.** Only after B.
Accounts. Blind review. Evidence pinned to sky positions. Reputation including forecast scoring. Refutation role. Band ratio view. Draw the light. Recipes. Spectrum time series. Distance slider. 3D neighbourhood from the Gaia Catalogue of Nearby Stars. Minigames. Indonesian text.

Anything unfinished at the freeze appears on the Proof panel under "Next", described in one line each.

*   **Implemented in Hour-0 / Tier A Build (`phantom_worlds/`):** Position input by decimal RA/Dec, HMS/DMS sexagesimal, and target name; interactive Observation Matrix click-to-jump across visits; per-detector cutouts (`real_spherex_s3_wcs_cutout`) across all 5 test targets (`6.56'` FOV at `6.15"/px`); `Single frame`, `Median stack`, `Subtract`, `Colour difference (D6 and D4)`, `Visits RGB`, `Follow motion` shift-and-stack, `Invert`, `Play speed`, and `Test source (S/N 5)` overlays; pixel-aligned Gaia DR3 + CatWISE `W1`/`W2` overlays and quality bitmask flags; `Light Curve`, `Change Spectrum`, and `Motion` readouts (`/api/patch/metrics`) with saturation/SNR refusal honesty; `Other telescopes` links (`IRSA Finder Chart`, `SIMBAD`, `Aladin Lite`); solar-system moving objects via IRSA MOST + Comet `3I/ATLAS` (`/api/sso`); live `Proof` report card (`/api/proof/summary`) matching `fallback_data.js` offline; PNG/CSV exports; and on-the-fly 102-band spectra with Layer-1 molecule readings and `Model Estimate` confidence words (`E1`/`E2`).
*   **Next (Deferred to Tier B/C):** Remove known catalogued stars on W1925 and RW Aurigae fields, M1 injection suite and searched depth map, weekly archive update job, Same-season play / WISE imagery layer, and expanding SPHEREx S3 spectra toward ML release gates.

## 7. Truth rules for the product

1. Nobody at NASA receives or verifies public finds. Confirmation comes from a science team with new telescope data. Registration comes from bodies such as the Minor Planet Center or AAVSO. We prepare evidence in the form those bodies accept, and the person who found the object sends it.
2. Agreement among reviewers ranks cases. It does not make a case true.
3. A held prediction shows that a moving source is real and keeps its motion. Its type still needs a spectrum or follow-up.
4. Expected new brown dwarfs in one or two square degrees: about zero. Our proof rests on recovering known objects, on variables missing from the variable-star index, and on sources whose spectrum disagrees with their catalogue label.
5. SPHEREx alone loses about 1.5 magnitudes in crowded fields (SMDET-1 paper, arXiv 2608.00046). We state our measured limit.
6. We credit Backyard Worlds, WiseView, The Rogue Worlds Project, SPHEREx forced photometry and Aladin by name.

## 8. Who it is for

| Person | What they need | What they get |
|---|---|---|
| A curious visitor | See something real in one minute | The WISE 0855 tour: four detectors empty, the sixth shows a dot, then it moves |
| A volunteer hunter | A fast way to inspect many spots and a fair way to report | Search by light, signals with machine checks, cases, later review |
| A student or teacher | Understand what a reading means | Plain reading first, numbers one click deeper, origin on every value |
| An astronomer | Trust and reuse | Frame IDs, flags, pipeline version, exports, a proof page they can rerun |
