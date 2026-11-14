# Phantom Worlds: design brief

You are designing the interface for Phantom Worlds, a public web tool built for NASA Space Apps 2026. This brief tells you what the product is, who it is for, what it does and what is true about it. It deliberately says nothing about how it should look. Every visual decision is yours.

Earlier design attempts exist in this repository. The owner judged none of them good enough. Do not use them as a reference for the look. Start fresh.

## 1. The product in one breath

Phantom Worlds lets anyone search NASA's SPHEREx sky by the light each object gives off in 102 infrared bands, to find moving and unexplained objects that no catalogue lists yet, including in the crowded Milky Way.

At its core it is a viewer. Type any position in the sky, and SPHEREx images of that patch play as a time series, so anything that moves or changes stands out. On top of that it reads what each source is probably made of, estimates what kind of object it is with an honest confidence, checks every leftover by machine, and lets people review what the machines could not explain.

The tool gives readings and estimates. People decide what an object is.

## 2. The occasion

| | |
|---|---|
| Event | NASA Space Apps Challenge 2026, challenge 12, "Planet X and SPHEREx" |
| NASA's one required objective | A public web tool that shows SPHEREx images of any patch of sky so anyone can quickly see how it changes over time, like a short video, so moving objects are easy to spot |
| The five test targets NASA names | Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis |
| Judging | Five equal criteria: Influence, Creativity, Validity, Relevance, Presentation. Judges read the project page and open the live site, so first impressions matter |
| Deadline | The build window closes Sun 15 Nov 2026, 23:59 WIB (16:59 UTC) |

## 3. The subject: what SPHEREx is

The design has a rich, real world to draw from. Use it.

- SPHEREx is a NASA space telescope in low Earth orbit. It maps the entire sky every six months.
- It sees in infrared, from 0.75 to 5.0 µm, through six detectors. Each detector looks through a filter whose colour changes across it, so every exposure catches each spot of sky in one narrow band. Over many exposures, every position builds up a spectrum in 102 bands.
- Infrared reveals what visible light hides: cold brown dwarfs, dust-wrapped young stars, ices of water, carbon dioxide and carbon monoxide, the glow of carbon-rich molecules.
- Each pass over a position is a visit. Visits come about six months apart, so a nearby object shifts a little between them.
- The data is public, read straight from NASA's archive (IRSA) and a public cloud bucket.

## 4. Who it is for

| Person | What they want in the first minute | What keeps them |
|---|---|---|
| A curious visitor | To see something real and astonishing | The coldest known brown dwarf, moving across the sky |
| A volunteer hunter | A fast way to inspect many spots and a fair way to report what they find | Search by light, signals with machine checks, cases, review |
| A student or teacher | To understand what a reading means | Plain words first, the number one step deeper, the origin of every value |
| An astronomer | Trust and reuse | Frame IDs, flags, pipeline version, exports, a proof page they can rerun |
| A judge | To grasp the idea, then believe it works | The live tool on real data, and honest proof |

## 5. Moments worth designing for

These are true, specific to this project, and nobody else has them.

The coldest known brown dwarf, moving. WISE 0855 is about 285 K, colder than the North Pole in winter, 2.28 parsecs away. In SPHEREx it shows only at the longest wavelengths, in detectors 5 and 6. It moves 8.1 arcseconds a year. The position NASA gives is years old, so the object now sits about two arcminutes away from it.

A brown dwarf passing a star. Measured on 14 Nov from real SPHEREx stacks, WISE 0855 is right now passing a background star (Gaia DR3, G 16.3). In the latest visit they are 4.6 arcseconds apart, less than one SPHEREx pixel. In detectors 1 to 4 you see the star. In detectors 5 and 6 you see the brown dwarf. One moves, one stays.

Six detectors, one spot. The same patch of sky looks completely different from 0.75 to 5.0 µm. Things appear and vanish across the bands.

The blink. Clyde Tombaugh found Pluto in 1930 by blinking two photographic plates. Blinking visits is still how movers are found. Difference images show a mover as a dark and bright pair.

Visits as colour. Put three visits in red, green and blue. Fixed stars come out white and movers come out coloured, so one still image shows motion.

