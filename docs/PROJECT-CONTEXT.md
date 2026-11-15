# Phantom Worlds: project context

Everything we decided, why we decided it, and how each part works. Written for anyone who works on the project, person or coding agent.

- Updated 14 Nov 2026.
- This file replaces the planning kit (`docs/01` to `docs/10`, `decisions.md`), the discussion deck, the prototype notes and the older project docs. Where any of them disagrees with this file, this file wins.
- In the repository this file is `docs/PROJECT-CONTEXT.md`. Links live in `docs/DATA-LINKS.md`. Setup for Claude Code lives in `SETUP.md` at the root.

Labels used in this file:

| Label | Meaning |
|---|---|
| `[VERIFIED]` | checked live by us, date given |
| `[SOURCED]` | from a cited paper or page |
| `[ESTIMATE]` | our arithmetic from published values. Replace with a measurement |
| `[TO CHECK]` | confirm before relying on it |
| `[FROM MEMORY]` | recalled without a source. Confirm before relying on it |

## Contents

0. How to use this file
1. Event, constraints and judging
2. The challenge, as NASA wrote it
3. How we got here: the reasoning behind each decision
4. Product
5. Language
6. The test: five targets, every weakness, every cover
7. Architecture, contracts and API
8. Methods, stage by stage
9. Machine learning
10. Interface
11. Community layer and game system (Tier C)
12. Build plan
13. Proof
14. Data facts from the resource pages
15. Decisions log
16. Open checks
17. Earlier artifacts and what changed since
18. Copy rules for the project page, video and slides

---

## 0. How to use this file

| You are working on | Read |
|---|---|
| Anything, at the start of a session | sections 1, 4 and 12 |
| Words or numbers on screen | sections 5 and 10 |
| `engine/`, `api/`, `proof/` | sections 7 and 8 |
| Any of the five test targets | section 6 |
| Models, classes, molecule readings, training data | section 9, plus `DATA-LINKS.md` section 7 |
| Validation or the report card | section 13 |
| Archive access, file layouts, flags | section 14, plus `DATA-LINKS.md` |
| Accounts, review, reputation, games | section 11 |
| Why something is the way it is | sections 3 and 15 |
| The project page, the video, slides | sections 4, 13 and 18 |

The plan is a default and wrong somewhere. When the data, a tutorial or a test shows a better route, take it, log it in `docs/decisions.md`, and update this file.

---

## 1. Event, constraints and judging

### Event

- NASA Space Apps Challenge 2026, Purwokerto local event (virtual). Challenge 12, "Planet X and SPHEREx".
- Build window: Sat 14 Nov 2026 09:00 WIB to Sun 15 Nov 2026 23:59 WIB. Nothing is accepted after the window closes.
- Local judging: 16 to 22 Nov. Judges read the project page and open the live site. Global nominees: 3 Dec.

### Constraints

- Public data only, mostly NASA data. No contact with outside experts, science teams or other projects.
- Scope is global, never a local or regional niche.
- Nothing on screen that does not work. Nothing invented.
- The project is self-contained. Every step in these files can be carried out by whoever picks it up, person or coding agent. Nothing waits on a named person, and no step depends on an outside party answering.

### Judging

Five criteria, equal weight: Influence, Creativity, Validity, Relevance, Presentation. Relevance is judged against the required objective first.

---

## 2. The challenge, as NASA wrote it

Source: challenge page, Details and Resources tabs, read 13 Nov 2026. Links in `DATA-LINKS.md` section 1.

**The one required objective.** A public web tool that displays SPHEREx images of the sky so anyone can quickly see how they change over time. The user enters Right Ascension and declination. The tool shows a series of images of that patch like a short video, so moving objects are easy to spot.

**The five test targets.** Barnard's Star. Epsilon Indi B (a pair of brown dwarfs orbiting a star). WISE 0855, given as RA 08h55m10.831s, Dec -7d14m42.53s. The variable stars RW Aurigae and R Draconis.

**Eight optional considerations.**
1. Easy to update with the latest data releases.
2. Creative display of the 102 bands so users can make discoveries. The page suggests adding together all data from each of the six detector arrays to raise signal to noise. Spectra on the fly earn extra credit.
3. Options to add together or subtract images taken at different times.
4. User-chosen field of view. Larger fields track faster movers and take longer to load.
5. Overlays from other telescopes such as Gaia or WISE.
6. Coordinates in the URL, so the tool can be embedded elsewhere.
7. Metadata such as contamination flags.
8. Existing tools such as Astropy and Aladin (CDS).

**Resources the page names.** The IRSA SPHEREx pages, the SPHEREx tutorial notebooks, WiseView as a model, Gaia DR3. Partner resources from the Canadian Space Agency (NEOSSat, CADC) are optional.

**Three sentences in the Background that we answer beyond the objective.**
- SPHEREx is especially sensitive to objects rich in hydrogen, water, carbon dioxide, carbon monoxide and other molecules.
- There will be "too much data for any one person or even computer code".
- The billion objects often overlap or vary in brightness. NASA wants creative new tools so that as many people as possible can help make discoveries.

---

## 3. How we got here: the reasoning behind each decision

In date order. Each step says what was asked, what we decided, and why.

### 3.1 The starting vision (Fri 13 Nov, morning)

The brief: a fresh public tool for SPHEREx that goes beyond the viewer. Use the molecule information NASA mentions as the baseline. Add machine learning that helps identify new objects. Give the public a structured place to contribute their analysis, discuss it like a forum, vote, and earn reputation. Hand agreed cases to scientists for verification. Phantom Worlds is a new product that uses Backyard Worlds, WiseView and past projects as references only, never a continuation of them.

What we kept: a public platform, machine learning with a stated confidence, community review, reputation, discussion, and a hand-off.

What we changed, and why:
1. **"Sent to NASA for verification" became evidence packets.** Nobody at NASA receives or verifies public finds. Confirmation comes from a science team with new telescope data. Registration comes from bodies such as the Minor Planet Center (asteroids, comets), AAVSO VSX (variable stars) and Backyard Worlds (brown dwarf candidates). We prepare the evidence in the form each body accepts, and the person who found the object sends it.
2. **Voting became blind structured review.** Members answer fixed questions before seeing others' answers. Agreement ranks cases. It never makes a case true.
3. **A test that needs no expert was added: the prediction check.** Each moving case carries a locked, dated prediction of where it will be at the next SPHEREx pass. New data settles it. A held prediction shows the source is real and keeps its motion. This gives the public a fair way to be right without outside contact.
4. **The required objective comes first.** The judged core is the viewer and the five targets. Everything else is built on top and each layer works when the next is unfinished.

### 3.2 Priority and feel (13 Nov)

- Priority: a smaller part working on real SPHEREx data comes before a full design shown as mockups. The whole system is shown too if it can be finished. Unfinished parts appear on the Proof panel under "Next".
- Feel: a complete product with precise button labels and wording, as if built by a large engineering team. Figma and Google Maps were named only for that feel, never as patterns to copy. "Ontologically shaped" became a closed vocabulary: one name for each thing, one verb for each action (section 5).
- Nothing irrelevant, nothing that reads as made by a template.

### 3.3 Word choices (13 Nov)

- "Band" for a wavelength slice, over "colour" or "channel".
- "Reputation" for a member's score, over "accuracy".
- Confidence words with fixed ranges: under 50% Unclassified, 50 to 69% Possibly, 70 to 89% Probably, 90% and above Very likely.

### 3.4 Innovation (13 Nov)

The request was for fresh ideas, not statistical defaults, using two idea-generation methods (generate fresh ideas, get more perspectives). Ideas were generated, attacked, and kept only when they use something SPHEREx has and older tools lack. The kept ideas and their tiers are in section 4.5. Rule for all of them: say "we built", never "first", because none has been checked against prior work.

### 3.5 Beat other teams on the test (13 Nov)

The goal: handle the five targets better than other teams, cover every weakness, and innovate on top. Other teams are pointed at WiseView as the model and many will call the IRSA cutout service. We listed what goes wrong on each target and the cover for each (section 6). The biggest finds:
- Raw SPHEREx frames cannot be blinked against each other. Each frame sees a position in one band, so brightness jumps for reasons unrelated to time.
- WISE 0855 is invisible in single frames and in detectors 1 to 4. Per-detector visit stacks are required.
- The challenge's WISE 0855 coordinates are an old-epoch position. The object is now roughly 16 to 21 pixels west `[ESTIMATE]`.
- Three of five targets saturate or come close.
- Masking every flagged pixel removes the stars, because bit 21 marks pixels on known sources.
- Spacecraft glow near 4.5 µm falls exactly where WISE 0855 shines.

### 3.6 Data released (13 Nov, afternoon)

The Resources tab went live. Every link was opened. Standing instruction: the plan serves the project and does not limit it. Agents may propose and take better routes. Additions from the resource pages: solar-system objects by name, Comet 3I/ATLAS, Same-season play, Colour difference, Test source, Other telescopes, ghost check, quick spectrum from the all-sky cube (section 4.5 and section 8, additions).

### 3.7 Machine learning vision and the correction (13 Nov, night)

The vision: a heavy model aimed at maximum accuracy that reads the 102 bands down to molecules ("40% CO2, 20% NO"), then combines SPHEREx with other surveys to give the most likely object type. The tool does not judge or decide. It gives readings and an analysis of what is most likely.

What the research showed (section 9):
1. A full composition breakdown is not in the data. NO's main band is at 5.3 µm, outside SPHEREx's range. The SPHEREx ice team itself measures feature strengths and does not split spectra into mixtures. Hydrogen and helium, most of the mass, leave no usable feature. Brown dwarf atmosphere models misfit real SPHEREx spectra.
2. What is measurable: feature strengths with errors, and for ice sightlines each molecule as a percentage of water ice.
3. Accuracy is limited first by signal and blending, then by label quality, then by which other surveys are added. Model size comes last. A learned spectrum encoder moved star purity by about one point in the one published comparison. Adding image data moved it by about 25 points.
4. So the heavy part of our system is fusion: several experts, each reading one kind of evidence, joined by a calibrated combiner.

### 3.8 The model choice (13 Nov, 22:33 to 22:36)

The question was which architecture, in plain terms. Answer: XGBoost as the main type model, a template match as the second opinion, logistic regression to merge them, isotonic calibration and conformal sets for honest percentages, isolation forest for unusual objects, a separate XGBoost for real against artefact, and a polynomial fit for molecule readings. XGBoost is the best fit for our data size and shape, not proven best overall. Alternatives worth testing are listed, and the winner is chosen on our own test split (section 9.11).

### 3.9 Datasets (14 Nov)

The data plan (section 9.4, links in `DATA-LINKS.md` section 7):
- Labels are plentiful: DESI DR1, Gaia DR3, SPLICES, UltracoolSheet, SIMBAD, Euclid.
- SPHEREx spectra to train on are the bottleneck. One bulk library exists (SPIFF, ultracool dwarfs). For every other type we build spectra from the SPHEREx all-sky cube in chosen fields.
- IRSA's Spectrophotometry Tool takes 20 positions per job, two jobs at once, no API, and hours per job. Nothing in the pipeline depends on it. Its spectra are an extra check when available.

### 3.10 Move to Claude Code (14 Nov)

The GitHub repository is ready. Work moves to Claude Code with three files: `SETUP.md`, this file, and `DATA-LINKS.md`. The docs describe the project and its order of work, without assigning work to named people or start times.

### 3.11 Molecule readings first (14 Nov)

The original idea, restated: decode each SPHEREx spectrum to the molecular level, train on that level to estimate the most likely object type, and show a confidence that helps a person shape their own thinking and research. The tool does not judge or decide.

"Molecular level" means the molecule features we can measure: which molecules show in the light, and how strongly. A full composition stays out of reach for the reasons in section 9.3.

How the idea is built:
1. **Decode.** Every source gets molecule readings: one feature per molecule with its strength, error and significance, or a refusal with its reason (section 9.3).
2. **Identify.** A model trained on those readings alone gives a type estimate. This is the idea in its pure form. It is stored as its own result and shown on screen.
3. **Explain.** Every estimate is explained in features: which ones moved it toward a type, which ones moved it away, and which measurement would settle it.

What we added, and why: molecule readings alone cannot carry every type. Hot stars, galaxies and quasars are expected to show few of our features at SPHEREx's resolving power `[ESTIMATE, measured by the input ladder]`. Their identity sits in the overall spectrum shape, brightness and motion. So the full spectrum and the other surveys come in as further steps, and the gain from each step is measured and published (section 9.11, proof test B13). That number says how much of an object's identity its molecules alone reveal, which is a measured statement about SPHEREx itself.

---

## 4. Product

### 4.1 Our answer in one sentence

Phantom Worlds lets anyone search NASA's SPHEREx sky by the light each object gives off in 102 infrared bands, to find moving and unexplained objects that no catalogue lists yet, including in the crowded Milky Way.

### 4.2 Three steps, each tied to NASA's text

| Step | What the user gets | NASA text it answers |
|---|---|---|
| 1. Look | Any position plays as a time series, in each detector, with every optional consideration done | The objective and all eight considerations |
| 2. Search by light | Filter sources by molecule features and motion. Remove every known star | The molecule sentence, and "often overlap" |
| 3. Check, then review | Machine checks on every leftover, a dated prediction the next survey pass settles, then review by people | "Too much data for any one person or even computer code" |

Each step works when the next one is unfinished.

### 4.3 What makes us better on the test itself

Details and checks are in section 6.

1. **Speed.** We read only the bytes we need from archive files. The five targets load from prepared data in under 3 seconds and work with our API off.
2. **Like with like.** We compare only matching band ranges, so brightness changes mean real change.
3. **Sub-pixel motion.** The test targets move about one pixel between visits. We upsample, align frames to a fraction of a pixel, mark the measured position per visit, and offer a Difference view.
4. **WISE 0855 needs stacks.** It appears only in detector 6 and faintly in detector 5. Per-detector visit stacks are the default view for it.
5. **Positions at the right date.** Catalogue coordinates of fast movers are years old. We move them to each frame's date and show both the entered position and where the object is now.
6. **Bright stars.** Fits and stacks drop pixels IRSA itself rejects, report overflow pixels separately, and measure position from the part of the star's image that is not overflowed.
7. **A report card.** One script measures every target against a pass mark set before the build and publishes the result, pass or fail.

### 4.4 Layers

| Layer | Contents | Tier |
|---|---|---|
| Viewer | the objective, the five targets, all eight considerations | A |
| Search and checks | Remove known, Search by light, Identity with class, detectors, machine checks, cases, prediction check, searched depth | B |
| Community | accounts, blind review, evidence, forecasts, reputation, games | C |

### 4.5 What is new in our build

None has been checked against prior work. Say "we built", never "first".

| Idea | What it does | Why it earns its place | Tier |
|---|---|---|---|
| Observation matrix as the control | Every frame of a position as a dot, date across, wavelength up. Drag across dates to play, across wavelengths to stack | SPHEREx data is a date by wavelength grid. The control shows the data's real shape and replaces a pile of dropdowns | A |
| Visits as colour | Visits 1, 2, 3 in the red, green, blue channels. Fixed stars come out white, movers as coloured dots | One still image shows motion, so it works in a screenshot and on the project page | A |
| Change spectrum | For a variable, the ratio of its spectrum between two visits, band by band | Three visits give only three points of a light curve. The change spectrum shows how the change depends on wavelength | A |
| Follow motion | Stack frames along a chosen motion, so a faint mover adds up | WiseView's shift and add, in every SPHEREx band | A |
| Solar-system objects by name | Type an asteroid or comet name. IRSA's Moving Object Search Tool gives its SPHEREx frames and path | The challenge names asteroids and comets first | A |
| Comet 3I/ATLAS showcase | An interstellar comet with a carbon dioxide coma, followed frame by frame | Motion and a gas feature in one view. IRSA gives the comet's position per frame | A |
| Same-season play | Play only visits from the same side of Earth's orbit, which removes parallax | WiseView's "separate scan directions", for SPHEREx | A |
| Colour difference | One detector's stack minus another's | The SPHEREx team's own method for very red sources. WISE 0855 stands alone in detector 6 minus detector 4 | A |
| Test source | Insert a synthetic mover of chosen brightness and motion in any band | WiseView has synthetic objects. Ours work in 102 bands, use the real PSF, and share code with the injection test | A |
| Other telescopes | Every other mission's images of the position, from NASA's and Canada's archives | Uses the partner agency resource for a real purpose | A |
| Remove known | Fit every catalogued star at positions from sharper surveys and subtract it | Answers "often overlap". Exposes what no catalogue explains | B |
| Deciding bands | Highlight the bands where the top two explanations disagree most, and say whether they are measured | Shows why the class is uncertain and which data would settle it | B |
| Prediction check | Each moving case carries a locked, dated prediction. New data settles it | A fair test for the public with no expert needed | B |
| Searched map | Each patch records how deeply it has been searched, from injected test objects | Finding nothing becomes a stated limit, which is the honest Planet X statement | B |
| Edge check | The last band of one detector and the first band of the next sit close in wavelength and are measured at different times. A mismatch flags change within one visit | Variability inside a visit with no extra data. Kept only if K12 shows the edge bands are close enough | B, conditional |
| Ghost check | Ghost and streak flags plus crosstalk parameter files say where false images fall | Kills the most common false signal with a stated reason | B |
| Pinned evidence, reputation from forecasts, refutation role, draw the light, recipes, spectrum time series, distance slider, 3D neighbourhood, minigames | See sections 11 and 12 | Community and stretch | C |

### 4.6 Scope tiers

**Tier A, the test.** Highest priority. Complete before Tier B work begins.
Position input in any common format and by name. Frame list for any position. Range-read cutouts. Alignment to Gaia. Per-detector visit stacks. Viewer with Play, Difference, Stack, Visits as colour, Follow motion. Observation matrix. Field of view choice. Gaia and CatWISE overlays, WISE imagery layer, flags. URL contract and embed mode. Spectrum on the fly. Light curve and change spectrum. Frame metadata. Weekly update job. Report card for the five targets. Every state designed. Then, as time allows inside Tier A: solar-system objects by name, Comet 3I/ATLAS, Same-season play, Colour difference, Test source, Other telescopes.

**Tier B, the signature.** Built after the Tier A gate (section 12.5). Stops at the freeze review.
Remove known on two fields (W1925 in the Galactic plane, RW Aurigae off the plane). Band features and Search by light with presets. Molecule readings. Identity panel with class estimate, confidence word, blend share and deciding bands. Detectors for movers, label mismatch and variability, with the edge check. Machine checks including the ghost check. Signals and cases list. Prediction check. Searched map. History strip. Benchmark test on known T and Y dwarfs.

**Tier C, stretch.** Only after a clean freeze review.
Accounts. Blind review. Evidence pinned to sky positions. Reputation including forecast scoring. Refutation role. Band ratio view. Draw the light. Recipes. Spectrum time series. Distance slider. 3D neighbourhood from the Gaia Catalogue of Nearby Stars. Minigames. Indonesian text.

Tier order is a default priority, not a wall. A later item that is cheap and makes the objective stronger can move up, with a line in `docs/decisions.md`. Anything unfinished at the freeze review appears on the Proof panel under "Next", one line each.

### 4.7 Truth rules for the product

1. Nobody at NASA receives or verifies public finds. Confirmation comes from a science team with new telescope data. Registration comes from bodies such as the Minor Planet Center or AAVSO. We prepare evidence in the form those bodies accept, and the person who found the object sends it.
2. Agreement among reviewers ranks cases. It does not make a case true.
3. A held prediction shows that a moving source is real and keeps its motion. Its type still needs a spectrum or follow-up.
4. Expected new brown dwarfs in one or two square degrees: about zero. Our proof rests on recovering known objects, on variables missing from the variable-star index, and on sources whose spectrum disagrees with their catalogue label.
5. SPHEREx alone loses about 1.5 magnitudes in crowded fields (SMDET-1 paper, arXiv 2608.00046). We state our measured limit.
6. We credit Backyard Worlds, WiseView, The Rogue Worlds Project, SPHEREx forced photometry and Aladin by name.
7. The tool gives readings and estimates. It never decides what an object is.

### 4.8 Who it is for

| Person | What they need | What they get |
|---|---|---|
| A curious visitor | See something real in one minute | The WISE 0855 tour: four detectors empty, the fifth a trace, the sixth a dot, then it moves |
| A volunteer hunter | A fast way to inspect many spots and a fair way to report | Search by light, signals with machine checks, cases, later review |
| A student or teacher | Understand what a reading means | Plain reading first, numbers one click deeper, origin on every value |
| An astronomer | Trust and reuse | Frame IDs, flags, pipeline version, exports, a proof page they can rerun |