Light read as molecules. Methane dips in brown dwarfs, water ice and carbon dioxide ice in front of young stars, the glow of carbon-ring molecules. Each reading is a measured feature strength with an error.

Planet X, honestly. A distant planet would appear as a fast apparent mover. The tool does not promise to find one. It measures and states how faint a moving object it could have found, field by field. That stated limit is the honest Planet X answer.

A prediction that new data settles. When something seems to move, the tool locks a dated prediction of where it will be at the next SPHEREx pass. New data proves it right or wrong, with no expert needed.

## 6. Everything the product does

These are capabilities and content, not layouts. Group them into screens, flows, panels or something else entirely, as you see fit. Some are built, some are planned. The design should cover all of them so the whole product can be seen.

### 6.1 Finding a place in the sky

- A position or name box. It accepts decimal degrees, sexagesimal in several formats (for example `08h55m10.831s -7d14m42.53s`), star names, and solar-system objects by name such as Ceres.
- The five named targets, one step away.
- A whole-sky view with the targets and processed fields marked (Aladin Lite can provide the all-sky layer).
- A guided first experience, "Find the coldest known brown dwarf", a few steps on WISE 0855 that drive the real tool.

### 6.2 The viewer, the heart of the product

| Capability | What it does |
|---|---|
| Detectors and visits | Images of the chosen patch, per detector (D1 to D6, each with its wavelength range) and per visit |
| Play | Visits one after another, like a short video, with speed control |
| Difference | One visit minus another. A mover shows as a dark and bright pair |
| Stack | Visits added together to see fainter things |
| Visits as colour | Up to three visits as red, green and blue |
| Compare detectors | The same spot in all six detectors side by side |
| Colour difference | One detector minus another, which makes very red objects stand alone |
| Same-season play | Only visits from the same side of Earth's orbit, which removes parallax |
| Follow motion | Stack along a chosen motion so a faint mover adds up |
| Test source | Insert a synthetic mover of chosen brightness and motion, always labelled synthetic |
| Observation matrix | Every frame of the position as a dot, date across, wavelength up. Visits show as groups with frame counts. Selecting in it chooses what plays or stacks |
| Marks | The entered position, the object's position at each date, its path, Gaia DR3 and CatWISE stars at the frame date, known solar-system objects, flagged pixels |
| Always on the image | Scale, north and east, date, detector and band range, cursor position, pixel value |
| Image controls | Stretch, contrast, invert, a pixel grid view, a colour map that works for colour-blind users |
| Field of view | A choice of size, with an estimate of how long a bigger field takes to load |
| Measure | A ruler for separation, a two-click motion tool |
| Export | Image, animation, frame list |
| Other telescopes | Images of the same position from other missions, with links |
| Embed mode | The viewer alone, for embedding elsewhere. Every view setting lives in the link |
| Live mode | Any position, with frames streamed from the archive as they are cut. Named targets load instantly from prepared data |

### 6.3 Source details: what is this thing

| Part | What it shows |
|---|---|
| Identity | Name or designation, status (Known, Unclassified or Uncatalogued), its type in catalogues |
| Catalogue readings | Position, motion, parallax, distance, brightness in other surveys |
| Spectrum | Brightness in each of the 102 bands, with errors, molecule features marked |
| Molecule readings | Each molecule's feature strength, error and significance, or the reason it could not be measured. For ices, each molecule as a percentage of water ice |
| Most likely type | Shown three ways: from the molecule readings alone, from the whole spectrum, and from all data including other surveys. Each with a confidence word and a range |
| The reasons | Which features pushed the estimate toward the type and which pushed away, which bands decided it and whether they were measured, which other types remain possible |
| What would settle it | The observation that would answer the question |
| Variability | Light curve and change spectrum for variable objects |
| History | Whether the object was seen at its predicted position in older surveys (2MASS, WISE era) |
| Model card | On request: training data, scores, date |

### 6.4 Search by light

- Find sources in a processed field by molecule features (methane dip, water ice, carbon dioxide, carbon monoxide, 3.3 µm glow, hydrogen lines), by shape (very red, seen only beyond 4 µm), by change (moved between visits, changed brightness) and by catalogue status (not in any catalogue).
- Filters for minimum signal to noise and maximum blending.
- Results ranked by priority, each linking to the source.
- Remove known subtracts every catalogued star from the image to expose what is left, with image, model and residual views.

### 6.5 Signals and cases

| Part | What it is |
|---|---|
| Signals | Raised by the machine detectors: movers, sources whose light disagrees with their catalogue type, variables |
| Machine checks | The tests a signal must pass to become a case, each with its result: seen in several frames and visits, no flagged pixels, no catalogue match, no known asteroid, a real-or-artefact model score, history |
| Case states | Detected, Machine-checked, In review, Reviewed, Prediction held, Follow-up ready, Confirmed elsewhere. Two exits at any point, Artefact and Explained. An exit is a result and is credited |
| Prediction check | A locked, dated prediction, its error radius, where the object would be if it had not moved, and its status: pending, held, failed or not observed |
| Blind review | Members answer fixed questions before seeing anyone else's answers. Agreement ranks a case and never makes a case true |
| Forecasts | A member's stated probability that a prediction will hold, scored when it settles |
| Evidence | Measurements, saved views and comparisons pinned to a sky position, date and band |
| Packets | Evidence exported in the form the receiving body accepts (Minor Planet Center, AAVSO, Backyard Worlds). The finder sends it |

### 6.6 Proof

- A report card with every test against the five targets and the methods, its pass mark (fixed before any result), the measured value, and pass or fail. Failures are published with their measured value.
- Recovery curves showing how faint a moving object the tool can find.
- Stated limits, with sources.
- What comes next.
- Data sources and credits.

### 6.7 Community

- Accounts for members. Guests can see everything.
- XP measures effort. Reputation measures accuracy on known-answer cases and settled forecasts. The two are separate.
- Classes follow the stellar spectral sequence O, B, A, F, G, K, M, then the brown dwarf classes L, T, Y. Members start hot and bright and progress toward the coldest objects the project hunts. WISE 0855 is a Y dwarf.
- Achievements tied to real skills: First Light, Blink Comparator, Dipole, Methane Line, Ice Line, Cosmic Ray, Crowded Field, Deep Field, Mira, Second Opinion.
- Minigames on real data: Blink (tap the mover), Spectrum Match, Signal or Noise.
- No all-time global leaderboard.

## 7. Truths the design must keep

These protect the science and the judges' trust. They say nothing about how anything looks.

1. Never invent a number shown as real. Where the pipeline has not produced a value yet, show it clearly as an example or show the honest empty state. Real data must never be confused with placeholders.
2. Nothing shown that does not work. In the shipped product a control is live or absent. Planned features belong under "Next".
3. Every number carries its unit and its origin. Origin is one of Measured, Catalogue, Estimated or Assumed, with an uncertainty where one exists. Coordinates are J2000 (ICRS).
4. Confidence words are fixed: under 50% Unclassified, 50 to 69% Possibly, 70 to 89% Probably, 90% and above Very likely. The word always appears with the number.
5. Some words are reserved. "Confirmed" appears only with an outside body's confirmation, and "Discovered" only after that. "Verified" is never used. Model output is always an "Estimate". Never "AI found" or "the AI thinks".
6. Molecule readings are feature strengths. The only composition percentage is an ice molecule as a share of water ice.
7. Every state is designed: loading with real stages, empty, partial, slow archive, and errors that name the next step.
8. It works with the server off. The five targets load from prepared files, and live mode fails gracefully.
9. It works for everyone: keyboard, screen readers, colour-blind users, phones, reduced motion, 4.5:1 text contrast.
10. It is fast. The named targets show their first image in under 3 seconds on a 4G phone.

## 8. The product's words

Consistent naming matters as much as visuals. These are the terms the product already uses. If you find a clearer word, propose it, and keep one word for one thing everywhere.