---

## 5. Language

Every label, message, tooltip, URL word and public identifier follows this section. If a needed word is missing, add it here in the same pull request. Do not coin a synonym in code.

### 5.1 Things

| Term on screen | Meaning | Never write |
|---|---|---|
| Sky | the whole celestial sphere as shown | map, universe |
| Position | RA and Dec of a point | location, coords |
| Field | a region we have fully processed | area, zone, tile |
| Frame | one SPHEREx exposure | image, shot, snapshot |
| Visit | all frames of one survey pass over a position. Passes come about six months apart | epoch, pass, session |
| Detector | one of the six arrays, D1 to D6 | channel, camera, sensor |
| Band | one of the 102 wavelength slices | channel, colour, filter |
| Stack | frames added together | coadd, composite, sum |
| Source | any point of light | object, dot, star (unless it is known to be a star) |
| Spectrum | a source's brightness in each band | SED, colours |
| Feature | a dip or rise in a spectrum tied to a molecule | index, signature |
| Signal | something a detector flagged, before checks | detection, hit, alert |
| Case | a signal that passed every machine check and is open for review | candidate, discovery, report |
| Check | one automatic test on a signal | filter, gate |
| Evidence | one item attached to a case: a measurement, a saved view, a comparison | comment, post |
| Review | one member's answers on one case, given before seeing other answers | vote, rating |
| Prediction | a locked statement of where a moving case will be at a stated date | forecast (reserved for a member's probability) |
| Forecast | a member's stated probability that a prediction will hold | bet, guess |
| Packet | the exportable evidence of a case, shaped for the body that takes it | submission, report |
| Member | a signed-in person | user, player |
| Guest | a person who is not signed in | anonymous, visitor |
| Reputation | a member's score from known-answer cases and settled forecasts, from 0 to 1 | accuracy, reliability, trust score |
| XP | a member's effort points | points, score |
| Class | a member's level, O B A F G K M L T Y | rank, tier |
| Searched depth | the faintest test object recovered in a patch at a stated rate | coverage, completeness |

Source status has exactly three values: **Known** (has a catalogue entry and a type), **Unclassified** (has a catalogue entry, no type), **Uncatalogued** (no entry in any catalogue we check).

Case states, in order: **Detected, Machine-checked, In review, Reviewed, Prediction held, Follow-up ready, Confirmed elsewhere.** Two exits at any point: **Artefact** and **Explained**. An exit is a result and is credited.

### 5.2 Verbs

Each button is a verb from this list plus an object. Each verb does one thing everywhere.

| Verb | Does |
|---|---|
| Go to | move the view to a position or a named source |
| Play / Pause | show visits or frames one after another |
| Stack | add frames together |
| Difference | subtract one date from another |
| Remove known | subtract every catalogued source from the image |
| Follow motion | stack along a chosen motion |
| Measure | return a number from the image: separation, motion, brightness |
| Compare | place two sources or two visits side by side |
| Save view | store the exact view as a link |
| Follow | get notified when a position or case has new data |
| Report | propose a position as a signal |
| Review | answer the structured questions on a case |
| Add evidence | attach a measurement, view or comparison to a case |
| Export | download data in a named format |

"Difference" and "Remove known" are different operations and never share a word. "Search" is used only for Search by light and the position box.

### 5.3 Reserved words

| Word | Allowed only when |
|---|---|
| Confirmed | an outside body confirmed it, with a link |
| Discovered, discovery | after "Confirmed". Before that, write "case" |
| Verified | never used for anything we or members do |
| Estimate | every model output |
| New | only for data that arrived since the member's last visit |
| Planet | only when quoting the challenge or a published source |

Never write "AI found", "AI thinks" or "the AI". Write "estimate" and name the method: "template fit", "classifier".

### 5.4 Readings

Every number shown has four parts: value, unit, uncertainty, origin.

`8.1 ± 0.6″/yr · Measured, 3 visits`
`8.15″/yr · Catalogue`

Origin is exactly one of: **Measured** (by us from SPHEREx frames), **Catalogue** (published, with the catalogue name on click), **Estimated** (model output), **Assumed** (a stated default).

Formats:
- RA and Dec: decimal degrees to 5 places by default, sexagesimal on toggle. Always J2000 (ICRS) and say so once per panel.
- Dates: `14 May 2026`. Times in UTC.
- Wavelength: `4.41 µm`, two decimals.
- Angles on the sky: arcseconds with `″`, and pixels in brackets when it helps: `8.1″ (1.3 px)`.
- Motion: `″/yr` plus direction in degrees east of north.
- Brightness: microjansky in data, AB magnitude one click deeper.
- Signal to noise: `S/N 11`.
- Significant figures follow the uncertainty. Never show more digits than the error supports.
- Missing value: `not measured`, with the reason. Never `N/A`, `null`, `--` or `0`.

### 5.5 Confidence words

Fixed ranges. The word always appears with the number.

| Probability | Word |
|---|---|
| under 50% | Unclassified |
| 50 to 69% | Possibly |
| 70 to 89% | Probably |
| 90% and above | Very likely |

Example: `Probably an ultracool dwarf · 74% · Estimated, classifier v0.3`. When the template fit disagrees with the classifier, the shown value is capped at 50% and the panel says why.

### 5.6 States

One pattern for every non-normal state: what happened, what you are seeing, what you can do.

| State | Example |
|---|---|
| Loading | `Reading frame 14 of 21.` |
| Empty | `SPHEREx has no frames of this position in detector 6 yet. Try another detector.` |
| Partial | `37 of 102 bands measured. The rest arrive with later visits.` |
| Slow source | `The archive is slow. Showing frames as they arrive.` |
| Error | `The archive did not answer. This is the copy from 12 Nov 2026. Retry.` |
| Outside a field | `Search by light works in processed fields. This position is outside them. The time series still works here.` |
| Blocked by a rule | `These two stacks cover different bands, so they cannot be compared. Pick the same detector.` |
| Reading refused | `Not measured: the source varies between visits.` |

No exclamation marks. No "Oops", "Sorry", "Something went wrong". An error always names the next step.

### 5.7 Label rules

1. Verb plus object, one to three words, sentence case: `Report this source`, `Open case`, `Export packet`.
2. Never `Submit`, `OK`, `Click here`, `Learn more`, `Get started`.
3. Plain reading first, the number one click deeper: `Moved 8 arcseconds in a year, about 1.3 pixels.`
4. A term from the Things table appears with the same spelling and capital letters everywhere.
5. Tooltips answer "what is this" in one sentence of 20 words or fewer.
6. Sentences in the interface have no semicolons, no dashes used as punctuation, and no questions.
7. Banned words anywhere in copy: seamless, effortless, powerful, unlock, empower, revolutionary, magic, smart, AI-powered, cutting-edge, robust, journey.

### 5.8 Identifiers in code and URLs

Use the same nouns in snake_case or camelCase: `frame`, `visit`, `detector`, `band`, `stack`, `source`, `signal`, `case`, `check`, `prediction`, `forecast`, `reputation`, `searched_depth`. Detector values are integers 1 to 6. Bands are integers 1 to 102. Case IDs are `PW-` plus four digits.

---

## 6. The test: five targets, every weakness, every cover

The challenge is judged first on the objective and the five targets.

### 6.1 Facts about the data

- SPHEREx pixel: 6.15″. Six detectors, 17 bands each, 0.75 to 5.01 µm. `[SOURCED: Bock et al. 2025]`
- Detector ranges in µm, from the IRSA tutorial: D1 0.75 to 1.09 (R 39), D2 1.10 to 1.62 (R 41), D3 1.63 to 2.41 (R 41), D4 2.42 to 3.82 (R 35), D5 3.83 to 4.41 (R 112), D6 4.42 to 5.00 (R 128). `[SOURCED: spherex-intro tutorial]`
- The Explanatory Supplement v2.1 gives wider ranges that overlap slightly at the edges: 0.744 to 1.116, 1.099 to 1.651, 1.636 to 2.421, 2.423 to 3.822, 3.809 to 4.420, 4.412 to 5.002. The true wavelength of every pixel comes from `CWAVE` and `CBAND`. Never hardcode edges.
- Channel 17 of detector 3 and channel 1 of detector 4 have no data in Year 1. `[SOURCED: Explanatory Supplement]`
- Each frame sees a given sky position in one band. A full spectrum of a position is built from many frames across a visit.
- The whole sky is covered about every six months.
- IRSA TAP answers a frame-list query in about 5 s. It sends no CORS header, so browsers cannot call it. `[VERIFIED 12 Nov]`
- The IRSA cutout service took over 12 s per cutout and returned "503 Server busy" with four requests at once. `[VERIFIED 12 Nov]` The IRSA tutorial reports 84 cutouts in about 13 s with 10 threads, so its speed depends on load. The call is the file URL plus `?center=<ra>,<dec>d&size=<deg>`. Last resort only. `[SOURCED: spherex-cutouts tutorial]`
- IRSA serves the raw Level 2 files with HTTP range support. Each is 71.6 MB, uncompressed. `[VERIFIED 12 Nov]`
- Each file holds IMAGE (2040 × 2040, float32, MJy/sr, zodiacal light not subtracted), FLAGS (int32 bit map), VARIANCE, ZODI (modelled zodiacal light), PSF or EPSF, WCS-WAVE (wavelength lookup for display). `VERSION` is in the PRIMARY header. `[SOURCED: tutorials]`
- Sky WCS is TAN with SIP distortion. Wavelength and bandwidth per pixel come from the WCS with key `W`. Set its SIP to none before use, as the tutorial does.
- Releases: DR1 (November 2026) reprocesses QR2. QR3 (since September 2026) holds newer data. DR1 and QR3 together are what archive searches return. QR2 stays downloadable until February 2027. New data arrives weekly. `[SOURCED: IRSA Quick Release overview]`
- Public S3 bucket `nasa-irsa-spherex`, region `us-east-1`, anonymous, prefixes `dr1`, `qr3`, `qr2`. Search results carry a `cloud_access` column. Confirm the key layout by listing it `[TO CHECK]`.
- FLAGS bits, from Table 16 of the Explanatory Supplement v2.1 (10 Nov 2026): 0 transient, 1 overflow, 2 onboard error, 4 phantom, 5 reference, 6 non-functional, 7 dichroic, 9 missing data, 10 hot, 11 cold, 12 full sample, 14 phantom correction missing, 15 non-linear, 17 persistence, 19 outlier, 20 crosstalk, 21 known source, 22 ghost, 23 ghost from another detector (unused), 24 ghost from outside the field, 25 satellite streak, 26 blooming, 27 snowball, 28 halo of a transient, 29 halo of a satellite streak. Older QR2 files carry fewer bits.
- IRSA's own all-sky cubes reject pixels with bits 0, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 25, 26, 27, 28, 29. We use the same list.
- Overflow (bit 1) means a pixel reached about half its full well during the exposure. IRSA keeps these pixels. Detectors 1 to 3 hit the threshold near 50,000 electrons, detectors 4 to 6 near 30,000.
- Known artefacts: ghosts from bright stars inside and outside the field, a ghost about 10′ wide near the detector 3 and 4 boundary, stray light from very bright stars about 8° away, Moon stray light at frame edges in detectors 1, 4, 5 and 6, persistence after bright stars, crosstalk images displaced about 32 rows or by multiples of 64 pixels, satellite streaks.
- Emission not from the sky: the 1.083 µm helium line in detectors 1 and 2, auroral lines in detector 1, and glow from atomic oxygen hitting the spacecraft near 2.9 µm and 4.5 µm. The 4.5 µm glow falls in detectors 5 and 6, where WISE 0855 is. Other atmospheric lines at 0.78, 0.84, 0.93, 1.13, 1.81, 2.63, 2.75, 4.03, 4.64 µm. About 1% of exposures show diffuse optical transients. IRSA provides templates for helium, aurora and spacecraft glow.
- An all-sky DR1 HiPS cube exists with 102 planes (two blank), maximum order 5, dated 26 Oct 2026. Each FITS tile is about 300 MB. IRSA labels spectra from it as for visualization only.

### 6.2 Frames available per target `[VERIFIED 12 Nov]`

| Target | Frames | Visits |
|---|---|---|
| Barnard's Star | 359 | Aug to Oct 2025, Mar to May 2026, Aug to Sep 2026. 17 to 25 per detector per visit |
| Epsilon Indi B | 447 | Apr to Jun 2025, Sep to Nov 2025, Apr to May 2026, Sep to Oct 2026 |
| WISE 0855 | 256 | 5 to 6 May 2025 (3 frames in D6, 8 in D5). 31 Oct to 13 Dec 2025 (19 in D6). 21 Apr to 14 May 2026 (21 in D6) |
| RW Aurigae | 333 | Sep 2025, Feb to Mar 2026, Sep 2026. 18 to 19 per detector per visit |
| R Draconis | 2,483 on 222 dates | Deep field near the north ecliptic pole. Near-continuous Apr 2025 to Sep 2026 |

Re-query before relying on these counts (K11). New frames may have arrived.

### 6.3 Target by target

**Barnard's Star**
- Motion 10.39″/yr. Shift across the visits so far: 10.3″, or 1.7 px. `[SOURCED, ESTIMATE]`
- Weakness: saturated core (K about 4.5). Cover: the quality plane marks overflow pixels. Position comes from a fit to the outer part of the star's image, overflow pixels left out. Report which detectors saturate.
- Weakness: stale coordinates. A J2000 catalogue position is about 275″ (45 px) from where the star is in 2026 `[ESTIMATE]`. Cover: move the position to each frame's date.
- Pass mark: measured motion within 1.0″/yr of Gaia DR3.

**Epsilon Indi B**
- A T dwarf pair, unresolved by SPHEREx, moving with Epsilon Indi A at 4.70″/yr. Shift 6.4″, 1.0 px over 1.4 yr. `[SOURCED, ESTIMATE]`
- Weakness: the bright primary nearby can leave ghosts and scattered light. Cover: flags shown, artefact check on by default, the primary marked on the overlay.
- Weakness: stale coordinates, about 125″ (20 px) since J2000 `[ESTIMATE]`. Same cover.
- Pass mark: motion within 1.5″/yr of the catalogue value.

**WISE 0855**
- Y dwarf at 2.28 pc, about 285 K. Motion 8.15″/yr (RA -8.12, Dec +0.68). W2 = 13.9 Vega, AB 17.2. `[SOURCED]`
- Its emission peaks near 10 µm, outside SPHEREx's range. Of SPHEREx's six detectors only D6 catches much of its light. Correct wording: "at WISE 0855's position, D1 to D4 see nothing, the red end of D5 catches a trace, D6 sees a dot".
- Weakness: invisible in single frames and in D1 to D4. Estimated S/N 4 to 11 per D6 frame and 19 to 47 in a 19-frame D6 visit stack `[ESTIMATE]`. Cover: per-detector visit stacks are the default view for this target. The tour shows all six detectors side by side.
- Weakness: the challenge's coordinates are an old-epoch position. With RA motion of -8.12″/yr the object now sits roughly 100 to 130″ west, 16 to 21 px, depending on the catalogue epoch `[ESTIMATE]`. Cover: compute from the catalogue epoch, centre on the present position, mark the entered position too. Never hardcode the offset.
- Weakness: visit 1 has only 3 frames in D6. Cover: motion is measured between visits 2 and 3. Visit 1 is shown with its measured S/N and no claim.
- Weakness: spacecraft glow near 4.5 µm. Cover: check IRSA's glow template level at the position and require a point-like shape that moves with the catalogue motion.
- Pass mark: 5σ or better in both full D6 visit stacks, absent in D1 to D4, motion within 2.0″/yr and 15° of the published vector.
- Task T03 stacks the 21 D6 frames of Apr to May 2026 and look for the source. If it fails, Epsilon Indi B becomes the motion showcase and WISE 0855 is shown with its measured limit.

**RW Aurigae**
- A young variable star with known deep dimming events. A close pair that SPHEREx does not resolve `[TO CHECK separation]`.
- Weakness: near saturation `[TO CHECK]`. Cover: per-detector saturation report. Bands that saturate are excluded from the change spectrum.
- Weakness: three visits give three points in time. Cover: the change spectrum shows how the change depends on wavelength, which a three-point light curve cannot.
- Pass mark: brightness change between visits reported with errors per detector, compared with AAVSO where data exist.

**R Draconis**
- A Mira variable in a deep field with 222 dates. About two pulsation cycles covered `[ESTIMATE]`. Published period `[TO CHECK in AAVSO VSX]`.
- Weakness: heavily saturated (K about 0.6). Cover: brightness from the unsaturated outer part of the star's image with flagged pixels masked. Fallback: relative brightness in a ring around the core. If both fail, show the saturation honestly and overlay the AAVSO light curve.
- Pass mark: period from our light curve within 10% of the VSX period.

### 6.4 Weaknesses that apply to every target

| # | Weakness | Cover | How it is tested |
|---|---|---|---|
| 1 | Mixed bands in a blink cause false flicker | Like-with-like rule in the viewer. Default comparison is the same detector's visit stacks | Unit test: comparing two stacks with different band ranges is refused with the stated message |
| 2 | One-pixel motion is invisible | 4x upsampling, sub-pixel alignment, measured position marks, Difference view, Visits as colour | End-to-end test on Barnard's Star: marks differ by the expected shift within tolerance |
| 3 | Background changes between visits | Subtract the ZODI plane, then a local median | Median of blank sky in each stack within a set tolerance of zero |
| 4 | Bad pixels and cosmic rays | Zero weight for IRSA's rejected bits, clipped stacks | Injected single-frame spike does not survive a stack |
| 5 | Input formats | Accept decimal degrees, `08h55m10.831s -7d14m42.53s`, `08:55:10.831 -07:14:42.53`, `08 55 10.831 -07 14 42.53`, and names through CDS Sesame | Unit tests with the page's own strings for all five targets |
| 6 | Slow or failing archive | Prepared data for the five targets. Live mode streams frames as they arrive. Cached frame lists | Site passes end-to-end tests with the API off |
| 7 | Two releases in one field | Reader handles DR1 and QR3. Each frame carries its release and version | A field with both stacks without a step in brightness |
| 8 | Alignment drift | Fit a shift per frame against Gaia DR3 moved to the frame date | RMS 1.0″ or better, reported per field |
| 9 | Users misread what they see | Scale bar, north and east compass, date and band on every frame, plain reading first | Usability check with people who have no astronomy background, when such testers are available. Nothing waits on it |
| 10 | Phones | Panels become a bottom sheet. Viewer runs at 60 frames per second on a mid-range Android phone | Playwright mobile viewport run |
| 11 | Masking every flagged pixel removes the stars | Bit 21 marks pixels on a known source, bit 12 is informational. Only IRSA's rejected bits count as bad | Unit test: a bright unsaturated star keeps its pixels after masking |
| 12 | A faint detector 6 signal is spacecraft glow | Compare against IRSA's glow template and require a point-like shape that moves with the catalogue motion | WISE 0855 detection reported with its PSF fit quality and the template level at its position |
| 13 | Ghosts and streaks read as new sources | Ghost and streak flag bits, plus predicted crosstalk positions, send a signal to Artefact with the reason | A known ghost near Epsilon Indi A is rejected |

### 6.5 Parity with WiseView

The Resources tab names WiseView as the model. Read from the live page on 13 Nov 2026. Its default position is WISE 0855, and every setting lives in its URL.

| WiseView control | Ours |
|---|---|
| Right ascension and declination | Position box: any format, names, solar-system objects by name |
| Field of view in arcseconds | Field of view with a load estimate |
| Band: W1, W2, W1+W2 | Detector D1 to D6, band windows, any stack from the matrix |
| Sliding window in years | Visit selection in the observation matrix |
| Blink interval | Play speed |
| Zoom | Continuous zoom down to the pixel grid |
| Minimum and maximum pixel values, stretch linearity | Stretch controls with automatic limits |
| Invert pixel values | Invert |
| Maximize dynamic range | Automatic limits per view |
| Separate scan directions | Same-season play |
| Use only NEOWISE imagery, skip middle epochs, skip duplicate windows | Choose which visits play |
| Smooth by scan direction | No SPHEREx equivalent. Stacks are already per visit and detector |
| Border | Mark for the first visit in a loop |
| Gaia DR3 overlay | Gaia DR3 and CatWISE2020 at the frame date |
| Difference imaging | Difference between chosen visits |
| Shift and add with motion in RA and Dec | Follow motion |
| Synthetic object A and B, with subtraction | Test source in any band. Remove known for subtraction |
| Every setting in the URL | URL contract and embed mode |
| Links menu to other services | Other telescopes at this position, SIMBAD link |

What WiseView cannot have, and we add: six detectors and 102 bands, the observation matrix, spectra on the fly, features by molecule, Colour difference between detectors, Remove known, the prediction check, solar-system objects by name.

### 6.6 What "better than others" means, measurably

1. All five targets load in under 3 s on a 4G connection.
2. Each target has a measured number against a pass mark on the Proof panel.
3. Every one of the eight optional considerations has a visible control.
4. The site still works when IRSA is slow.
5. The page states our limits in numbers.

### 6.7 Reference values

Computed 13 Nov with astropy from published parallaxes. Use for the 3D neighbourhood and the tour copy.

| Object | Galactic l, b (deg) | Distance (pc) |
|---|---|---|
| Proxima Centauri | 313.9, -1.9 | 1.30 |
| Barnard's Star | 31.0, 14.1 | 1.83 |
| Luhman 16 AB | 285.2, 5.3 | 1.99 |
| WISE 0855-0714 | 235.0, 23.3 | 2.28 |
| Epsilon Indi B | 336.2, -48.1 | 3.64 |
| W1925 (L dwarf, the Galactic plane field) | 43.0, -4.3 | 11.2 |

2MASS observed from 1997 to 2001.

---

## 7. Architecture, contracts and API

### 7.1 Services

```
Browser (static single-page app)
  |-- site .................. Cloudflare Pages
  |-- data products ......... Hugging Face Dataset repo (static files, range requests)
  |-- live requests ......... API: FastAPI in a Hugging Face Space (Docker, CPU)
  |                              |-- IRSA TAP (frame lists, Gaia, WISE, 2MASS tables)
  |                              |-- S3 or IRSA static files (byte-range reads)
  |                              |-- CDS Sesame, VizieR, SIMBAD (names, catalogues)
  |                              |-- IMCCE SkyBoT, IRSA Moving Object Search Tool (solar-system objects)
  |                              '-- IRSA SIA and Canadian archive SIA (other telescopes at a position)
  '-- accounts, reviews ..... Supabase (Tier C only)

Pipeline (Python CLI `phantom`, same package the API imports)
  runs locally for showcase targets and fields, weekly through GitHub Actions
  writes data products and pushes them to the Dataset repo

Model training (ML lane, `ml/` scripts using `phantom.ml`)
  runs locally, writes versioned models and model cards
  models are published to the Dataset repo next to the data products
```

All services have a free tier that covers us. The Space sleeps after idle time, so a scheduled ping keeps it awake during judging week.

Rules:
1. The site works with the API off. Targets and fields load from static data products.
2. The API, the pipeline and model inference import the same package. One code path.
3. Every product carries `data_as_of`, `pipeline_version` and source file IDs. Every model output carries `model_version`.
4. The browser never calls IRSA, CDS or SkyBoT directly. IRSA TAP sends no CORS header.

### 7.2 Stack

**Engine and API.** Python 3.12, `uv`, numpy, scipy, astropy, astroquery, pyvo, photutils, reproject, healpy, fsspec with aiohttp, pyarrow, FastAPI, pydantic, httpx. Lint `ruff`. Tests `pytest`.

**ML.** scikit-learn, xgboost, shap. For tests against the first picks: lightgbm, catboost, optuna, mapie, and PyTorch for the small neural members. TabPFN only with version 2 weights (licence, section 9.11). Licences of each to be confirmed before adding (K28).

**Web.** Vite, React, TypeScript strict, Zustand for view state, TanStack Query for fetching, Tailwind with the tokens in section 10, Radix primitives for accessible controls, Aladin Lite v3 for the all-sky layer, our own WebGL2 frame viewer, uPlot for charts. Tests `vitest` and Playwright. Budget: initial script under 300 kB gzipped without Aladin.

**Why a WebGL2 viewer of our own.** Frames arrive as raw calibrated values. Stretch, Difference, Stack, Visits as colour and pixel readout are computed on the graphics card with no new download.

### 7.3 Data products

All paths are relative to the Dataset repo root. JSON Schemas for each live in `contracts/` and are written in task T02 from this section. Field names here are final.

**Field manifest** `fields/<id>/manifest.json`

```
{ "field_id", "title", "center": {"ra","dec"}, "size_deg",
  "grid": {"nx","ny","pixscale_arcsec": 3.075, "projection":"TAN", "crval":[ra,dec], "crpix":[x,y]},
  "data_as_of", "pipeline_version", "collections": [...],
  "frames": [ {"id","mjd","date","visit","det","band","wave_um","bw_um","release","version",
               "flag_frac","sat_frac","sky","scale","offset","pack","index","fwhm_arcsec","shift_arcsec":[dx,dy],"src"} ],
  "stacks": [ {"id","det","visit","n","mjd_mid","wave_min","wave_max","scale","offset","pack","index"} ],
  "targets": [ {"name","source_id","ra_at":[{"mjd","ra","dec"}],"note"} ] }
```

`det` is 1 to 6. `band` is 1 to 102. `visit` is 1-based in date order. `src` is the archive file ID.

**Frame pack** `fields/<id>/<pack>.bin`

Unsigned 16-bit little-endian images on the field grid. Value = (flux - offset) / scale. 0 means no data. A parallel 8-bit quality plane: 0 good, 1 flagged, 2 overflow, 3 outside the frame, 4 ghost. Mapping in section 8, stage 4. The grid is 3.075″, half a SPHEREx pixel.

**Sources** `fields/<id>/sources.json`

```
{ "id","ra","dec","epoch","pmra","pmdec","plx",
  "ids": {"gaia","twomass","catwise","simbad","vsx","sso"}, "otype",
  "mags": {"G","J","H","Ks","W1","W2"},
  "status": "known|unclassified|uncatalogued",
  "sx": {"n_bands","snr","blend","sat"},
  "features": {"ch4","h2o_ice","co2","co","pah","h_lines","slope_short","slope_long"},
  "motion": {"mu_ra","mu_dec","err","n_visits"},
  "var": {"chi2r","amp","edge_sigma"},
  "ml": {"p_real","class","p_class","word","template","template_agrees","novelty_pct",
         "deciding_bands":[...],"deciding_measured": true,"model_version"},
  "signals": ["mover","mismatch","variable"] }
```

`blend` is the share of fitted light in the source's footprint that belongs to neighbours, 0 to 1. `word` is the confidence word from section 5.5. Each feature holds `{ "value","err" }`.

The ML lane extends `ml` with: `p_class_features` (molecule readings alone), `p_class_spectrum` (spectrum alone), `p_class_all` (all data), `feature_contrib` (how far each feature moved the result, toward or away from the top type), `conformal_set`, `p_range` (resampled 16th to 84th percentile), `expert_votes`, `refused` (reason when no type is given), and per-feature `origin`. Add these to the contract in T02 or with a line in `docs/decisions.md`.

**Spectrum** `fields/<id>/spectra/<source>.json`

Per measurement: `wave_um, band, flux_ujy, err, mjd, det, flag, frame`. Plus the binned 102-band spectrum per visit and overall, each with `flux_ujy, err, n`.

**Cases** `fields/<id>/cases.json`

```
[ { "id":"PW-0001","source_id","kind":"mover|variable|mismatch","state",
    "created","reporter": "pipeline|<member id>",
    "checks": {"visits_seen","flags_clean","bright_star_sep_arcsec","catalogue_match",
               "known_sso","history": [{"survey","year","seen": true}] , "p_real"},
    "priority": {"value","signal","real","unexplained"},
    "prediction": {"locked_at","for_visit","mjd_window":[a,b],"ra","dec","err_arcsec",
                   "stay_ra","stay_dec","status":"pending|held|failed|not_observed",
                   "measured": {"ra","dec","err_arcsec","frames":[...]}, "settled_at"},
    "route": "backyard_worlds|aavso_vsx|mpc|none" } ]
```

`stay_ra, stay_dec` is where the source would be with no motion. A prediction holds only when the measured position agrees with the predicted one and disagrees with the stay position (section 8, stage 14).

**Searched depth** `fields/<id>/searched.json`

```
{ "field_id","method_version","data_as_of",
  "injections": {"n","bins":[{"ab_mag","speed_arcsec_yr","recovered","injected"}]},
  "cells": [ {"nside","ipix","n_visits","depth_ab_50","depth_ab_90","speed_range":[lo,hi]} ] }
```

**Proof** `proof/report.json`

One entry per test: `id, target, what, pass_mark, measured, unit, passed, run_at, pipeline_version, inputs`. See section 13.

**Models** `models/<name>/<version>/`

Model file, `model_card.json` (training data with label sources and grades, splits, scores per brightness bin, calibration error, conformal coverage, date), and the feature list. The site shows the model card on click.

### 7.4 URL contract

```
/?ra=<deg>&dec=<deg>&fov=<deg>&mode=play|diff|stack|colour|follow|detdiff
  &det=1..6&visit=<n>|all&overlay=gaia,catwise,flags&src=<source id>
  &panel=identity|search|signals|case|proof&case=PW-0001&embed=1
/t/<target id>          named targets: barnard, epsindib, wise0855, rwaur, rdra, w1925, 3i-atlas
```

Every part of the view is in the URL. Back and forward work. `embed=1` hides the top bar and panels and leaves the viewer and its controls. Never put personal data in a URL.

### 7.5 API

All GET. JSON. Cached by request. Inputs validated. Outbound calls only to the allowlist.

| Endpoint | Returns |
|---|---|
| `/health`, `/version` | status, pipeline version, data_as_of |
| `/resolve?name=` | position, catalogue epoch, proper motion, parallax, identifiers |
| `/frames?ra=&dec=&fov=` | frame list at once, then frames as server-sent events while they are cut |
| `/catalog?ra=&dec=&r=&mjd=` | reference sources with positions at that date |
| `/spectrum?ra=&dec=&pmra=&pmdec=` | spectrum at a position from cached cutouts. With motion given, measured along the track |
| `/sso?ra=&dec=&r=&mjd=` | known solar-system objects in the field at that date |
| `/track?name=` | for a named solar-system object: SPHEREx frames that contain it and its position in each |
| `/elsewhere?ra=&dec=` | images of the position from other missions, from IRSA and the Canadian archive |
| `/identify?ra=&dec=` (Tier B) | readings, molecule readings and the type estimate for one source, same code as the pipeline |

Before writing `/frames`, list the real columns: query `TAP_SCHEMA.columns` for the `spherex` tables. Do not guess column names.

### 7.6 Weekly update

A GitHub Actions job runs the frame-list query for every target and field. If new frames exist it cuts them, updates stacks and manifests, settles any prediction whose window now has data, re-runs the proof script, and pushes. A jump in the share of unclassified sources against the previous week blocks publishing and writes a report of the jump. Publishing resumes when the cause is logged in `docs/decisions.md`.

### 7.7 Security

- API: input validation, fixed host allowlist, rate limit per address, no user-supplied URLs.
- Supabase (Tier C): row-level security on every table. A member reads their own email only. Display names are public. Reviews are hidden from other members until the reviewer submits.
- Bot check on sign-up and on Report.
- No secrets in the repo. `.env.example` lists names only. Tokens live in GitHub secrets.

---

## 8. Methods, stage by stage

Each stage names its inputs, its output and its check. Where an archive detail is not confirmed, the stage says `[TO CHECK]` and the first step is to confirm it. The "Additions from the resource pages" at the end refine these stages, and win where they differ.

### Stage 1. Frame list

1. Start from the query in the IRSA cutouts tutorial: `spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid`, with `CONTAINS(POINT('ICRS', ra, dec), p.poly) = 1`, selecting `a.uri`, `p.time_bounds_lower` and `p.energy_bandpassname` (values like `SPHEREx-D2`). Confirm the other columns we need (exposure ID, release, version) from `TAP_SCHEMA.columns` and record them (K1). The `spherex` schema holds `artifact`, `obscore`, `observation`, `plane`, `provenance_input` `[VERIFIED 14 Nov]`.
2. Select every frame whose footprint contains the position. Searches return DR1 and QR3. Include the deep-survey frames. Keep one file per exposure and record its release and version. SIA lags new data by about a day, so use TAP for the frame list.
3. Group dates into visits: a gap over 30 days starts a new visit.
4. Cache the result per target. Output feeds `manifest.frames`.

Check: frame counts for the five targets match section 6.2 or exceed them.

### Stage 2. Cutouts by byte range

1. Open the file over HTTP with range support (astropy with fsspec). Try S3 first: bucket `nasa-irsa-spherex`, region `us-east-1`, anonymous, prefixes `dr1`, `qr3`, `qr2` `[TO CHECK key layout by listing]`. Fall back to the IRSA file URL from `a.uri` `[VERIFIED range support]`. Last resort: the IRSA cutout call.
2. Read the IMAGE header. Convert the field box to pixel rows and columns through the image WCS including distortion terms.
3. Read only those rows from IMAGE, FLAGS, VARIANCE and ZODI.
4. Wavelength and bandwidth per cutout pixel come from `CWAVE` and `CBAND` (addition 1).
5. Run 16 readers in parallel with retries and a local cache keyed by file ID and box.

Check: a 0.2° cutout of one file transfers under 1 MB and matches the same region cut from a fully downloaded file, pixel for pixel.

### Stage 3. Alignment

For each frame, fit a shift against Gaia DR3 sources moved to the frame date. Exclude stars with flagged or overflow pixels in their core. Store `shift_arcsec`.

Check: RMS residual 1.0″ or better per field.

### Stage 4. Display products

1. Subtract ZODI, then a local median background.
2. Resample to the field grid at 3.075″.
3. Scale each frame to 16-bit with stored `scale` and `offset`. Write the quality plane from FLAGS, following the list IRSA uses to reject pixels in its own all-sky cubes:
   - Flagged (1): bits 0, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 25, 26, 27, 28, 29. Zero weight everywhere.
   - Overflow (2): bit 1. Kept in stacks, as IRSA keeps it. Left out of position fits on bright stars. Reported per target.
   - Ghost (4): bits 22 and 24. Kept in stacks. A signal on these pixels exits as Artefact.
   - Good (0): everything else. Bit 21 marks a pixel on a known source and must never be masked, or every star disappears.
   In this file "flagged" means quality value 1.
4. **Visit stacks.** For each detector and visit, average the frames with flagged pixels at zero weight and outliers clipped. Store the wavelength range covered.

**Like-with-like rule.** A stack is comparable with another stack only when detector and band range match. Play, Difference and Visits as colour operate on comparable stacks. The viewer refuses other pairs with the message in section 5.6. Single frames can be played in date order only inside one band window (same detector, band within ±1). Colour difference is the one labelled exception (addition 11).

Check: a star with a steep spectrum shows no brightness change between two visit stacks of the same detector beyond its error.

### Stage 5. Positions at the frame date

Any catalogue position is moved to the frame's date with proper motion and parallax before overlay, match or prediction. A name that resolves to a source with proper motion gives two marks: the entered or catalogue position with its epoch, and the present position.

### Stage 6. Measured motion

1. In each comparable visit stack, fit the source position with the detector's PSF, using only pixels that are neither flagged nor overflowed.
2. Fit a straight line through the visit positions for motion in RA and Dec with errors. With four or more visits add the parallax term.
3. Report against the catalogue value.

### Stage 7. Spectrum on the fly

1. For a position, measure brightness in every frame that covers it: PSF-weighted sum on background-subtracted pixels, error from VARIANCE.
2. Each measurement carries wavelength, band, date, detector, flag and frame ID.
3. Bin to the 102 bands per visit and overall.
4. **Along a track.** When motion is known or entered, measure at the predicted position for each frame's date. This keeps a mover's spectrum from smearing.

IMAGE is in MJy/sr. Convert to microjansky with the pixel solid angle map.

In processed fields the spectrum comes from the joint fit (stage 9) and is instant.

**Quick look anywhere (optional, after Tier B's core).** A small aperture read from the all-sky cube tile that covers a position gives a spectrum of any fixed source without touching single frames. Tiles are about 300 MB, so read only the needed bytes `[TO CHECK that the tile layout allows it]`. The cube averages over time, so movers and variables are smeared, and IRSA labels such spectra as for visualization only. Show it with the label `Quick look, DR1 mosaic` and no error bars unless we compute them.

### Stage 8. Light curve and change spectrum

- Light curve: brightness against date inside one band window. For R Draconis use the unsaturated outer part of the star's image.
- Change spectrum: ratio of the binned spectrum of visit B to visit A, band by band, with errors. Bands that saturate in either visit are left out and listed.
- Period: Lomb-Scargle on the band window with the best coverage. Report the peak and its width.

### Stage 9. Reference scene and joint fit (Remove known)

1. Merge Gaia DR3, 2MASS and CatWISE2020 positions. Add Spitzer GLIMPSE in the plane field. Move each to the frame date.
2. For each frame solve `min || W (A f + b - d) ||`. Column j of A is the PSF of source j at its sub-pixel position. `f` is the brightness vector, `b` a local background, `d` the data, `W` the weights (zero for flagged and overflow pixels). Sparse least squares with a small ridge term.
3. Outputs per frame: brightness and error per source, and the residual image (data minus model).
4. Blend share per source: the part of the fitted light in its footprint that belongs to neighbours.

We write this solver ourselves. The Tractor (GPL-2) and tractorjax-spherex (GPL-3) are not used. The official SPHEREx photometry uses Tractor forced photometry with positions fixed, a local background fit, all sources in the cutout fitted together, and a 3% systematic added in quadrature. Our solver follows the same idea.

Check: synthetic Ks from our spectra against 2MASS for isolated stars with 9 < Ks < 13. Median offset 5% or less, scatter 10% or less. In W1925, scatter 20% or less for blend under 0.3.

### Stage 10. Features

Windows and the molecule reading method are in section 9.3. From each binned spectrum compute, with errors: methane dip near 3.3 µm, water ice near 3.05 µm, CO2 near 4.26 µm, CO near 4.67 µm, the 3.3 µm emission feature, hydrogen lines near 1.875 and 4.05 µm, and two slopes (short and long wavelengths). Each feature is the band value against a line through its neighbours. Search by light presets are thresholds on these.

The methane dip and the 3.3 µm emission feature sit at the same wavelength with opposite sign. The preset names say "dip" or "glow".

### Stage 11. Detectors

| ID | Finds | Method |
|---|---|---|
| mover | sources that change position | detections in residual visit stacks that link across visits, or within a visit for fast solar-system objects |
| mismatch | spectrum disagrees with catalogue type | catalogue type against the classifier and template result, both confident |
| variable | brightness changes | reduced chi-square of brightness against date inside band windows |
| variable (edge check) | change within one visit | the last band of one detector and the first band of the next sit close in wavelength and are measured at different times. Flag a mismatch beyond 3σ after correcting for the local spectral slope and after checking the two detectors agree on non-variable stars. First confirm from `CWAVE` how close the edge bands are (K12). If further apart than half a bandwidth, cut this detector |

### Stage 12. Machine checks

A signal becomes a case only when all pass:
1. Seen in two or more independent frames, and for movers in two or more visits.
2. No flagged or ghost pixels under the source in the frames that detect it. Far enough from bright stars and frame edges. Not on a satellite streak. Not at a predicted crosstalk position (addition 7).
3. No match in Gaia DR3, 2MASS, CatWISE2020, SIMBAD at the frame date (for the Uncatalogued route).
4. No known solar-system object at the frame time. SkyBoT first, IRSA's Moving Object Search Tool with `catalog=spherex` second (it covers SPHEREx, K14).
5. `p_real` of 0.9 or more from model M1.
6. History: for a mover, look at the positions its motion predicts in 2MASS (1997 to 2001) and WISE-era images (2010 to 2024) `[TO CHECK source of epoch images, K7]`. Record seen or not seen per survey.

Priority = signal × real × unexplained, each from 0 to 1, each stored. `signal` is strength, `real` is `p_real`, `unexplained` is how poorly known sources and artefacts account for it.

### Stage 13. Models

The full design is in section 9. Summary:
- **M1, real or artefact.** XGBoost. Real examples are test sources injected into real residual frames with the SPHEREx PSF, plus 5% of catalogue stars left out of the reference scene on purpose. Artefact examples are single-frame residuals, residuals beside bright stars, on flagged pixels or at edges, on ghost and streak flags. Threshold where 1% of artefacts pass.
- **Type model (called M2 in older docs).** Readings, experts, and a calibrated combiner. Three results stored per source: molecule readings alone, spectrum alone, and all data.
- **Molecule readings.** Feature strength with error for every source. For ice sightlines, each molecule as a percentage of water ice. No full composition percentages.
- **Unusual objects (called M3 in older docs).** Isolation forest plus template residual plus empty conformal set.
- **Deciding bands.** For the top two types, rank bands by the difference between their templates divided by the measurement error at that band. Store the top bands and whether each is measured.
- **Cap.** If the best template disagrees with the trees, shown confidence is capped at 50%.

Release gate: section 9.9, plus M1 recall 0.90 at the 1% artefact threshold. A version that fails stays unpublished and the panel shows readings with no type.

### Stage 14. Prediction check

**For a case.** When a mover case is created, compute its position for the next visit window from the fitted motion, with an error radius. Store it with `locked_at`. Store the stay position too. The record is never edited.

**Settling.** When frames in the window exist, measure the position in the comparable visit stack.
- `held`: measured position within 2σ of predicted, and more than 3σ from the stay position.
- `failed`: detected, and inconsistent with the prediction.
- `not_observed`: no detection above 5σ at either position.
- `pending`: no frames yet.

**Retro test on the test targets.** For each mover with three or more usable visits, hide the last visit, fit motion from the earlier ones, predict, then reveal and measure. For WISE 0855, visit 1 has 3 frames in D6, so the test predicts visits 2 and 3 from the catalogue position, motion and parallax.

A prediction counts only if it beats "it stayed where it was". Report both separations.

### Stage 15. Searched depth

1. Inject test sources into real frames of a field over a grid of brightness and motion.
2. Run the mover detector and checks unchanged.
3. Record the recovered share per bin. `depth_ab_90` is the faintest brightness recovered at 90% or more.
4. Publish per field as measured. The Planet X statement on the Proof panel is the faintest mover recovered, with the motion range tested.

A distant planet shifts by hundreds of arcseconds between visits because Earth moves 2 AU in six months. At 500 AU the shift is about 800″, 130 px `[ESTIMATE]`. Small fields cannot contain both positions. State the field size limit next to the depth. A distant planet is a fast apparent mover through parallax, never a "very slow mover".

### Stage 16. Follow motion

Shift each comparable stack by minus the chosen motion times its time offset, then average. Used in the viewer with an entered motion, and by the mover detector over a grid of motions when time allows.

### Stage 17. Publish

Write manifest, packs, sources, spectra, cases, searched depth, models. Validate each against its schema. Push to the Dataset repo.

### Additions from the resource pages (13 Nov)

These refine the stages above. Where they differ, these win.

1. **Wavelength for science.** Use `CWAVE` and `CBAND` from the `spectral_wcs` calibration file of each detector. They are fixed per detector pixel, so load six maps once. The WCS-WAVE table inside each image is good to about 1 nm and meant for display.
2. **Units.** Convert MJy/sr to microjansky with the `solid_angle_pixel_map` of the detector.
3. **PSF.** Read `VERSION` from the PRIMARY header. At 7.0 or higher use the EPSF extension in the file. Below that, load the `epsf` calibration file for the detector. Pick the zone nearest the source in parent-image pixels (`CRPIX1A`, `CRPIX2A` in cutouts, then nearest zone by `XCENTER`, `YCENTER`). Render to image pixels at the source's sub-pixel position and normalise. ePSF: 33 × 33 cells, 5 times oversampled, 21 × 21 zones for D1, D2, D4, D5, D6 and 11 × 41 for D3. IRSA noted on 13 Mar 2026 that the PSF extension header describes the zones wrongly in current files, while the PSF planes are fine. Follow IRSA's documentation for the grid.
4. **Collections.** Frame lists must include deep-survey frames. R Draconis depends on them.
5. **Endpoints.** TAP, 5 minute limit for sync, one geometric constraint per query. SIA with `RESPONSEFORMAT=JSON` as a second route.
6. **Paths.** `level2/[Planning Period]/l2b-v[Version]-[Processing Date]/[Detector]/` under `dr1`, `qr3`, `qr2`, on IRSA and in S3.
7. **Ghost check.** Ghost bits 22 and 24 in FLAGS, plus the `xtalk_class` parameter files for crosstalk images about 32 rows away or at multiples of 64 pixels. A signal at such a position exits as Artefact with that reason.
8. **Emission not from the sky.** Templates exist for helium (detectors 1, 2), aurora (detector 1) and spacecraft glow (detector 5 in the data products page, detectors 5 and 6 near 4.5 µm in the Explanatory Supplement). Before claiming a faint detection in detectors 5 or 6, including WISE 0855, check the glow template level at that position and require a point-like shape.
9. **Solar-system objects by name.** `/resolve` tries the Moving Object Search Tool with `catalog=spherex` when a name is a solar-system object. It returns the frames and the object's position in each. The viewer then uses Follow motion along that path, and `/spectrum` measures along it.
10. **Comet 3I/ATLAS.** IRSA's table (`obscore_3I_Atlas.vot`) gives the comet position per frame (`comet_ra`, `comet_dec`). Observed August and December 2025. Pack it as named target `3i-atlas`. The comet is extended and faint at many wavelengths, so use aperture sums and say so. Published SPHEREx result: carbon dioxide production about 9.4 × 10^26 molecules per second, upper limits on water and CO (arXiv 2508.15469).
11. **Colour difference.** Detector A stack minus detector B stack on the field grid, each scaled to flux. The SPHEREx team's method for red sources (Source Discovery Tool). A deliberate exception to the like-with-like rule, labelled as a colour image.
12. **Same-season play.** Tag each visit with its season from the date. Playing one season removes parallax.
13. **Test source.** Render the ePSF at a chosen position, brightness and motion into the displayed frames. Same code as the injection test in stage 15.
14. **Other telescopes.** For a position, query IRSA SIA and the Canadian archive SIA. Return mission, instrument, date, band and a link. For mover cases with orbital elements, the Moving Object Search Tool covers 2MASS, WISE, NEOWISE and ZTF.
15. **Name lookup fallback.** CDS Sesame first, then SIMBAD TAP, then a built-in table for the named targets with their catalogue source. IRSA's own lookup was partly down on 13 Nov.
16. **Feature map.** One band plane minus the median of its neighbours, as in the IRSA mosaic tutorial.
17. **Catalogues on IRSA TAP.** Gaia DR3, CatWISE2020, AllWISE, NEOWISE, 2MASS, unWISE, ZTF and Euclid tables sit on the same TAP service as the SPHEREx frames `[VERIFIED 14 Nov]`. Table names in `DATA-LINKS.md` section 7.3. Use them for the reference scene, overlays and survey features, so one service covers frames and catalogues.

---

## 9. Machine learning

Written 13 Nov after reading the resource pages, the Explanatory Supplement v2.1 and the 2026 papers that use real SPHEREx spectra. Updated 14 Nov with the dataset checks. Every paper and link is in `DATA-LINKS.md` sections 7 and 9.

### 9.1 Short answer

1. The product goal stands: read a spectrum, report what it contains, combine it with other surveys, and state the most likely object type with a confidence. The tool reports. People decide.
2. One part of the goal changed. A full composition such as "40% CO2, 20% NO" is a quantity SPHEREx data do not contain. Section 9.3 explains why and gives the readings that are measurable. One real percentage survives: for ices, each molecule as a percentage of water ice.
3. Published results on SPHEREx spectra show accuracy is limited first by signal and blending, second by label quality, third by which other surveys are added. Model size comes fourth. In the one study that compared them, a learned spectrum encoder changed star purity by about one point, and adding aligned image data changed it by about 25 points (fact 9).
4. So the heavy part of our system is the fusion: several independent experts, each reading one kind of evidence, joined by a calibrated combiner.
5. The main model is XGBoost. Section 9.11 names the library for every job, explains each in plain words, and lists the alternatives worth testing.
6. Labelled SPHEREx spectra exist today. The largest set is the SPIFF library of ultracool dwarfs with 47 subtype templates. For every other type, training spectra come from the SPHEREx all-sky cube in chosen fields (section 9.4).
7. Molecule readings come first (section 3.11). The spectrum is decoded into molecule features, a model trained on those features alone gives the first type estimate, and every estimate is explained in features. The full spectrum and the other surveys are added step by step, and the gain from each step is measured on our test split and published (section 9.11).

### 9.2 Facts that set the limits

| # | Fact | Source |
|---|---|---|
| 1 | A source's spectrum is a set of single-exposure measurements, each at its own wavelength, taken over days to weeks. The 102 bands are a binning of these. Exposures of one target can span 5 to 40 days. A target gets at least 408 measurements over four surveys | Supplement, Melnick 2026 |
| 2 | Resolving power is 35 to 41 below 3.8 µm and 112 to 128 from 3.8 to 5.0 µm | Supplement |
| 3 | Official photometry is forced PSF photometry at a fixed position with a 3% systematic error added. Absolute calibration from about 54,000 measurements of 17 CALSPEC stars, under 1% for most channels. Fine astrometry RMS under 0.3″. Independent teams use larger floors: 3% visit to visit with calibration within 3% (bands 1 to 4) and 5% (bands 5 and 6), or an 8% floor on absolute flux | Supplement, Rustamkulov 2026, Gagné 2026 |
| 4 | Depth per exposure at 5σ is about 19.5 AB below 3.8 µm and 17.5 to 18.5 AB above. Signal to noise per band reaches about 10 at W2 = 14.0. The ice team requires W2 brighter than 11.96 to reach 50 per band in bands 5 and 6 | Rustamkulov 2026, Gagné 2026, Melnick 2026 |
| 5 | Pixels are 6.15″, so neighbours blend. Of 1,327 known brown dwarfs with W2 ≤ 14.0, 81.2% gave a clean match, 8.6% were typed slightly early, and 7.6% were low quality, mostly from background sources and blends. Some percentages in that paper do not add up, so treat them as approximate | Gagné 2026 |
| 6 | Template matching recovers the spectral type of ultracool dwarfs with a median absolute deviation of 1.5 subtypes | Gagné 2026 |
| 7 | Atmosphere model grids fit real brown dwarf spectra poorly. Reduced χ² is 10 or more for most high-signal spectra. Fitted gravity for one L1 dwarf spans three orders of magnitude across grids. Fitted temperature moves by 100 to 200 K between grids. A second team finds gravity off by a median 1.05 dex between 1,700 and 2,500 K | Rustamkulov 2026, SUDA 2026 |
| 8 | The SPHEREx ice team does not split a spectrum into ice mixtures. It measures the integrated optical depth of each feature. Its reasons: mixture fits are not unique, features beyond 5 µm are often needed, grain assumptions add large uncertainty, and decomposition becomes impractical beyond a few species. Narrow CO and CO2 features read low at this resolution and need a correction | Melnick 2026 |
| 9 | Star against galaxy, on simulated SPHEREx spectra, stellar completeness and purity. Boosted trees on the 102 normalised bands: 0.977 and 0.682. Trees on a learned spectrum embedding: 0.973 and 0.692. Trees on an image embedding aligned with the spectrum: 0.983 and 0.931 | arXiv 2607.20797 |
| 10 | Galaxy, narrow-line active galaxy, broad-line active galaxy, on real spectra with 14 empirical templates (7 galaxy, 7 AGN, weighted NMF, trained on 2,777 galaxies and 1,064 AGNs in the NEP field): accuracy 81.3% in the deep field and 72.9% at all-sky depth. Redshift within 0.01 for about 93% in the deep field | arXiv 2609.02167 |
| 11 | About 22% of the ice target list is flagged variable from NEOWISE and Gaia. A spectrum built from exposures on different dates can show false features for a variable source | Melnick 2026 |
| 12 | The main infrared band of nitric oxide (NO) is at 5.3 µm, outside the SPHEREx range of 0.75 to 5.0 µm. Its overtone near 2.7 µm is about 27 times weaker (2.8 against 76 in the same units). Water also absorbs near 2.7 µm `[FROM MEMORY]` | Breeze and Ferriso 1964 |
| 13 | The official High Reliability Source Catalog of SPHEREx spectra arrives 8 months after the end of survey 3, so it is not available this weekend | SPHEREx data products page |

### 9.3 Molecules: what can be measured

A SPHEREx spectrum shows a molecule as a dip or a bump at a known wavelength. The size of that feature is measurable with an error. Turning feature sizes into a complete percentage breakdown fails for four reasons.

1. Most of the mass of a star, brown dwarf or gas cloud is hydrogen and helium, which leave no usable feature in this range. The molecules we see are trace species.
2. Many molecules have no band between 0.75 and 5.0 µm. NO is one (fact 12).
3. Going from feature size to amount needs a physical model. For brown dwarfs the models misfit the data (fact 7). For ices the mixture is not unique (fact 8).
4. At a resolving power of 35 to 130, narrow features are diluted and neighbouring features merge.

The SPHEREx teams face the same limits and report feature strengths. We do the same, and label every value with its origin.

**What we report, by kind of object**

| Kind of object | Features in range | Reading we show | Origin label |
|---|---|---|---|
| Ice in front of a star or around a young star | H2O 3.05 µm, CO2 4.27, 13CO2 4.38, XCN 4.62, CO 4.67, OCS 4.91 | Integrated optical depth with error per feature. Column density using a stated laboratory band strength. Each molecule as a percentage of water ice | Measured for depth. Estimated for column density and percentage |
| Brown dwarf or cool star | CH4 3.20 to 3.65 µm, CO2 4.18 to 4.35, CO 4.55 to 4.80, each against the 3.70 to 4.14 window. Water bands | Index in magnitudes with error. Spectral type from templates. Temperature only as a range taken from the type | Measured for index. Estimated for type and temperature |
| Comet coma | CO2 gas near 4.26 µm, water near 2.7, CO near 4.67 | Band flux above the dust continuum with error, per date. Production rate is a stretch item and needs a coma model | Measured |
| Galaxy or nebula | 3.28 µm emission from carbon-ring molecules (PAH), hydrogen lines near 1.875 and 4.05 µm | Line or band flux with error. Redshift when lines allow | Measured |
| Asteroid | Broad band near 3 µm from hydrated minerals `[FROM MEMORY]` | Band depth against the continuum. Rotation changes brightness between exposures, so correct with the light curve first | Measured |

**The percentage we can show.** For ice sightlines: `N(molecule) / N(H2O) × 100`, with `N = integrated optical depth / band strength`. Ice astronomers publish abundances this way. The interface line reads, for example, `Carbon dioxide ice: [value]% of water ice, ± [error], Estimated`. Band strengths come from laboratory work cited by the ice team (Gibb et al. 2004) `[TO CHECK values, K23]`. Apply the low-resolution correction to CO and CO2 or state that it is not applied. For every other kind of object the panel shows feature strength with error and a detection significance, and no composition percentage.

**Method for molecule readings**

1. Continuum: fit a third-degree polynomial (`numpy.polyfit`) through the clean windows the ice team uses, 2.53 to 2.72, 3.80 to 4.02 and 4.90 to 5.01 µm, for ice sightlines. For brown dwarfs use the 3.70 to 4.14 µm window as the reference, as in Rustamkulov 2026.
2. Optional upgrade: Gaussian-process regression for the continuum (`sklearn.gaussian_process.GaussianProcessRegressor`), which the ice team uses as one of four fitters. It returns an error on the continuum.
3. Optical depth per band: `τ = ln(continuum / flux)`. Integrate over the feature in wavenumber.
4. Error: redraw the spectrum 200 times within its errors and repeat steps 1 to 3. Report the median and the 16th to 84th percentile range.
5. Refuse the reading when the source is flagged variable, when the blend share is above 0.3, or when fewer than three bands cover the feature. Say which reason applied.

### 9.4 Object types, labels and training data

**Types.** Two levels. Level 1 always runs. Level 2 runs only where labelled spectra exist.

| Level 1 | Level 2 |
|---|---|
| Star | temperature class and giant or dwarf, from DESI and Gaia where available |
| Ultracool dwarf (brown dwarf or very low-mass star) | subtype L0 to Y1, plus young and subdwarf flags |
| Young star with ice or dust | none yet |
| Evolved giant star | none yet |
| Galaxy | none yet |
| Active galaxy or quasar | narrow-line, broad-line |
| Reddened background star | none. Kept as its own class because it is the main thing that fakes a brown dwarf |
| Solar-system object | name from ephemeris. No model needed |
| Unclassified | shown when no type reaches 50% |

Artefact is decided earlier by M1 and the machine checks, so the type model only sees signals that passed.

**Labels.** Gold means a person or a spectrograph set the label. Silver means another model set it.

| Type | Gold labels (testing) | Silver labels (half weight in training) |
|---|---|---|
| Ultracool dwarf + subtype | SPIFF known dwarfs (2,050 sources, literature types). UltracoolSheet v2.1.0 (4,000+ ultracool dwarfs, spectral types, parallaxes, young and subdwarf flags, CC BY 4.0) | SPIFF new dwarfs, candidates and photometric candidates |
| Normal star + temperature and gravity | DESI DR1 `SPECTYPE = STAR` (4,866,890 entries in the full redshift catalogue). DESI Milky Way Survey catalogue (6,372,607 rows, Teff, logg, [Fe/H]) | Gaia DR3 `gaia_dr3_astrophys_param` |
| Evolved giant | DESI MWS stars with low logg. SIMBAD `otype` | SPLICES `STYPE_ML`. Gaia DR3 `vari_long_period_variable` and `vari_classifier_result` with class LPV |
| Young star | SPLICES `YSO_PUB` (published). SIMBAD `otype` | SPLICES `STYPE_ML` |
| Galaxy | DESI `SPECTYPE = GALAXY` (21,696,490). Euclid DR1 deep spectroscopic classification (NEP field) | Gaia DR3 `galaxy_candidates`. 2MASS `fp_xsc` for extended sources |
| Quasar or AGN | DESI `SPECTYPE = QSO` (1,862,583). DESI `agngal` catalogue: broad line is bit 12 (`BROAD_LINE`) of `AGN_MASKBITS` | Gaia DR3 `qso_candidates`, `classprob_dsc_combmod_quasar` |
| Reddened background star | SPLICES main-sequence stars with high `Av` | |
| Variable star class | | Gaia DR3 `vari_classifier_result`, also in SPLICES as `VarClassGaia` |
| Solar-system object | Moving Object Search Tool at the frame time (exact) | |

Rules:
- The test set is gold only.
- Silver labels train at half weight and never count toward a pass mark.
- Record the label source per row so a result can be traced.
- DESI rows: keep only `ZWARN = 0`.
- SUDA (1,675 ultracool dwarfs with model parameters) does not state whether its atlas or templates are public. Do not plan on it.
- The galaxy and AGN NMF templates (fact 10): public status unknown `[TO CHECK, K19]`.

**Where training spectra come from**

| Route | What it gives | Limits | Use |
|---|---|---|---|
| SPIFF library (Zenodo, version QR2-2026-04-24, CC BY 4.0, 6.7 GB in total) | Reduced SPHEREx spectra of ultracool dwarfs and candidates, binned and unbinned CSV, 47 subtype templates (raw and hybrid), machine-readable tables | Built from QR2. Column layout of the CSVs not stated on the page | Ultracool dwarf training and the template expert. Download the binned CSVs, templates and tables, about 57 MB |
| All-sky cube tiles (DR1, order 5, 3.36 deg² each, about 300 MB each) | A spectrum for every labelled source inside a tile, by small aperture | IRSA labels cube spectra as display grade. Time-averaged, so movers and variables smear | Bulk training spectra for every other type. Calibrate first (check below) |
| IRSA Spectrophotometry Tool | Spectra by the official method (Tractor forced photometry, position fixed, local 15-pixel background, position-dependent PSF, µJy) | 20 positions per upload, two jobs at once, no API, at least 5 minutes per job, about 2.5 hours per 5,700 images, needs a logged-in browser session, results kept 14 days, Tuesday maintenance can stop jobs | Optional extra check when its spectra are available. Nothing depends on it |
| Our own extraction (stages 7 and 9) | Science-grade spectra with our errors | Hundreds of cutouts per source | The test targets and the processed fields |

**Which cube tiles to pull** (tile numbers and links in `DATA-LINKS.md` section 6):
- North Ecliptic Pole: SPHEREx's deepest data. Overlaps Euclid Deep Field North. Galaxies, quasars, stars.
- One star-forming cloud dense in SPLICES sources (Taurus, the L1495 area, as a first guess, confirmed by counting SPLICES rows): young stars, ices, reddened background stars, evolved giants.
- One high-latitude field dense in DESI spectra: galaxies, quasars, normal stars. Pick it with the DESI tile count query in `DATA-LINKS.md` section 11.
- The five test-target fields.

**Two checks before training**
1. Cube against frames: pick 20 bright isolated stars in one cube tile, extract their spectra from single frames with our own stage 7 code, and compare with the cube spectra. If any band is off by more than 10%, correct it band by band (K22). If Spectrophotometry Tool spectra of the same stars exist, add them as a third comparison.
2. QR2 against DR1: SPIFF spectra come from QR2 and our data is DR1. Compare on sources in both, using `l3_flux_corrections`, before mixing them.

### 9.5 Every option, stage by stage

Verdicts: **Build** is in the weekend plan. **If time** is a stretch task. **Later** is after the hackathon. **Skip** has a stated reason.

**A. Getting the spectrum**

| Option | Notes | Verdict |
|---|---|---|
| Aperture sum (as in xcavation and the Source Discovery Tool, radii 3 to 5 px) | Simple. Wrong in crowds | Build as quick look only |
| PSF-weighted sum at a fixed position | Stage 7 | Build |
| PSF fit with the position free and shifted by proper motion per exposure | The SPIFF method. Needed for movers. Position freedom helps when coordinates are stale, as with WISE 0855 | Build inside the along-track mode |
| Joint fit of every catalogued source in the cutout | Stage 9, the same idea as the official pipeline. Best in crowds | Build for processed fields |
| Learned deblending network | No truth set to train on this weekend | Skip |

**B. Representing the spectrum**

| Option | Notes | Verdict |
|---|---|---|
| 102 bands divided by their mean, with errors and a coverage mask | The baseline. Within one point of learned embeddings in fact 9 | Build |
| Physical indices and slopes (stage 10, section 9.3) | Each has an error and a meaning a user can read | Build |
| Non-negative matrix factorisation or PCA coefficients | Used for the galaxy and AGN templates. Weights handle missing bands | If time |
| Autoencoder latent (1D convolutional, 6 numbers, error-weighted loss) | Published design reaches χ² per band of about 1.18. Its reconstruction error doubles as a novelty score | If time |
| Masked transformer over the native measurements (wavelength, bandwidth, flux, error, date as one token each) | Fits the instrument: no binning, gaps are natural, date carries variability. Needs on the order of 100,000 spectra and GPU days `[ESTIMATE]` | Later |
| Pretrained astronomy foundation models (AION-1, SpecCLIP, AstroCLIP) for the spectrum | None lists SPHEREx spectrophotometry among its inputs `[TO CHECK]`, so the spectrum would be out of distribution | Skip for spectra. AstroCLIP's image encoder is usable for an image branch later |

**C. Deciding the type**

| Option | Notes | Verdict |
|---|---|---|
| Template χ² fit, dropping the worst 5 bands, scale solved analytically | The SPIFF method. Works with few examples. Returns residuals a person can inspect | Build |
| Nearest neighbours in the labelled library | Cheap check on the template result | If time |
| Gradient-boosted trees (XGBoost first, LightGBM and CatBoost as tests) on bands, indices and survey features | Handles missing values. Trains in minutes on a laptop `[ESTIMATE]`. The classifier used in the published star and galaxy study | Build |
| TabPFN | Strong on small tables. Version 2 weights carry an Apache 2.0 licence with an attribution clause. Later weights are non-commercial, so only version 2 fits our licence `[TO CHECK row limit, K25]` | If time |
| Small neural network on the bands (MLP or 1D convolutional) | A second, different model for the ensemble | If time |
| Transformer classifier | Comes with option B's transformer | Later |
| Two-level classifier | Level 1 by trees. Level 2 for ultracool dwarfs by template | Build |
| Stacked ensemble: logistic regression over out-of-fold outputs of the members | Often scores above each single member and keeps calibration simple. Keep it only if the test score says so | Build when two members exist |

**D. Physical parameters**

| Option | Notes | Verdict |
|---|---|---|
| Spectral type from templates, temperature range from the type | Empirical, so it avoids the model misfit in fact 7 `[TO CHECK source of the type to temperature relation, K26]` | Build |
| Ice optical depths and ratios (section 9.3) | The ice team's own quantities | Build |
| χ² fit to public model grids (Sonora Elf Owl, Sonora Diamondback, ATMO2020) | Show as a model comparison with the reduced χ² and the spread between grids. Never as a single answer | If time |
| Data-driven model trained on labelled spectra (The Cannon approach) | Works at this resolution in published tests. Inherits the label errors | Later |
| Neural posterior estimation trained on simulated spectra | Fast and published for brown dwarfs with JWST data. When simulations misfit real data, posteriors come out too narrow, which is our case today | Later |

**E. Adding other surveys**

| Survey | Adds |
|---|---|
| Gaia DR3 | Parallax, so distance. Proper motion. G, BP, RP brightness. Classifier probabilities. Low-resolution XP spectra from 330 to 1,050 nm for most sources brighter than G 17.6, which overlap SPHEREx band 1. Variability class |
| 2MASS | J, H, Ks from 1997 to 2001, a second epoch more than 20 years back |
| CatWISE2020, AllWISE | W1 and W2 with proper motions, W3 and W4 for dust, artefact flags |
| NEOWISE single exposures | Brightness changes over more than 10 years |
| ZTF | Optical variability in the north |
| Euclid, in the deep fields | Sharp images for shape, near-infrared spectra, classifications |
| Sky position | Galactic latitude, dust, and cloud membership from SPLICES |
| Moving Object Search Tool | Whether a known solar-system object was there at that time |
| SIMBAD | An existing type, when one exists |

Derived values with direct physical meaning:
- Absolute magnitude from parallax: `M = m + 5 log10(parallax in arcsec) + 5`. Gaia gives parallax in milliarcseconds.
- Tangential speed: `4.74 × proper motion (arcsec/yr) / parallax (arcsec)` km/s.
- Reduced proper motion when parallax is missing.
- A flag per survey for "no detection", which is evidence in itself for faint red objects.
- Matching: move Gaia and CatWISE positions to the SPHEREx frame date before matching. Use `gaia_dr3_allwise_best_neighbour` on IRSA for the Gaia to WISE match instead of building one.

Ways to combine:

| Option | Notes | Verdict |
|---|---|---|
| Physical gates | Parallax above 5σ means the object is inside our galaxy, so galaxy and quasar are excluded. A known solar-system object at the frame time settles the type. Gates outrank every model | Build |
| One table of all features into the trees | Missing entries stay empty | Build |
| Bayes combination: class prior by sky zone and brightness times the spectrum result | Corrects for labels that over-represent bright, well-studied objects | Build |
| Stacking with a meta-learner | Same as in C | Build when two members exist |
| Contrastive alignment of spectrum and image embeddings | The method behind the 25-point gain in fact 9, shown on simulated data | Later |
| One multimodal transformer | Needs far more paired data than we can assemble | Later |

**F. Confidence**

| Option | Notes | Verdict |
|---|---|---|
| Isotonic calibration on a held-out split | Corrects stated confidence to observed accuracy | Build |
| Conformal prediction sets per class | Output is the set of types that contains the truth 90% of the time. An empty set means no known type fits. Matches a tool that reports and leaves the decision to people | Build |
| Resampling within errors: redraw the spectrum 100 times and reclassify | Gives the confidence range shown on screen | Build |
| Prior correction by sky zone and brightness | See E | Build |
| Deep ensembles | Only with neural members | If time |
| Bayesian neural networks | Costly, and calibration still needs checking afterwards | Skip |

**G. Finding what fits no type**

| Option | Notes | Verdict |
|---|---|---|
| Residual χ² after the best template | SPIFF flags reduced χ² above 3 with a 10% error floor | Build |
| Isolation forest on the features | Called M3 in older docs | Build |
| Empty conformal set | Comes free with F. In a 2026 study of transient spectra, 40% of out-of-taxonomy inputs got an empty set at the loosest setting | Build |
| Autoencoder reconstruction error | Comes with B's autoencoder | If time |

Before a spectrum is called unusual, rule out the ordinary causes in this order: blend share above 0.3, variability between visits, flagged or ghost pixels, spacecraft glow in detectors 5 and 6. In the SPIFF sample, most low-quality matches came from background sources and blends.

**H. Checking the result**

1. Split by sky tile, 60% train, 20% calibrate, 20% test.
2. Test on gold labels only.
3. Report every score per brightness bin: W2 up to 12, 12 to 13, 13 to 14, fainter than 14.
4. Leave one type out of training, then confirm its members land in Unclassified or are flagged unusual.
5. Cross-extraction: for 100 SPIFF sources, compare our spectrum with theirs band by band. Report the median ratio.
6. Fixed cases: the five test targets, with expected readings written down before the model runs (section 9.8).

### 9.6 The design

Three layers. Each layer's output is stored, so every number on screen can be traced.

**Layer 1. Readings.** No learning. Spectrum with errors, molecule readings, measured motion, distance and absolute magnitude from parallax, variability between visits, blend share. Shown whether or not any model runs.

**Layer 2. Experts.** Each answers one question from one kind of evidence and can abstain.

| Expert | Input | Output |
|---|---|---|
| E0 Feature trees (XGBoost) | molecule features and the two slopes from stage 10, each with its error and significance | probability per type. The idea of section 3.11 in its pure form |
| E1 Template match | binned spectrum | best three templates, reduced χ², residual per band |
| E2 Spectrum trees (XGBoost) | bands and indices | probability per type |
| E3 Spectrum network (if time) | bands with errors | probability per type, reconstruction error |
| E4 Motion and distance | parallax, proper motion, absolute magnitudes | probability per type, gates |
| E5 Catalogue | Gaia classifier, SIMBAD type, SPLICES class | probability per type, origin Catalogue |
| E6 Variability | SPHEREx visits, NEOWISE, Gaia class | variable or steady, amplitude |
| E7 Sky prior | Galactic latitude, dust, cloud membership, brightness | prior per type |

**Layer 3. Combiner.**
1. Apply the physical gates.
2. Combine expert outputs with a stacked logistic regression trained on out-of-fold predictions.
3. Calibrate, then build the conformal set and the resampled range.
4. Run the novelty checks from G.
5. Write the explanation: how far each feature moved the result (SHAP values of the trees, summed over the inputs that belong to one feature), the deciding bands, each named by its feature where it lies in one, which expert moved the result most, what is missing, and which observation would settle it.

Three results are stored for every source:
- **Molecule readings alone**: E0 only.
- **Spectrum alone**: E0 to E3.
- **All data**: every expert.

Showing all three tells the user what the molecule readings carry, what the rest of the spectrum adds, and what the other surveys add. A disagreement between the spectrum result and the catalogue type is the mismatch signal of stage 11.

E0 abstains when fewer than two features are measured, and the panel then says `Not measured: too few molecule features`.

When the template and the trees disagree on the top type, the shown confidence is capped at 50%.

### 9.7 On screen

Follows section 5. The Identity panel gains three blocks. The numbers below only show the layout.

```
Molecule readings
Methane dip, 3.3 µm        0.42 mag ± 0.05    Measured    8σ
Carbon dioxide, 4.3 µm     0.18 mag ± 0.06    Measured    3σ
Carbon monoxide, 4.7 µm    not detected       Measured    under 2σ

Most likely type
Probably an ultracool dwarf, T type     78%  (range 70 to 85)
Also possible: reddened background star 14%
Molecule readings alone 48%.  Spectrum alone 61%.  With Gaia and WISE 78%.
Toward this type: methane dip, long slope
Away from this type: none
Deciding bands: methane dip 3.3 µm measured, carbon dioxide 4.3 µm measured, 1.6 µm not measured

What would settle it
A second visit with motion measured. Next SPHEREx pass: [date window].
```

Wording rules:
- The panel never states a type as fact. It uses the confidence words.
- Every reading shows its origin: Measured, Catalogue, Estimated or Assumed.
- A refused reading states its reason, for example `Not measured: the source varies between visits`.
- For ice sightlines the molecule block adds the line `[value]% of water ice`.
- The model card opens on click: training data, label grades, scores per brightness bin, date.

### 9.8 Build order for the ML lane

**Data to fetch before training, in this order**
1. SPIFF binned CSVs, templates and tables. UltracoolSheet CSVs.
2. SPLICES (3.1 GB). Count rows per cube tile to pick the star-forming field.
3. Cube tiles for the chosen fields.
4. Per-field TAP pulls: Gaia, CatWISE, AllWISE, 2MASS, DESI, Euclid, SIMBAD.

All of these download by script with no account. The Spectrophotometry Tool is the one resource that needs a browser login. It is optional.

All links and file names are in `DATA-LINKS.md` sections 6, 7 and 12. Keep downloads in `data/`, which git ignores.

| Task | What | Check | Hours |
|---|---|---|---|
| T43a | Label table with source and grade per row | counts per type and grade reported | 1 |
| T43b | Training spectra: ingest SPIFF, extract cube spectra, cross-extraction and calibration checks | median ratio per band within 10% for bright isolated sources | 3 |
| T43c | Molecule readings with resampled errors and refusal reasons | methane dip significant for Epsilon Indi B, absent for Barnard's Star | 2 |
| T43d | E1 template match with SPIFF templates and per-type medians | subtype within 2 of the literature for 80% of a held-out SPIFF sample | 2 |
| T43e | Survey features, gates, E0 feature trees, E2 spectrum trees, E4, E7, and the input ladder of section 9.11 | release gate values and every rung of the input ladder reported per brightness bin | 3 |
| T43f | Stacking, calibration, conformal sets, resampled ranges, the three stored results, feature contributions, deciding bands | coverage of the 90% sets between 88% and 92% on the test split | 2 |
| T43g | Novelty checks with the contamination screens first | a left-out type is flagged at the stated rate | 1 |
| T43h (stretch) | E3 autoencoder member, added to the stack | kept only if the test score improves | 3 |
| T43i (stretch) | Model grid comparison for ultracool dwarfs | spread between grids shown beside the best fit | 3 |

T42 (features with errors) and the M1 part of T45 (real or artefact) sit in the ML lane too.

**Expected readings for the five test targets** (write down before the model runs):

| Target | Expected | Known difficulty |
|---|---|---|
| Barnard's Star | Star, cool dwarf, no methane dip | very bright, check for overflow |
| Epsilon Indi B | Ultracool dwarf, T type, methane dip | glare from Epsilon Indi A |
| WISE 0855 | Ultracool dwarf, Y type, or Unclassified with a stated reason | detected only in detectors 5 and 6, spacecraft glow at the same wavelengths |
| RW Aurigae | Young star, variable | blended pair, changes between visits |
| R Draconis | Evolved giant, variable | overflow in many bands |

If the model gives a different answer for a target, the panel shows the model's answer and the catalogue type side by side. That is the honest outcome and it is useful to a judge.

### 9.9 Pass marks

- Level 1 recall 0.80 or more per type on gold labels above signal to noise 10.
- Calibration error 0.05 or less.
- Conformal 90% sets cover between 88% and 92% on the test split.
- Ultracool dwarf subtype within 2 subtypes for 80% of the held-out sample. The published scatter is 1.5 subtypes.
- Cross-extraction median ratio within 10% per band.
- Every score reported per brightness bin. A bin that fails is shown as failing.
- M1 recall 0.90 or more at the 1% artefact threshold.

A version that fails stays unpublished and the panel shows readings with no type.

Reference points from published work, so a judge can compare: 81.2% clean matches for known brown dwarfs with W2 ≤ 14.0, and 72.9% three-way accuracy for galaxies and AGNs at all-sky depth.

### 9.10 Later, after the hackathon

1. **Self-supervised spectrum transformer.** Pretrain by masking parts of the native measurements for 100,000 or more sources, then fine-tune on labels. Condition to start: a bulk source of spectra, either the High Reliability Source Catalog or our own extraction at scale.
2. **Alignment with other data.** Contrastive training between SPHEREx spectra, Gaia XP spectra and survey image cutouts.
3. **Review labels feed training.** A case that reviewers settle becomes a gold label, weighted by reviewer agreement. This joins the community layer to the model.
4. **Posterior estimation for cold brown dwarfs**, once model grids fit the 4 to 5 µm region. Run coverage tests on real spectra before showing any posterior.
5. **Ice catalogue comparison.** The SPHEREx ice catalogue of about 10 million sources is due one year after the prime mission ends. Compare our optical depths against it.
6. **Asteroid classes** once the SPHEREx Solar System Object Catalog is public.

### 9.11 Model shortlist with library names

**First picks**

| Job | First pick | Library call | In plain words |
|---|---|---|---|
| Type from the spectrum and survey data | XGBoost | `xgboost.XGBClassifier` | Builds a few hundred small decision trees. Each new tree corrects the mistakes of the ones before. One row of numbers per object in, a probability per type out. Copes with empty cells, so an object with no Gaia match still gets a result |
| Second opinion on the type | Template match | `numpy`, written by us | Takes the average spectrum of each known type, scales it to the object, measures the mismatch with χ². Smallest mismatch wins. No training |
| Merge the opinions | Logistic regression stacking | `sklearn.linear_model.LogisticRegression` on predictions from `sklearn.model_selection.cross_val_predict` | Learns how much to trust each model for each type, then gives one probability per type |
| Make percentages honest | Isotonic calibration | `sklearn.calibration.CalibratedClassifierCV(method="isotonic")` | Compares stated confidence with how often the model was right on held-out objects and corrects it, so 80% means right about 80% of the time |
| List every plausible type | Split conformal prediction | about 20 lines of `numpy`, written by us | Uses held-out objects to find a score threshold. Every type above it goes in the set. The set contains the true type at the chosen rate, 90% |
| Flag objects that fit no type | Isolation forest | `sklearn.ensemble.IsolationForest` | Splits the data at random many times. Objects separated from the rest in very few splits are unusual |
| Real object or image artefact | XGBoost | `xgboost.XGBClassifier` | Same method, trained on injected test sources against known artefacts |
| Molecule readings | Polynomial continuum fit | `numpy.polyfit` | Draws the smooth baseline and measures how deep each dip is. No learning |
| Which inputs decided the result | SHAP on the trees | `shap.TreeExplainer` | For one object, shows how much each input pushed the result toward or away from a type. Shown beside the deciding bands |

**Worth testing, in order of expected gain**

Test inputs first. Inputs move the score more than the model does (fact 9). Run the same XGBoost settings on each rung of this input ladder, on the same split, and report balanced accuracy and recall per type for each rung, per brightness bin:

| Rung | Inputs | What it answers |
|---|---|---|
| 1 | Molecule features only (methane, water ice, CO2, CO, 3.3 µm emission, hydrogen lines) | How much of the type the molecules alone reveal. This is expert E0 without the slopes |
| 2 | All stage 10 features: rung 1 plus the two slopes | What the overall colour adds. This is expert E0 |
| 3 | The 102 bands only | What a model finds with no physics given to it |
| 4 | Bands plus features | Whether the features add to the raw bands |
| 5 | Rung 4 plus survey data | What Gaia, WISE and the other surveys add |

Every rung is published in the model card and as proof test B13, as measured. No rung has a pass mark. The shipped type model is still chosen by the rules below.

| Job | Alternative | Library call | Why it might win | Watch out for |
|---|---|---|---|---|
| Type model | LightGBM | `lightgbm.LGBMClassifier` | Same family, grows trees differently, often faster | Overfits small data unless `num_leaves` and `min_child_samples` are limited |
| Type model | CatBoost | `catboost.CatBoostClassifier` | Same family, good results on default settings | Slower to train |
| Type model | Histogram boosting | `sklearn.ensemble.HistGradientBoostingClassifier` | Same family, no extra install | Fewer tuning options |
| Type model | Random forest and extra trees | `sklearn.ensemble.RandomForestClassifier`, `ExtraTreesClassifier` | Simple, hard to overfit, a sanity check | Empty cells may need filling first `[TO CHECK for the installed version]` |
| Type model | TabPFN, version 2 weights | `tabpfn.TabPFNClassifier` | Pretrained network for small tables, no tuning. Strong below about 10,000 rows `[TO CHECK limit]` | Needs a GPU to be fast. Only version 2 weights fit our licence |
| Type model | Small neural network | `sklearn.neural_network.MLPClassifier` or PyTorch | Learns smooth shapes across neighbouring bands | Needs scaled inputs and filled cells. Usually behind trees on small tables |
| Type model | 1D convolutional network or autoencoder | PyTorch | Reads the spectrum as a curve. Reconstruction error doubles as a novelty score | Needs more labelled spectra than we have for most types |
| Type model | Logistic regression | `sklearn.linear_model.LogisticRegression` | The baseline every other model must beat | None. Always run it |
| Second opinion | Nearest neighbours in the library | `sklearn.neighbors.KNeighborsClassifier` | Keeps rare variants that an average hides | Slow on large libraries, sensitive to noisy bands |
| Second opinion | Component templates | `sklearn.decomposition.NMF` | A few building-block spectra per type fit mixed objects | Needs complete spectra with no empty bands |
| Merge | Plain average of probabilities | `numpy.mean` | Nothing to overfit | Ignores which model is better for which type |
| Merge | Best single model, no merge | none | Simplest to explain | Loses the disagreement signal |
| Calibration | Sigmoid scaling | `CalibratedClassifierCV(method="sigmoid")` | Steadier than isotonic on a small held-out set | Less flexible |
| Calibration | Temperature scaling | a few lines, written by us | One number to fit, standard for neural networks | Only for models that output logits |
| Plausible types | MAPIE | `mapie` | A maintained conformal library with adaptive sets | Its interface changed between major versions `[TO CHECK]` |
| Unusual objects | Local outlier factor | `sklearn.neighbors.LocalOutlierFactor(novelty=True)` | Finds objects in thin regions near dense groups | Sensitive to the neighbour count |
| Unusual objects | One-class SVM | `sklearn.svm.OneClassSVM` | A learned boundary around normal objects | Slow, needs scaled inputs |
| Unusual objects | Template residual χ² | written by us | Direct and readable | Blends and variables also fit badly, so screen those first |
| Real or artefact | Small convolutional network on the image cutout | PyTorch | Sees the source's shape in pixels `[FROM MEMORY: transient surveys use this]` | Needs thousands of labelled cutouts. Stretch only |
| Molecule readings | Gaussian-process continuum | `sklearn.gaussian_process.GaussianProcessRegressor` | Gives an error on the baseline. The ice team uses it | Slower, needs a sensible kernel |
| Settings search | Optuna | `optuna` | Finds good tree settings automatically | Tune on the calibrate split only, never on the test split |

**How the winner is chosen**

1. Every candidate uses the same split by sky tile and the same gold test set.
2. Scores, in this order: balanced accuracy (the mean of per-type recall), log loss, calibration error.
3. Choose on the calibrate split. Run the test split once, at the end, for the reported numbers.
4. A more complex model replaces a simpler one only if it gains more than one point of balanced accuracy and the gain holds in every brightness bin.
5. Estimate the noise first: resample the test set 200 times and note how much the baseline score moves. Treat a gain smaller than that as zero.
6. Rare types: class weights (`sample_weight` or `class_weight="balanced"`). Report each type's recall on its own.

Starting settings for XGBoost on a few thousand rows `[ESTIMATE, tune from here]`: 300 to 600 trees, depth 4 to 6, learning rate 0.05, row and column sampling 0.8, early stopping on the calibrate split.

### 9.12 ML open checks

Answers go in `docs/decisions.md`.

- [x] K18 SPIFF package: CC BY 4.0, version QR2-2026-04-24, 6.7 GB, file list known (`DATA-LINKS.md` section 7.1). Still open: the CSV column layout. Read `00_README.txt` and `spiff_tables.zip` first
- [ ] K19 Whether the SUDA atlas and the galaxy and AGN NMF templates are public. SUDA's abstract does not say
- [ ] K20 SPLICES: the values `STYPE_ML` takes and what the two probability stages mean (Ashby et al. 2023, Lakshmipathaiah et al. 2023). Read the release notes PDF
- [x] K21 Spectrophotometry Tool: 20 positions per upload, two jobs at once, no API, at least 5 minutes per job, needs a browser login. Optional. Nothing depends on it
- [ ] K22 All-sky cube spectra against our own single-frame spectra for 20 bright isolated stars: median ratio per band
- [ ] K23 Laboratory band strengths for H2O, CO2 and CO ice, with the paper for each
- [x] K24 Gaia DR3 tables confirmed in the Gaia documentation: `gaiadr3.vari_classifier_result`, `vari_long_period_variable`, `qso_candidates`, `galaxy_candidates` (ESA archive). `gaia_dr3_source` and `gaia_dr3_astrophys_param` also on IRSA TAP. Still open: the XP spectra route (GaiaXPy)
- [ ] K25 TabPFN version 2: row and feature limits, exact licence text
- [ ] K26 A published relation from ultracool dwarf subtype to temperature
- [x] K27 Gold galaxy and quasar labels: DESI DR1 through NOIRLab Data Lab TAP (`desi_dr1.zpix`, `desi_dr1.mws`, `desi_dr1.agngal`). CC BY 4.0
- [ ] K28 Licences of xcavation, spxquery, SPIFF code, and each ML library before importing. Reading their methods is fine
- [ ] K29 DESI `zpix` `healpix` column: confirm nside 64, nested, before using the tile count query
- [ ] K30 The exact `xtalk_class` folder names under the DR1 root

---

## 10. Interface

Words and number formats come from section 5. This section decides where things go and how they behave.

### 10.1 Principles

1. **One surface.** The sky is always on screen. Everything else is a panel over it. There are no separate pages.
2. **One anatomy.** Selecting a source, a frame or a case opens the same panel in the same place with the same four parts in the same order: what it is, evidence, status, actions.
3. **One primary action per panel.** Other actions are secondary.
4. **Everything is a link.** The URL holds the whole view.
5. **Plain first.** A sentence anyone can read, then the number, then its origin.
6. **Live or absent.** No control exists unless it works.
7. **Honest images.** Real pixels, real limits, false colour labelled.

### 10.2 Layout

```
+--------------------------------------------------------------------------+
| mark  Phantom Worlds   [ position or name ...            ]   Proof  Sign |
+----------------------+---------------------------------------+-----------+
| Left panel (320)     |  Viewer (sky, then frames)            | Right     |
| Search by light      |                                       | panel     |
| Signals and cases    |  scale bar   N/E compass   cursor pos | (400)     |
|                      +---------------------------------------+ Identity  |
|                      |  Observation matrix (full width)      | or Case   |
+----------------------+---------------------------------------+-----------+
```

- The left panel opens on demand and is closed by default for guests.
- The right panel opens when something is selected.
- The matrix appears once a position has frames.
- Under 900 px wide: panels become a bottom sheet with three heights. The matrix collapses to a visit selector with a control to expand.
- Sign in appears only when accounts ship. Until then the control is absent.

### 10.3 Zoom levels

| Level | Shows | Source |
|---|---|---|
| Sky | the whole sky, named targets and fields as marks | Aladin Lite with IRSA's SPHEREx all-sky layer if it loads (K6), otherwise 2MASS and WISE layers, which Aladin offers |
| Field | our stacks on the field grid, sources as selectable marks | frame packs |
| Source | 4x upsampled stacks, position marks per visit, path | frame packs |
| Pixel | the 6.15″ pixel grid with values on hover | frame packs |

Moving between levels is one continuous zoom. The switch from the Aladin layer to our frames happens at the Field level with a short cross-fade.

### 10.4 Viewer

Modes (URL `mode`): `play`, `diff`, `stack`, `colour`, `follow`, `detdiff`.

| Control | Behaviour |
|---|---|
| Detector | D1 to D6, each with its range in µm. A detector with no frames is absent |
| Play / Pause, speed | plays comparable visit stacks in date order. The date and band range show on the image |
| Difference | choose two visits. Result is B minus A. A slow mover shows as a dark and bright pair |
| Stack | all visits of the chosen detector, or a dragged selection in the matrix |
| Visits as colour | up to three visits as red, green, blue. Legend names which visit is which colour |
| Follow motion | enter motion in ″/yr and direction, or take it from the selected source |
| Same season | play only visits from the same side of Earth's orbit, so parallax drops out |
| Colour difference | one detector's stack minus another's. Labelled as a colour image |
| Test source | insert a synthetic mover of chosen brightness and motion, in any band. Always labelled synthetic |
| Other telescopes | list of images of this position from other missions, with links |
| Stretch | greyscale by default, asinh with automatic limits, sliders for limits, invert. An alternative colour map that stays readable for colour-blind users |
| Overlays | Gaia DR3, CatWISE2020, flags, known solar-system objects. Positions at the frame date |
| Measure | ruler for separation. Two-click motion tool that returns ″/yr and direction |
| Export | PNG of the view, GIF of the play, CSV of the frame list |

Always visible on the image: scale bar in arcseconds, north and east arrows, date, detector and band range, cursor RA and Dec, pixel value on hover.

Marks: the entered position (cross), the present position of a named mover (ring), measured position per visit (small dots joined by a line), predicted path (dashed).

### 10.5 Observation matrix

Every frame of the position is a dot. Date runs across, wavelength runs up on a log scale, dot colour is the detector label colour. Visits are shaded columns with their frame count.

- Click a dot: show that frame.
- Drag across dates inside one band window: play those.
- Drag across wavelengths inside one visit: stack those.
- Drag a box: stack per visit, then play.
- A selection that breaks the like-with-like rule snaps to the nearest valid one and says so.

### 10.6 Right panel: Identity

Order of parts:

1. **What it is.** Name or designation. Status chip (Known, Unclassified, Uncatalogued). The class line with its confidence word and number, or "Unclassified".
2. **Evidence.**
   - Spectrum chart with error bars, feature markers, and the deciding bands highlighted. A line under it names the two explanations compared and whether the deciding bands are measured.
   - Spectrum strip: 102 cells, hue by band order, brightness by measured value. Reference strips of the top three classes under it.
   - Molecule readings block (section 9.7).
   - Motion: measured value against catalogue value.
   - Blend share and S/N.
   - History strip: 2MASS, WISE era, SPHEREx, each marked seen or not seen at the predicted position.
3. **Status.** For a case, the state bar and the prediction with its date and state.
4. **Actions.** Primary: `Open case` for a case, `Report this source` for an uncatalogued source (when accounts ship), `Compare` otherwise. Secondary: `Save view`, `Export`.

Every number follows the reading format and opens its origin on click: frame IDs, catalogue row, pipeline version, model card.

### 10.7 Left panel: Search by light, Signals

**Search by light.** Presets as toggles: Methane dip, Water ice, CO2, CO, 3.3 µm glow, Hydrogen lines, Very red, Seen only beyond 4 µm, Moved between visits, Changed brightness, Not in any catalogue. Two sliders: minimum S/N, maximum blend share. A line states which field the search covers. Results list sorted by priority. Selecting a result selects the source in the viewer.

**Remove known.** A three-way switch on the viewer inside processed fields: Image, Model, Residual.

**Signals and cases.** A list with ID, kind, field, priority bar and state. Explained and Artefact stay in the list with their reason.

### 10.8 Proof panel

Opens from the top bar. Report card table (target, test, pass mark, measured, pass or fail). Recovery curves from the injection test. Classifier reliability chart. Stated limits with sources. Data sources and credits. "Next" list.

### 10.9 Guided start

A guest who lands on `/` sees the sky and one button: `Find the coldest known brown dwarf`. It runs four steps on WISE 0855, each driving the real viewer:
1. Go to the position. Both marks appear: the challenge's coordinates and where the object is now.
2. Six detector stacks side by side. Four show nothing, the fifth a trace, the sixth a dot.
3. Play the detector 6 visit stacks. The dot shifts.
4. Open Identity. The spectrum rises only past 4 µm.

Each step has one sentence and `Next`. `Skip` is always present. If T03 shows WISE 0855 cannot be detected, the tour moves to Epsilon Indi B.

### 10.10 Visual system

**Colour.** Neutral greys around images so the surround does not tint what the eye sees. This replaces the blue-black palette in the 13 Nov prototype.

| Token | Value | Use |
|---|---|---|
| canvas | `#08090B` | behind everything |
| surface | `#111317` | panels |
| raised | `#181B20` | controls, rows |
| line | `#262A31` | borders, grid |
| text | `#E8EAED` | primary text |
| muted | `#9AA1AC` | secondary text. Passes 4.5:1 on surface |
| accent | `#9DB8FF` | interactive elements, selection (the colour of a B star) |
| warm | `#FF9A52` | uncatalogued sources, signals, cases, and nothing else (the warm infrared end) |

Detector label colours, used only for small labels and matrix dots: D1 `#A98BFF`, D2 `#63A9FF`, D3 `#4FD4C4`, D4 `#BEDF5A`, D5 `#FFB04D`, D6 `#FF6A5C`. Detectors are also always labelled in text, so colour is never the only cue.

Member class badges use approximate blackbody colours (Charity 2001 table): O `#9BB0FF`, B `#AABFFF`, A `#CAD7FF`, F `#F8F7FF`, G `#FFF4EA`, K `#FFD2A1`, M `#FFCC6F`. L and T are deep red. Y is near black with an infrared outline, because Y dwarfs give off almost no visible light.

**Type.** Space Grotesk for headings. Inter for text and numbers with tabular figures. Sizes 12, 14, 16, 20, 28. No other sizes.

**Shape.** 8 px spacing grid. Radius 8 for controls, 12 for panels. One level of shadow, used only for floating panels. No gradients, no glow, no glass blur.

**Icons.** One stroke set, 24 px grid, 1.75 px stroke, as inline SVG. No emoji.

**Charts.** Direct labels, no legends where a label fits. Error bars always. One chart per panel section.

**Physics rules for any visual.**
1. Any colour standing for a temperature uses the approximate blackbody colour above.
2. Infrared images are false colour, labelled as such. Shorter wavelength maps to bluer.
3. Spectrum strip: hue follows wavelength order (0.75 to 5.0 µm, violet to red), brightness follows flux. The information sits in brightness, so it survives colour blindness.
4. Stars are points sized by brightness. Discs appear only for 3D models, each with a model card marking measured, estimated and assumed values.
5. Orbits obey Kepler's laws. SPHEREx's orbit (about 700 km, sun-synchronous, about 98 minutes) is shown time-compressed with the factor on screen.
6. Camera moves on the sky follow great circles. Depth view distances are true, with a labelled log option. Sources without a parallax appear in depth view as a direction only, with no invented distance.

### 10.11 Motion

Motion is used only when it explains a change.

| Motion | Rule |
|---|---|
| Panel open and close | 180 ms, ease-out, interruptible |
| Zoom and go to | camera follows the zoom-out-then-in path (van Wijk and Nuij). Under 1.2 s. On the sky, along a great circle |
| Play | hard cut between stacks by default. Optional 80 ms cross-fade |
| Remove known | known sources fade in order of brightness over 1 s, leftovers stay |
| Spectrum arriving in live mode | points appear in the order the frames were taken |
| Uncatalogued marks | slow pulse, 2 s period, off under reduced motion |
| Prediction settled | the measured mark moves into place once |

No decorative motion. No parallax backgrounds. Stars never twinkle. Respect the reduced-motion setting everywhere.

### 10.12 States

Every fetch has four designed states with the sentences from section 5.6: loading with real stages, empty, partial, error. Skeletons match the final layout. A failed overlay never blocks the image.

### 10.13 Access and performance

- Every control reachable by keyboard, with visible focus. Shortcuts: space Play, `1` to `6` detector, `[` and `]` previous and next visit, `d` Difference, `s` Stack, `c` Visits as colour, `/` position box, `?` shortcut list.
- Real `button`, `a`, `input` and `label` elements. Touch targets 44 px or more.
- Text contrast 4.5:1 or better.
- First frame under 3 s on 4G for named targets. Live mode first frame under 10 s, complete under 45 s.
- Decoding and resampling run in workers. The viewer holds 60 frames per second during Play on a mid-range phone.

### 10.14 Signs of a demo, all banned

Placeholder text or data. A dashboard of metric cards. Controls that do nothing. A tab bar of pages. Generic hero copy. Three-word slogans. Pills on every value. Gradient backgrounds. Emoji as icons. A chat box. Anything labelled "AI".

---

## 11. Community layer and game system (Tier C)

Built only after Tier B is clean at the freeze. Until then it appears on the Proof panel under "Next" and in the prototype. It is designed in full here so the story on the project page is complete and true.

### 11.1 Roles

Guest (views everything), Member (contributes), Trusted reviewer (earned by reputation), Moderator (team).

### 11.2 How a case moves

1. A detector raises a signal, or a member reports a position (`Report this source`).
2. Machine checks run (section 8, stage 12). Failing signals exit as Artefact or Explained with the reason, and the exit is credited.
3. A passing signal becomes a case in state Machine-checked. A mover case gets its locked prediction.
4. In review: members answer structured questions blind, before seeing other answers. Known-answer cases are mixed in unannounced to measure each reviewer.
5. Reviewed needs 5 or more reviews and reputation-weighted agreement of 0.8 or more.
6. Prediction held: the next SPHEREx pass settles the prediction (section 8, stage 14).
7. Follow-up ready: the packet is exported in the shape the receiving body accepts (Backyard Worlds for brown dwarf candidates, AAVSO VSX for variables, Minor Planet Center for solar-system objects). The person who found it sends it.
8. Confirmed elsewhere: only with a link to the outside body's confirmation.

Discussion is attached to cases as evidence (a measurement, a saved view, a comparison) pinned to a sky position, date and band, each storing its exact view. A refutation role assigns one member to explain the case away before it moves up.

### 11.3 Why the game rules look like this

Evidence:
- Gravity Spy: machine-learning-guided training that moves volunteers through levels raised accuracy from 54% to 90%, tasks per volunteer from 121 to 228, and retention from 2 to 2.5 sessions (Jackson et al. 2020, Computers in Human Behavior 105, 386 participants).
- Old Weather: competitive ranks motivated top contributors, while low scorers felt demotivated by a distant competition they could not reach, and some found it stressful (Eveleigh et al. 2013).
- EyeWire study: competitions can make tasks stressful when players gain unassailable leads (Reeves, West and Simperl 2018).

Rules that follow:
1. Three separate quantities. **XP** measures effort. **Reputation** measures accuracy on known-answer cases and settled forecasts (0 to 1, Bayesian per task type) and weights every review. **Class** is the level and needs both.
2. Rewards follow checked accuracy and real outcomes. Raw volume, time on site, logins and comments earn nothing.
3. No all-time global leaderboard. Personal progress, a shared weekly community goal, and an optional weekly board of about 20 members at the same class.
4. Harder work unlocks by measured skill, as in Gravity Spy.
5. Forecasts: a member states a probability that a prediction will hold. When it settles, the forecast is scored with the Brier score and feeds reputation.

### 11.4 Classes: the spectral sequence O to Y

The real stellar classes O B A F G K M continued by the brown dwarf classes L T Y. Members start with bright, easy targets and progress toward the faint cold objects the project hunts. WISE 0855 is a Y dwarf.

| Class | Approx. temperature | XP | Reputation | Unlocks |
|---|---|---|---|---|
| O | above 30,000 K | 0 | none | explore, save, follow, minigames |
| B | 10,000 to 30,000 K | 100 | training done | review queue: bright, isolated cases |
| A | 7,500 to 10,000 K | 400 | 0.70 | report a spot |
| F | 6,000 to 7,500 K | 1,000 | 0.75 | add evidence and discussion |
| G | 5,200 to 6,000 K | 2,000 | 0.80 | variable-star cases |
| K | 3,700 to 5,200 K | 3,500 | 0.83 | crowded-field cases (blend over 0.3) |
| M | 2,400 to 3,700 K | 5,500 | 0.86 | faint cases (S/N 5 to 10) |
| L | about 1,300 to 2,400 K | 8,000 | 0.88 | label-mismatch and unusual-spectrum cases |
| T | about 500 to 1,300 K | 12,000 | 0.90 | tie-break reviews |
| Y | below about 500 K | 18,000 | 0.92 | mentor, propose known-answer cases (moderator approves) |

A class once earned is kept. Access to a gated queue follows current reputation. XP thresholds and reputation marks are design proposals, tuned after launch.

### 11.5 XP table

| Action | XP |
|---|---|
| Guided tour completed | 20 |
| Training case answered (5 cases) | 10 each |
| Review submitted | 4 |
| Known-answer case answered correctly | +6 |
| Review matches the final consensus (paid when the case closes) | +6 |
| Report passes the machine checks and becomes a case | 30 |
| A case you reported or reviewed reaches Follow-up ready | 100 |
| A case you contributed to is confirmed by an outside body (link required) | 500 |
| Minigame: each correct known-answer item | 1 |

Caps: 400 XP a day from reviews, 50 a day from minigames.

### 11.6 Minigames

Real SPHEREx data. Each round has 10 items: 7 known-answer items scored at once, 3 real unknowns that count toward consensus. Players are told which was which after the round.

| Game | Task | Skill it trains | Feeds |
|---|---|---|---|
| Blink | Frames play, tap the mover or answer "none" | motion vetting | mover detector labels |
| Spectrum Match | Pick which of 4 reference strips matches a measured strip | classification | type model labels |
| Signal or Noise | Real light or artefact (cosmic ray, ghost, edge, bright-star residual) | artefact rejection | M1 labels |

### 11.7 Achievements

Each tied to a skill or an outcome.

| Badge | Earned by | Origin of the name |
|---|---|---|
| First Light | finishing the guided tour | a telescope's first observation |
| Blink Comparator | 10 known movers found in Blink | the device Clyde Tombaugh used to find Pluto in 1930 |
| Dipole | 10 slow movers identified from the bright-dark pair in Difference | Backyard Worlds' term for slow movers |
| Methane Line | 10 correct T or Y dwarf matches | methane absorption that defines T dwarfs |
| Ice Line | 10 correct young-star cases with 3.05 µm water ice | the ice feature SPHEREx maps |
| Cosmic Ray | 25 artefacts correctly rejected | the most common false signal |
| Crowded Field | 25 correct Galactic-plane reviews | the region older searches avoided |
| Deep Field | 25 reviews in the ecliptic-pole deep fields | SPHEREx's most-observed areas |
| Mira | 10 correct variable-star cases | the first known periodic variable star |
| Second Opinion | 5 times your review disagreed with the model and the consensus agreed with you | rewards independent judgement |
| Follow-up Ready | a case you reported reaches Follow-up ready | case state |
| Confirmed | a case you contributed to is confirmed elsewhere | case state |

### 11.8 Other Tier C ideas

| Idea | What it does |
|---|---|
| Band ratio view, feature map | one band minus the median of its neighbours, from our packs in fields and from the all-sky cube elsewhere |
| Quick spectrum anywhere | from the all-sky cube, labelled quick look |
| Draw the light | sketch a spectrum, get matching sources |
| Recipes | saved searches scored automatically against the benchmark list |
| Spectrum time series | in the deep field, where R Draconis has 222 dates |
| Distance slider | stack along the shift expected for a chosen distance |
| 3D neighbourhood | from the Gaia Catalogue of Nearby Stars, true distances, log option labelled |
| Indonesian text | the whole interface in Bahasa Indonesia |

---

## 12. Build plan

Lanes are areas of code: **E** Engine, **M** ML, **W** Web. Any person or agent can take any lane. Tick a box only when its check passes. One task per pull request. The order below is a priority and dependency order. The one fixed time is the end of the build window, Sun 15 Nov 2026 23:59 WIB.

### 12.1 Milestones, in order

1. Scaffolds, contracts, first range read.
2. Walking skeleton: Barnard's Star plays from a real frame pack on the deployed site.
3. All five targets packed. Play, Difference, Stack, overlays, URL. API live mode v0.
4. **Tier A gate** (section 12.5). Report card v1.
5. Remove known on two fields. Search by light. Identity with class and molecule readings.
6. **Freeze review** (section 12.9). Cases, prediction check, searched depth done or cut.
7. Proof numbers final. Project page, video, AI-use statement.
8. Submitted. Repo public. Leave margin before the window closes.

The ML lane does not wait on the viewer. It runs alongside from milestone 1 and feeds milestone 5. Long jobs (field cutouts, joint fits, model training) run in the background with logs in `data/logs/`.

### 12.2 Open checks

The full list with status is in section 16. Do the ones that block your first tasks before coding.

### 12.3 Hour zero

- [ ] **T00 (every session)** Run `date -u`. Read `AGENTS.md` and this file's sections for your lane. *Check: the time and the next task ID are stated in the first reply.*
- [ ] **T01-E** Scaffold `engine/`, `api/`, `proof/` with `uv`, `ruff`, `pytest`, a CI workflow. *Check: `uv run ruff check . && uv run pytest` passes with one real test.*
- [ ] **T01-W** Scaffold `web/` with the stack in section 7.2, tokens from section 10.10, CI, deploy to Cloudflare Pages. *Check: deployed URL shows the top bar and an empty sky with the canvas colour. `pnpm -C web build` reports its size.*
- [ ] **T01-M** Scaffold `engine/phantom/ml/` and `ml/` (training scripts, configs, reports) and run the downloads in section 9.8 by script. *Check: files listed with sizes and checksums in `data/manifest.csv`.*
- [ ] **T02-E** Write `contracts/`: JSON Schemas for manifest, sources (with the ML fields in section 7.3), spectrum, cases, searched, proof report, model card. OpenAPI for the API. URL contract. *Check: schemas validate. Changes after this need a line in `docs/decisions.md`.*
- [ ] **T03-E** WISE 0855 first look. Range-read one D6 file, then stack the 21 D6 frames of Apr to May 2026. *Check: S/N at the predicted position reported. Decision recorded: WISE 0855 or Epsilon Indi B as the motion showcase.*

### 12.4 Tier A, Engine

- [ ] **T04** Frame list for any position, both collections, deep frames included, visits grouped. *Check: counts for the five targets meet section 6.2.*
- [ ] **T05** Cutout engine by byte range, parallel, cached, S3 then IRSA. *Check: 0.2° cutout under 1 MB per file and pixel-identical to a full download.*
- [ ] **T06** Alignment against Gaia DR3 at the frame date. *Check: RMS 1.0″ or better on the Barnard field.*
- [ ] **T07** Display products: background removal, resampling, packs, quality plane, visit stacks. *Check: a pack round-trips through the schema. Like-with-like test passes.*
- [ ] **T08** Position parsing and name resolution with positions at the frame date. *Check: unit tests with the challenge page's own strings for all five targets. WISE 0855 returns both the entered and the present position.*
- [ ] **T09** Measured motion per target. *Check: values and errors for Barnard's Star, Epsilon Indi B, WISE 0855 written to the proof report.*
- [ ] **T10** Spectrum on the fly, fixed position and along a track. *Check: an isolated bright star's spectrum is smooth across detector joins within errors.*
- [ ] **T11** Light curve, change spectrum, period. *Check: R Draconis period and RW Aurigae change per detector written to the proof report, with saturated bands listed.*
- [ ] **T12** Pack and publish the five targets and a first W1925 cutout to the Dataset repo. *Check: the deployed site loads each from static files.*
- [ ] **T13** API with `/health`, `/version`, `/resolve`, `/frames` (streamed), `/catalog`, `/spectrum`, `/sso`. Deployed. *Check: first frame of an arbitrary position under 10 s. Allowlist test passes.*
- [ ] **T14** Weekly update workflow. *Check: a manual run on one target finishes and updates `data_as_of`.*
- [ ] **T15** Proof script v1 for Tier A tests. *Check: `proof/report.json` validates and lists every Tier A test with a measured value.*
- [ ] **T16** Solar-system objects by name through the Moving Object Search Tool, and `/track`. *Check: "Ceres" returns SPHEREx frames with a position in each.*
- [ ] **T17** Pack Comet 3I/ATLAS from IRSA's table as a named target. *Check: Follow motion keeps the comet centred across frames.*
- [ ] **T18** Load `CWAVE`, `CBAND`, solid angle maps and ePSF calibration once per detector and use them everywhere. *Check: wavelength at three test pixels matches the per-file WCS within 1 nm.*

### 12.5 Tier A, Web

Start on a small real pack from T03 or T07. Do not build against invented data.

- [ ] **T20** App shell: top bar, position box using the same parsing rules, URL-synced view state, sky layer. *Check: every URL parameter in the contract restores the view. Back and forward work.*
- [ ] **T21** Pack loader in a worker and the WebGL2 viewer: stretch, invert, pixel readout, scale bar, compass, cursor position. *Check: values under the cursor match the engine's for three test pixels.*
- [ ] **T22** Modes: Play, Difference, Stack, Visits as colour, with the like-with-like guard. *Check: Barnard's Star shows a dark and bright pair in Difference and a coloured pair in Visits as colour.*
- [ ] **T23** Observation matrix with click, drag and box selection. *Check: WISE 0855 shows three visits with the frame counts from the manifest.*
- [ ] **T24** Overlays at the frame date and the four marks (entered, present, measured, path). *Check: the Gaia mark for Barnard's Star sits on the star in every visit.*
- [ ] **T25** Field of view control with load estimate, live mode over the stream, all four states. *Check: with the API off, named targets work and live mode shows the stated error sentence.*
- [ ] **T26** Identity panel v1: spectrum chart, strip, motion, metadata, light curve, change spectrum. Origin on click for every number. *Check: every number follows the reading format.*
- [ ] **T27** Follow motion, Measure tools, Export (PNG, GIF, CSV). *Check: the motion tool on Barnard's Star returns a value within the pass mark of the engine's.*
- [ ] **T28** Embed mode, `/t/<id>` routes, guided start on WISE 0855. *Check: the embed URL renders inside an iframe on a blank page.*
- [ ] **T29** Proof panel reading `proof/report.json`. *Check: no number is typed by hand in the web code.*
- [ ] **T30** End-to-end tests on five targets, a phone viewport, API-off run, bundle budget. *Check: all green in CI.*
- [ ] **T31** Same-season play, Colour difference, Test source. *Check: detector 6 minus detector 4 leaves WISE 0855 as the brightest source near the centre. A test source at S/N 5 is visible in Play.*
- [ ] **T32** Other telescopes list from `/elsewhere`. *Check: Barnard's Star lists images from at least two other missions with working links.*

**Tier A gate.** Every one of the eight optional considerations has a visible, working control, and the five targets pass or publish their measured failure. Until then, Tier B waits.

### 12.6 Tier A and B, ML (no dependency on the viewer)

- [ ] **T42** Features with errors for every source. *Check: methane dip is significant for Epsilon Indi B and absent for a field M star.*
- [ ] **T43a** Label table with source and grade per row (section 9.4). *Check: counts per type and grade reported.*
- [ ] **T43b** Training spectra: ingest SPIFF, extract cube spectra, cross-extraction and calibration checks. *Check: median ratio per band within 10% for bright isolated sources.*
- [ ] **T43c** Molecule readings with resampled errors and refusal reasons. *Check: methane dip significant for Epsilon Indi B and absent for Barnard's Star.*
- [ ] **T43d** Template match with SPIFF templates and per-type medians. *Check: subtype within 2 of the literature for 80% of a held-out sample.*
- [ ] **T43e** Survey features, physical gates, XGBoost feature trees (E0) and spectrum trees (E2), motion and distance expert, sky prior, the input ladder of section 9.11. *Check: release gate values and every rung of the input ladder reported per brightness bin.*
- [ ] **T43f** Stacking, calibration, conformal sets, resampled ranges, the three stored results, feature contributions, deciding bands. *Check: 90% sets cover between 88% and 92% on the test split. If the gate fails, no type is published.*
- [ ] **T43g** Novelty checks, with the contamination screens first. *Check: a left-out type is flagged at the stated rate.*
- [ ] **T43h** (stretch) Autoencoder member added to the stack. *Check: kept only if the test score improves.*
- [ ] **T43i** (stretch) Model grid comparison for ultracool dwarfs. *Check: spread between grids shown beside the best fit.*
- [ ] **T45-M1** Real-or-artefact model M1 from injections and flagged artefacts. *Check: recall 0.90 or more at the 1% artefact threshold on held-out injections.*

### 12.7 Tier B, Engine

- [ ] **T40** Reference scene for W1925 and RW Aurigae fields. *Check: source counts per catalogue reported.*
- [ ] **T41** Joint fit, residual images, blend share. *Check: photometry tests in section 13 run and report.*
- [ ] **T44** Detectors: mover, mismatch, variable, edge check. *Check: known asteroids in the RW Aurigae field recovered at the stated rate. Edge check calibrated on non-variable stars.*
- [ ] **T45** Machine checks, history, priority, `cases.json` (uses M1 from the ML lane). *Check: every case lists each check with its result.*
- [ ] **T45b** Ghost check from the crosstalk parameter files. *Check: a known ghost of a bright star in the Epsilon Indi field is rejected with the stated reason.*
- [ ] **T46** Prediction check: retro test on the movers, locked predictions for new cases, settling in the weekly job. *Check: predicted and stay separations reported for each mover.*
- [ ] **T47** Injection test and `searched.json`. *Check: recovery table by brightness and motion for both fields.*
- [ ] **T48** Proof script v2 with all Tier B tests. *Check: report validates.*

### 12.8 Tier B, Web

- [ ] **T50** Remove known switch with the brightness-ordered fade. *Check: Image, Model, Residual share one stretch.*
- [ ] **T51** Search by light panel with presets, sliders, results, field statement. *Check: outside a field the stated sentence shows and the panel offers nothing else.*
- [ ] **T52** Identity v2: class line with confidence word, molecule readings, deciding bands, blend, history strip, model card. *Check: the 50% cap message appears when template and classifier disagree.*
- [ ] **T53** Signals and cases list, case view with checks, priority, state bar, prediction. *Check: a held retro prediction shows both separations.*
- [ ] **T54** Searched depth layer and Proof panel v2 with recovery curves and limits. *Check: the Planet X statement is generated from `searched.json`.*

### 12.9 Freeze review, before the project page is written

1. Run every acceptance check again on the deployed site.
2. Remove any control whose feature is unfinished.
3. Write the "Next" list from open tasks, one line each.
4. Search the web code for every string and check it against section 5.
5. Only fixes after this point.

### 12.10 Tier C, in this order, only after the freeze review is clean

- [ ] **C1** Accounts with Supabase: Google or email link, display name, row-level security
- [ ] **C2** Blind review with structured questions, known-answer cases, reputation-weighted agreement. Reviewed needs 5 or more reviews and agreement of 0.8 or more
- [ ] **C3** Evidence pinned to a sky position, date and band, each storing its exact view
- [ ] **C4** Forecasts on predictions and reputation scored by Brier score when a prediction settles
- [ ] **C5** Refutation role: one member assigned to explain the case away before it moves up
- [ ] **C6** Feature map: one band minus the median of its neighbours, from our packs in fields and from the all-sky cube elsewhere
- [ ] **C6b** Quick spectrum anywhere from the all-sky cube
- [ ] **C7** Draw the light: sketch a spectrum, get matching sources
- [ ] **C8** Recipes: saved searches scored automatically against the benchmark list
- [ ] **C9** Spectrum time series in the deep field
- [ ] **C10** Distance slider: stack along the shift expected for a chosen distance
- [ ] **C11** 3D neighbourhood from the Gaia Catalogue of Nearby Stars
- [ ] **C12** Minigames: Blink, Spectrum Match, Signal or Noise
- [ ] **C13** Indonesian text

### 12.11 Steps outside the code

These sit outside any lane. Each is written so that nothing else waits on it.

- **Deploy tokens.** Deployment reads tokens from GitHub secrets (names in `SETUP.md`). If a token is absent, the deploy job reports which one and stops. The site still builds and the tests still run. Agents never create accounts and never handle token values.
- **Independent proof run.** `proof/run.py` runs from a clean clone on any machine and gives the same report. Check this before the numbers are published.
- **Usability check.** When people with no astronomy background are available, five minutes each on the site shows what they misread. Fix what they misread. Nothing waits on it.
- **Project page, video, AI-use statement.** Written from sections 4, 13 and 18 and `docs/ai-log.md`. A 30-second video or 7 slides.
- **Spectrophotometry Tool spectra.** Optional extra check for the ML lane. It needs a browser login.
---

## 13. Proof

### 13.1 Rules

1. One script, `proof/run.py`, produces every number on the Proof panel. It writes `proof/report.json` and `proof/report.md`.
2. Pass marks below are fixed. They are not tuned after results come in.
3. A failed test is published with its measured value and a one-line reason.
4. The web code reads `report.json`. No proof number is typed into the interface.
5. The script runs from a clean clone on any machine and gives the same report. This is checked before the numbers are published.
6. Each entry records `run_at`, `pipeline_version` and the frame IDs used.

### 13.2 Tier A tests

| ID | Target | What is measured | Pass mark |
|---|---|---|---|
| A1 | every field | Alignment against Gaia DR3 at the frame date | RMS 1.0″ or better |
| A2 | Barnard's Star | Motion from our visit positions | within 1.0″/yr of Gaia DR3 |
| A3 | Epsilon Indi B | Motion | within 1.5″/yr of the catalogue value |
| A4 | WISE 0855 | Detection in each full D6 visit stack | 5σ or better in both |
| A5 | WISE 0855 | Detection in D1 to D4 stacks | absent (under 3σ) |
| A6 | WISE 0855 | Motion between visits 2 and 3 | within 2.0″/yr and 15° of the published vector |
| A7 | R Draconis | Period from our light curve | within 10% of the AAVSO VSX period |
| A8 | RW Aurigae | Brightness change between visits, per detector | reported with errors. Compared with AAVSO where data exist |
| A9 | five targets | Time to first frame from static data on a 4G profile | under 3 s |
| A10 | arbitrary position | Live mode, first frame and complete | under 10 s and under 45 s |
| A11 | five targets | Position strings from the challenge page parse and resolve | all five |
| A12 | site | End-to-end run with the API off | named targets fully usable |

### 13.3 Tier B tests

| ID | Target | What is measured | Pass mark |
|---|---|---|---|
| B1 | RW Aurigae field | Synthetic Ks from our spectra against 2MASS, isolated stars with 9 < Ks < 13 | median offset 5% or less, scatter 10% or less |
| B2 | W1925 field | Same test by blend share | scatter 20% or less for blend under 0.3 |
| B3 | RW Aurigae field | Known asteroids from SkyBoT above our measured limit recovered by the mover detector | 80% or more |
| B4 | benchmark list | Methane dip preset finds known T dwarfs with W2 < 13.5 | 80% or more found, false matches 1% or less of neighbours |
| B5 | type model | Recall per Level 1 type on gold labels above S/N 10, calibration error, conformal coverage | 0.80 or more, 0.05 or less, 88% to 92% |
| B6 | model M1 | Recall on held-out injected sources at the 1% artefact threshold | 0.90 or more |
| B7 | movers among the targets | Retro prediction: separation from predicted position, and from the stay position | predicted within 2σ, stay position excluded at 3σ |
| B8 | both fields | Injection recovery by brightness and motion | published as measured |
| B9 | SMDET-1 | Detection attempt | published as measured. Expected: not detected |
| B10 | edge check | False flag rate on non-variable stars | 1% or less |
| B11 | ultracool dwarf subtype | Held-out SPIFF sample | within 2 subtypes for 80% |
| B12 | cross-extraction | Our spectra against SPIFF and the Spectrophotometry Tool | median ratio within 10% per band |
| B13 | type model | Input ladder: balanced accuracy and recall per type for molecule features alone, all features, bands, bands plus features, and all data | published as measured |

### 13.4 What the Proof panel states in words

- Depth: SPHEREx reaches 17.8 to 18.8 AB magnitude at 3.8 to 5.0 µm after four surveys (Bock et al. 2025). Our measured depth per field comes from B8.
- Crowding costs about 1.5 magnitudes near the Galactic plane (SMDET-1 paper, arXiv 2608.00046). Our measured loss comes from B2 and B8.
- Planet X: the faintest moving test object we recover, the motion range tested, and the field size limit. Generated from B8.
- Class percentages are calibrated on our test fields only.
- A class is a suggestion for follow-up. It confirms nothing.
- Molecule readings are feature strengths. Composition percentages are shown only for ice relative to water ice.
- How much of an object's type its molecule readings alone reveal, and what the rest of the spectrum and the other surveys add. Generated from B13.

### 13.5 Credits to show

SPHEREx DR1 and Quick Release Spectral Images (IRSA, with the DOIs and acknowledgement text), IRSA tutorials, Bock et al. 2025, Gaia DR3, 2MASS, CatWISE2020, unWISE, Spitzer GLIMPSE, SIMBAD, VizieR, AAVSO VSX, IMCCE SkyBoT, Aladin Lite, Astropy, photutils, WiseView, Backyard Worlds, The Rogue Worlds Project, Faherty et al. 2018, the SMDET-1 paper. For the ML lane add: the SPIFF library (Gagné et al. 2026), UltracoolSheet, SPLICES (Ashby et al. 2023), DESI DR1, Euclid, and each library used. DOIs are in `DATA-LINKS.md` section 13.

---

## 14. Data facts from the resource pages

Read on 13 and 14 Nov 2026. Links in `DATA-LINKS.md`. Facts already in section 6.1 are not repeated.

### 14.1 Survey design

- Target groups of 17 pointings. Surveys 1 and 2 in the first 12.5 months. Surveys 3 and 4 are shifted by half a channel. Four passes over the sky in total.
- Deep fields at the north ecliptic pole and near the south ecliptic pole. Euclid Deep Field North (centre 17:58:55.9 +66:01:03.7, 22.9 deg² in Euclid Q1) overlaps the SPHEREx north deep field.
- 17 channels per detector, 102 in total.
- Exposure 113.58 s. 20 cm aperture. Field of view 2 × (3.5° × 11.3°).

### 14.2 Releases

- QR2 (pipeline 6.4 to 6.5.6): download only until February 2027, not returned by searches.
- DR1 (November 2026): Year 1 reprocessed.
- QR3 (since September 2026): surveys 3 and 4.
- DR2 later. `l3_flux_corrections` let QR2-era fluxes be combined with DR1 and QR3.
- Weekly ingestion. SIA lags about a day. The browsable directories and TAP have the newest.

### 14.3 Search

- TAP base with `/sync` and `/async`. Parameters `QUERY`, `FORMAT` (VOTable, CSV, TSV, IPAC_TABLE, HTML, FITS), `MAXREC`. Sync queries time out at 5 minutes. One geometric constraint per query. When calling by URL, encode spaces as `+` and quotes as `%27`. Long URLs fail, so use POST from code.
- SIA collections: `spherex_dr1`, `spherex_dr1_deep`, `spherex_dr1_cube`, `spherex_qr3`, `spherex_qr3_deep`. `RESPONSEFORMAT=JSON` works. Result columns include `access_url`, `cloud_access`, `t_min`, `t_max`, `em_min`, `em_max`, `s_region`, `obs_id`.
- R Draconis sits in a deep field, so include the `_deep` collections.

### 14.4 Files

- Level 2 path: `level2/[Planning Period]/l2b-v[Version]-[Processing Date]/[Detector]/`. Example: `qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_2026W21_2A_0001_2D1_spx_l2b-v27-2026-268.fits`.
- File name: `level2_[Observation ID]D[Detector]_spx_l2b-v[Version]-[Processing Date].fits`, about 70 MB.
- Calibration products under each release root: `epsf` (DR1, QR3), `spectral_wcs` (`CWAVE`, `CBAND`), `solid_angle_pixel_map` (arcsec² per pixel), `xtalk_class` (ghosts displaced vertically, horizontally, and streaks), `nonfunc_v2`, `dichroic`, `l3_flux_corrections`, `spectral_channels`, `sip`, `dark`, `abs_gain_matrix`, `nonlinear_pars`, `readnoise_pars`, and templates `aurora_template` (detector 1), `he_template` (detectors 1 and 2), `shuttle_glow_template` (detector 5). Folder patterns in `DATA-LINKS.md` section 5.
- A spectral files archive holds per-band central wavelengths and transmission curves.

### 14.5 All-sky cube

- Tile path: `hips5_cube/hips_20261026/Norder5/Dir{(ipix // 10000) * 10000}/Npix{ipix}_cube.fits` under the DR1 root. HEALPix order 5, nside 32, nested. 12,288 tiles of 3.36 deg² each.
- Extensions IMAGE, NHITS, FLAGS, SPECTRAL_CHANNELS, WCS-WAVE. 102 planes, plane = 17 × (detector - 1) + (band - 1), planes 50 and 51 blank (the Year 1 gaps). About 300 MB per tile. IRSA says spectra from it are for display only.

### 14.6 Spectrophotometry Tool

- Built on The Tractor. Only the flux amplitude is fitted. Point source or Sérsic galaxy profile. Position is fixed, never recentred. Local background from a 15-pixel box, masking known-source pixels. Position-dependent PSF, VARIANCE for errors, µJy via the solid angle map.
- Upload: up to 20 sources with `ra` and `dec` columns. Neighbours within confusion range must be in the same upload to be deblended. Two jobs run at once, others queue.
- Run time: seconds ≈ 1.67 × number of images + 50. At least about 5 minutes per job. About 5,700 images takes a little over 2.5 hours. Ecliptic-pole sources can reach about 20,000 measurements and take hours.
- Output: wavelength, flux, flux_err, lambda_width, flags (bit 7 dichroic, bit 33 fit error), fit_ql, flux_bkg, lvf_id, det_id, deep_flg, mjd, data_collection, x_image, y_image. VOTable download.
- No API. Log in before submitting. Jobs kept 14 days. Biweekly Tuesday maintenance can stop jobs.

### 14.7 Moving Object Search Tool

URL interface with `catalog=spherex`, `input_type=name_input`, `obj_name`, `obs_begin`, `obs_end`, `output_mode=Brief`. Also accepts NAIF IDs, MPC one-line elements and manual orbital elements. Other catalogs: `2mass`, `wise_merge`, `wise_neowiser`, `ztf`, `spitzer_bcd`. The page shows both `output_mode` and `outfmt` as the format parameter, so test which works.

### 14.8 Comet 3I/ATLAS

Observed August and December 2025. IRSA provides `obscore_3I_Atlas.vot` listing every frame with the comet's predicted position per exposure (`comet_ra`, `comet_dec`). Extended and faint at many wavelengths.

### 14.9 SPLICES

Nearly nine million isolated, infrared-bright point sources likely to show ice absorption. One 3.1 GB FITS file, `20241107_SPLICESv8.6.fits.gz`. Columns: 2MASS, WISE, IRAC and Gaia DR3 photometry, parallax, proper motion and distance, class columns (`CLASS_1`, `YSO_PUB`, `STYPE_ML`, `STYPE_ML_PROB1`, `STYPE_ML_PROB2`), variability from NEOWISE and Gaia (`VarClassGaia`), extinction `Av`, molecular cloud membership, number of clouds on the sightline, neighbour counts and flux ratios within 7.6″ from Gaia, IRAC, VVV and UKIDSS. 633,814 sources have class probability above 90%, 56% of them young stars and 40% evolved giants. Cite Ashby et al. 2023 and DOI `10.26131/IRSA554`.

### 14.10 Catalogues on IRSA TAP `[VERIFIED 14 Nov]`

Gaia (`gaia_dr3_source`, `gaia_dr3_astrophys_param`, `gaia_dr3_allwise_best_neighbour`, `gaia_dr3_total_galactic_extinction_map`), WISE (`catwise_2020`, `allwise_p3as_psd`, `neowiser_p1bs_psd`, `unwise_2019`), 2MASS (`fp_psc`, `fp_xsc`), ZTF (`ztf_objects_dr24`), Euclid Q1 and DR1 tables. Gaia variability, LPV, quasar and galaxy candidate tables and XP spectra are on the ESA Gaia archive only.

### 14.11 Other data

- **Gaia DR3:** classifications for 1.59 billion sources, astrophysical parameters for 470 million, 219 million low-resolution XP spectra from 330 to 1,050 nm (most G < 17.6), 6.6 million quasar candidates, 4.8 million galaxy candidates, about 10 million variability classifications. The MAST link on the Resources tab is a general page with no DR3 endpoint.
- **DESI DR1:** 28,425,963 entries in `zall-pix-iron.fits` (21.7 million galaxies, 1.86 million quasars, 4.87 million stars). Spectra 360 to 982 nm. Milky Way Survey catalogue with Teff, logg, [Fe/H]. AGN and galaxy classification catalogue. CC BY 4.0. Anonymous TAP at NOIRLab Data Lab.
- **Euclid:** Q1 (March 2025) covers the deep fields at single-visit depth. DR1 was due 21 Oct 2026 and is being released in stages, with the full release around mid-2027. DR1 deep-field tables are already listed on IRSA TAP.
- **UltracoolSheet v2.1.0** (3 Jul 2025): 4,000+ ultracool dwarfs and imaged exoplanets with photometry, parallaxes, proper motions, multiplicity, spectral types, gravity classes, ages. Main table 3,890 objects. CC BY 4.0.
- **SPIFF library:** see section 9.4.
- **NEOSSat and CADC:** NEOSSat is a Canadian microsatellite for near-Earth objects and space objects. No value for classification. Used only for the Other telescopes list and the Solar System Object Image Search for movers.

### 14.12 WiseView and the Source Discovery Tool

- WiseView controls are listed in section 6.5.
- Source Discovery Tool method: convert to flux with the solid angle map, subtract background, mask by flag bits, reproject one detector onto another, subtract them to get a colour image, detect with SExtractor, aperture spectra at radii of 3, 4 and 5 pixels. Its stated use is finding very red sources.

### 14.13 Status and citation notes

- IRSA status on 13 Nov: some object lookup services were unavailable. Name lookup needs a fallback.
- DOIs: QR2 `10.26131/IRSA652`, QR3 `10.26131/IRSA662`, DR1 `[TO CHECK]`. IRSA asks for a fixed acknowledgement sentence. Copy it from the Quick Release overview.
- Some IRSA and DESI directories block automated readers (robots) but open in a browser and with curl or wget.

### 14.14 What these make possible

Ranked by value for the objective.

1. **Any asteroid or comet by name.** The Moving Object Search Tool returns the SPHEREx frames that contain a named object and where it is in each. Type "Ceres", get its frames, Follow motion, read its spectrum along the track. The challenge names asteroids and comets first.
2. **Comet 3I/ATLAS as a showcase.** An interstellar comet with a carbon dioxide coma, with per-frame positions provided.
3. **Test source.** Insert a synthetic object with the ePSF in any band. It teaches, and it is the same code as our injection test.
4. **Colour difference.** Detector 6 minus detector 4 is one shader. WISE 0855 stands alone in that image.
5. **Same-season play.** Visits alternate between two sides of Earth's orbit. Playing one season removes parallax and leaves proper motion.
6. **Science-grade wavelengths with no per-file read.** `CWAVE` and `CBAND` are fixed per detector pixel. Load six maps once.
7. **Ghost check.** Ghost and streak bits plus the crosstalk parameter files say where false images fall.
8. **Spectrum anywhere on the sky.** The all-sky cube gives a quick spectrum and a feature map for any fixed source, outside our processed fields too. It is also our bulk route to training spectra.
9. **Feature maps the way IRSA makes them.** One plane minus the median of its neighbours.
10. **Precovery for movers.** The Moving Object Search Tool searches 2MASS, WISE, NEOWISE and ZTF for an object with given orbital elements.
11. **Other telescopes at this position.** One SIA query to IRSA and one to the Canadian archive list every image of the position from WISE, 2MASS, Spitzer, HST, JWST, CFHT and others, with links.
12. **Canadian Solar System Object Image Search.** For a mover case with a fitted arc, it searches Canadian-hosted archives for earlier images, NEOSSat included.
13. **Ice labels.** SPLICES gives millions of sources expected to show ice. It labels the water ice class and checks the Water ice preset.
14. **Glow check for WISE 0855.** Checking our detection against IRSA's glow template, and saying so on the Proof panel, is a validity point other teams will likely miss.
15. **One service for frames and catalogues.** IRSA TAP holds SPHEREx, Gaia, WISE, 2MASS, ZTF and Euclid tables.

---

## 15. Decisions log

Full history. New decisions go in `docs/decisions.md` first, then into this section at the next update.

### 13 Nov 2026

- Challenge chosen on 9 Nov: Planet X and SPHEREx.
- Project name: Phantom Worlds (13 Nov, 08:20). "Flipbook" was rejected as a product name because it confused readers. "Flipbook 102" in older docs means Phantom Worlds.
- The required objective is the time-series viewer for any position, tested on five targets. Everything else answers the eight optional considerations or the Background text.
- Phantom Worlds is a new product. Backyard Worlds, WiseView and past projects are references, credited by name.
- Priority for the judged page: a smaller part working on real SPHEREx data over a full design shown as mockups. The full design appears as "Next" and in the prototype.
- "Sent to NASA for verification" replaced by evidence packets for the bodies that register finds. Voting replaced by blind structured review. Agreement ranks cases and never makes them true.
- Word on screen for a wavelength slice: band.
- Member score name: reputation.
- Confidence words: under 50% Unclassified, 50 to 69% Possibly, 70 to 89% Probably, 90% and above Very likely.
- Case states: Detected, Machine-checked, In review, Reviewed, Prediction held, Follow-up ready, Confirmed elsewhere. Exits: Artefact, Explained.
- Interface: one sky surface with panels. No separate pages.
- New mechanisms chosen: observation matrix as control, Visits as colour, change spectrum, Follow motion (Tier A). Remove known, deciding bands, prediction check, searched depth, edge check (Tier B).
- Accounts, review, pinned evidence, forecasts and games are Tier C. Accounts and reviews use Supabase when they ship.
- Game system: XP for effort, reputation for accuracy, classes O to Y need both. No global leaderboard.
- Two coding agents planned: Claude Code and Codex, each reviewing the other's lane.
- Writing project code was locked until the build window opened. Data downloads and reading were allowed before it.
- The challenge Resources tab went live: IRSA SPHEREx pages, SPHEREx tutorial notebooks, WiseView, Gaia DR3, plus optional Canadian Space Agency resources.
- Added to scope from the resources: solar-system objects by name, Comet 3I/ATLAS, Same-season play, Colour difference, Test source, Other telescopes, ghost check, quick spectrum from the all-sky cube.
- The plan is a default. Agents may propose and take better routes, logged in `docs/decisions.md`.
- Pixel quality follows IRSA's rejection list for its all-sky cubes. Overflow kept and reported. Ghost bits send signals to Artefact. Bit 21 never masked.
- Science wavelengths come from `CWAVE` and `CBAND`.
- PSF: EPSF extension at file version 7.0 or higher, the ePSF calibration file below that.
- The current Explanatory Supplement is v2.1 (`SPHEREx_Expsupp.pdf`). The `_QR` file is v2.0.
- Machine learning design (evening): molecule readings are feature strengths with errors. The only composition percentage shown is each ice molecule as a percentage of water ice. Type comes from several experts and a calibrated combiner, stored twice: spectrum alone, and all data. Task T43 split into T43a to T43i.
- Main type model: XGBoost. Second opinion: template match. Merge: logistic regression stacking. Confidence: isotonic calibration, conformal sets, resampled ranges. Unusual: isolation forest, template residual, empty conformal set. Alternatives are tested against these on our own split.

### 14 Nov 2026

- Training data plan: SPIFF for ultracool dwarfs, all-sky cube tiles for every other type, the Spectrophotometry Tool for a gold check set only. Labels from DESI DR1, Gaia DR3, SPLICES, UltracoolSheet, SIMBAD, Euclid.
- Gold labels for testing, silver labels at half weight in training.
- Reddened background star kept as its own class.
- IRSA TAP hosts the Gaia DR3, WISE, 2MASS, ZTF and Euclid tables (K16), so one service covers frames and catalogues.
- Work moves to Claude Code. Three files carry the project: `SETUP.md`, `docs/PROJECT-CONTEXT.md`, `docs/DATA-LINKS.md`. They replace the planning kit.
- Code is split into three lanes by area: Engine, ML, Web. Any person or agent can take any lane.
- The docs assign no work to named people and set no start times. The project runs on its own. Outside contributions are welcome and nothing depends on them.
- The Spectrophotometry Tool is optional. The cube calibration check uses our own single-frame spectra.
- Molecule readings first (section 3.11): expert E0 gives a type estimate from molecule features alone, three results are stored per source (molecule readings alone, spectrum alone, all data), every estimate is explained by feature contributions, and the input ladder is published as proof test B13.
- The repository is shared by the whole team. `SETUP.md` is the setup guide for any person or agent, `CONTRIBUTING.md` says how work flows, and a task is claimed by opening a draft pull request.

### Questions still open from the 13 Nov deck

1. Is Tier A the right must-ship core. (Working answer: yes.)
2. Do accounts and review ship now, or show as Next. (Working answer: Tier C, shown as Next unless the freeze review is clean early.)
3. Which screens go into the 30-second video.
4. Are the XP and reputation thresholds right. (Working answer: proposals, tuned after launch.)
5. Indonesian text this weekend, or after. (Working answer: Tier C.)

---

## 16. Open checks

Answers go in `docs/decisions.md` with the command or URL used.

| ID | Check | Status |
|---|---|---|
| K1 | Remaining TAP columns for exposure ID, release and version (`TAP_SCHEMA.columns`) | Partly done: join and four columns known |
| K2 | S3 key layout under each prefix, and what `cloud_access` holds | Path layout confirmed. Listing still to do |
| K3 | PSF rule by file version | Done |
| K4 | Saturation limit by detector. Is RW Aurigae affected. Separation of the RW Aurigae pair | Open |
| K5 | AAVSO VSX period for R Draconis. AAVSO light curves for R Dra and RW Aur | Open |
| K6 | Whether Aladin Lite v3 can show the IRSA all-sky HiPS cube, its tile pixel size, and whether a tile can be read by byte range | Open |
| K7 | Source of WISE-era epoch images for the history check | Open |
| K8 | Public list of known T and Y dwarfs with positions and W2 for the benchmark | Likely answered by UltracoolSheet and SPIFF. Confirm |
| K9 | WiseView controls | Done |
| K10 | 2026 Project Submission Guide: demo format, AI-use disclosure wording | Open |
| K11 | Re-run frame counts for the five targets and W1925. DR1 against QR3 counts | Open, do first |
| K12 | Wavelengths of the edge bands of neighbouring detectors from `CWAVE`. Decides the edge check | Partly done: the Supplement shows slight overlaps |
| K13 | FLAGS bits and IRSA's rejection list | Done |
| K14 | Moving Object Search Tool covers SPHEREx | Done. Test which format parameter works |
| K15 | SPLICES columns | Done. DR1 DOI still open |
| K16 | IRSA TAP hosts Gaia DR3, 2MASS and CatWISE2020 | Done, 14 Nov |
| K17 | Canadian archive SIA answers a position query without an account | Open |
| K18 to K30 | Machine learning checks | See section 9.12 |

---

## 17. Earlier artifacts and what changed since

| Artifact | Link | Status |
|---|---|---|
| Clickable prototype, 18 screens in 5 rows (explore, hunt, join and review, play and progress, proof) | https://claude.ai/artifact/XmXN8VcGMu4TLmo8Gqtwpw | Older than this file |
| Team discussion deck, 30 slides | https://claude.ai/artifact/9KfqnuD4S8qW1CzwWExzZE | Older than this file |
| Blueprint whiteboard | https://claude.ai/artifact/QyXSyjJ9rsa436KgSq45oE | Older than this file |
| Planning kit zip (`docs/01` to `docs/10`) | sent in chat on 13 Nov | Replaced by the three files |

What changed since the deck and prototype:
- The deck says "five asks of the brief". The challenge has one required objective plus eight optional considerations.
- Detector ranges on the deck follow the tutorial. The Supplement's ranges overlap slightly. Use `CWAVE`.
- "Community-reviewed" became "Reviewed", and "Prediction held" was added.
- "Accuracy" and "reliability" became "reputation".
- "Detection" and "candidate" became "signal" and "case".
- The prototype has a tab bar of pages. The product is one sky surface with panels.
- The prototype palette (blue-black) became neutral greys.
- "Three models and the physics check" became readings, seven experts and a calibrated combiner, with XGBoost as the main type model.
- Molecule readings are feature strengths. No full composition percentages.

Every number on the prototype screens is illustrative and labelled so. Do not copy prototype numbers into the product.

---

## 18. Copy rules for the project page, video and slides

House rules. These apply to every word we publish, alongside section 5 for the interface.

**Banned sentence shapes:** "not X but Y" and every reframe of that kind ("This isn't X, it's Y", "Less X, more Y", "While X may seem", "At first glance", "Most people think X"). Em dashes. Two-word slogans like "Analytics, reimagined". Rhythmic triplets, including negative ones. A metaphor before the benefit. Rhetorical questions. Slide sentences with subordinate clauses.

**Banned words:** delve, realm, landscape, tapestry, testament, myriad, robust, harness, seamlessly, effortlessly, quietly, magically, unlock, empower, elevate, supercharge, revolutionise, transform, kills, crushes. Filler: "The result?", "Here's the thing", "Let that sink in", "In today's", "It is important to note", "Furthermore", "Additionally", "Moreover", "That said". No "Enter: ProductName", no "Whether you're X or Y". No analogies or metaphors by default.

**Claims:** never invent a figure. Cite the source for every number or write `[PLACEHOLDER]` and flag it. No unsourced superlatives. No invented user counts. Never claim a capability the build does not have.

**Fix for a weak line:** replace it with a number, a name or a verb. A line that could sit on any other project's page gets cut. Read it aloud to decide.

**Slides:** fixed slide count agreed up front, with a cut list if content overflows. At most 70 words a slide. One idea a slide. Headlines state the conclusion. Two fonts. At most three colours a slide. 40 px safe zone. Headers 36 pt or more, body 18 pt or more. One chart a slide, direct labels, no 3D, no pie beyond four slices. Real logos only. A dark scrim on every background image for 4.5:1 contrast. No stock clichés.

**Voice:** start with the useful answer. Short paragraphs. Active voice. Specific numbers, names and dates. Accurate first, then clear, then specific, then human.