| Word | Means |
|---|---|
| Sky | the whole celestial sphere |
| Position | RA and Dec of a point |
| Field | a region fully processed |
| Frame | one SPHEREx exposure |
| Visit | all frames of one survey pass over a position |
| Detector | one of six, D1 to D6 |
| Band | one of 102 wavelength slices |
| Stack | frames added together |
| Source | any point of light |
| Spectrum | a source's brightness in each band |
| Feature | a dip or rise tied to a molecule |
| Signal | something a detector flagged, before checks |
| Case | a signal that passed every machine check |
| Check | one automatic test on a signal |
| Review | one member's answers on a case |
| Prediction | a locked statement of where a mover will be |
| Forecast | a member's probability that a prediction holds |
| Reputation | a member's accuracy score, 0 to 1 |

The verbs on buttons are Go to, Play, Pause, Stack, Difference, Remove known, Follow motion, Measure, Compare, Save view, Follow, Report, Review, Add evidence and Export.

## 9. Raw material you can use

- Real SPHEREx images. Scripts in `design/prototype/py/` read real frames from NASA's public archive and stack them per detector and visit for all five targets. Another script builds a wide false-colour image of a real SPHEREx field. You can rerun them, change them, or ask for other fields.
- Real numbers. On 14 Nov there were 3,917 SPHEREx frames across the five targets: WISE 0855 261, Barnard's Star 363, Epsilon Indi B 465, RW Aurigae 335, R Draconis 2,493. Catalogue values come from SIMBAD through CDS Sesame.
- NASA and mission heritage you may draw on: the SPHEREx mission, the 1975 NASA Graphics Standards Manual, mission patches, the blink comparator. Use real NASA imagery only under its usage rules, and never present NASA's logo as ours.
- The science. `docs/PROJECT-CONTEXT.md` explains every method, test and decision. `docs/DATA-LINKS.md` lists every data source.

## 10. Make it unmistakably designed by a person

The owner wants an interface that feels made with intent: precise, beautiful, alive and specific to this subject. Polished, with motion and texture, and nothing that looks generated. Some encouragement toward that follows.

Start from the subject. Space is about darkness and the light measured in it, about time, distance, cold, motion too slow to see, and things hidden in plain sight. SPHEREx adds rainbow filters, 102 bands, six detectors, an orbit and a sky scanned twice a year. "Phantom" adds what is there and unseen. There is far more here than any template holds.

Make choices you can explain. Every colour, typeface, shape and motion should have a reason tied to this project. If a choice is simply what usually comes first, look again.

Know the defaults that read as AI-made, and avoid them unless you choose them on purpose:

- untouched component-library styling, with stock grey cards, stock radius and stock spacing
- a purple or indigo accent, and purple-to-blue gradients
- gradient-filled headlines
- glow added everywhere without a reason
- emoji used as icons
- the same large radius on everything, and pill buttons everywhere
- the centred hero with two buttons, followed by three identical feature cards
- the "tasteful default" of a cream background, a serif display face and a sage green accent
- Inter or Geist as the only typeface, picked by habit
- a fade-in on every section and a hover-grow on every card
- filler copy such as "Transform your..." or "Unleash..."

Let real data be the visual. Real SPHEREx pixels, real spectra, real positions and real motion are more striking than any stock art of planets.

Give motion a meaning: a mover moving, light sweeping across bands, a prediction settling. Then make it smooth and keep it light.

Sweat the details. Align to a grid, keep one spacing scale, match edges, design every state, handle long names and big numbers, and consider phone and desktop from the start.

Look at real work: space agencies, observatories, scientific instruments, mission control, star charts, print design. Learn the pattern and never copy a brand.

Check the result. Look at it rendered, at phone and desktop widths, and by keyboard. If the `unslop-ui` and `unslop-text` scanners are available (https://github.com/JCarterJohnson/vibecoded-design-tells), run them.

Surprise us. Then make it work.

## 11. What the build team needs back

Whatever form suits your process: a coded prototype, design files, or both. The Web lane will build the real app in `web/` with Vite, React and TypeScript, hosted as a static site, with an initial script budget of 300 kB gzipped (Aladin Lite excluded). Note any library or font you rely on and its licence (BSD, MIT, Apache-2.0 or OFL are fine).
