# Phantom Worlds: UI prototype

The interface design has moved to a fresh start from [`../DESIGN-BRIEF.md`](../DESIGN-BRIEF.md). The owner judged the look of this prototype not good enough, so treat it as an experiment. Its scripts in `py/` remain useful: they make real SPHEREx images and data for any new design.

The interface for the whole product, built as one page so the team can see, test and change it before the engine, the API and the models exist. Open [`phantom-worlds.html`](phantom-worlds.html) in a browser, or view the published copy at https://claude.ai/artifact/XYhEy7thRQMip1pWQLTQUR.

The Web lane builds the real app in `web/` from this design. The prototype is a reference and a placeholder. It is not the product code.

## Views

| View | What it shows |
|---|---|
| Home | The purpose, WISE 0855 blinking between two visits in detector 6, the five test targets, what you can do |
| Viewer | Play, Difference, Stack, Visits as colour, Compare detectors. Observation matrix, marks, Gaia DR3 overlay, cursor readout. Guided tour |
| Source details | Catalogue readings, spectrum, molecule readings, the type estimate with its three results (molecule readings alone, spectrum alone, all data) |
| Search by light | Feature presets, S/N and blend filters, results by priority |
| Signals and cases | Case states, machine checks, the prediction check, blind review |
| Proof | Every test from `docs/PROJECT-CONTEXT.md` section 13 with its fixed pass mark |
| Member | XP, reputation, classes O to Y, achievements |

## Real data and example values

Real, read from the archives on 14 Nov 2026:

- Positions, motion, parallax and types of the five targets (CDS Sesame, SIMBAD).
- Every SPHEREx frame of each target (IRSA TAP), with the wavelength at the target read from each file.
- Image stacks per detector and visit, from 3,912 frames read by byte range from the public S3 bucket.
- The Gaia DR3 overlay (IRSA TAP).
- Pass marks, stated limits and credits, read from `docs/PROJECT-CONTEXT.md` at build time.

Example values, until the pipeline and the models produce real ones: the spectrum, molecule readings, type estimates, search results, cases and the member profile. Each such panel carries an `Example values` tag.

The stacks use a simplified method: ZODI subtracted, IRSA's rejected flag bits at zero weight, frames reprojected to a 3.075″ grid, clipped mean per detector and visit. Positions use proper motion only. Alignment to Gaia (T06) and PSF fits come with the engine.

## Concept: the survey instrument

SPHEREx maps the sky by sweeping it through a rainbow filter, so the interface borrows the instrument's own language, joined with NASA's design heritage and the patterns that strong space interfaces share.

| Element | Where it comes from |
|---|---|
| Spectral rule: a hairline in the six detector colours, violet to red | The detectors in wavelength order. Marks the top bar, active tabs, section labels and progress |
| Real sky behind the hero, slowly drifting | A 1.1° false-colour composite of the Barnard's Star field from 42 SPHEREx frames (`py/make_hero.py`) |
| RA and Dec grid with coordinate labels over that sky | Computed from the field's real centre and pixel scale |
| Survey scan line sweeping across the hero | How SPHEREx scans the sky |
| Earth's limb along the bottom of the hero | SPHEREx observes from low Earth orbit |
| Mission patch, registration marks, mission plate footer | The NASA Graphics Standards Manual (Danne and Blackburn, 1975): unity and technical precision |
| Wide uppercase titles (Unbounded), big numbers with units | Common to the space and NASA web designs reviewed on Pinterest |
| Eyepiece views: each target in a circle with crosshair ticks | How a telescope frames the sky. Each thumbnail is exposed to its own target's peak |
| Reticle corners that close in on hover | A finder locking onto a target |

Motion uses transform and opacity only, pauses off-screen and stops under reduced motion. Measured with every animation running, in a renderer with no GPU: 44 frames per second at 1440 px, 61 at 390 px.

## Design decisions

| Choice | Reason |
|---|---|
| A dark, neutral surround | Images need a surround that does not tint what the eye sees |
| Accent `#9db8ff` | The colour of a B-type star |
| Warm `#ff9a52` only for uncatalogued sources, signals and cases | The infrared end of the spectrum |
| Detector colours violet to red | Wavelength order, D1 to D6 |
| Atkinson Hyperlegible Next and Mono for text and readings | Designed by the Braille Institute so I, l, 1 and O, 0 never mix, which matters in designations and coordinates. Mono for every reading, so digits line up |
| Unbounded for wide titles, Bricolage Grotesque for headings | Presence for the product name and section titles, as in the space references |
| Radius 8 to 14 px, layered panels, grain, soft glow on the hero panel only | The owner asked for a cinematic, polished look with motion and texture |
| Separate views with a top bar | The owner asked for the best fit over the single-surface rule of section 10.1 |

The page passes the `unslop-ui` and `unslop-text` scanners from https://github.com/JCarterJohnson/vibecoded-design-tells with no findings. Lines that are deliberate choices carry `unslop-ignore` with the reason: the astronomy term "spectral" (it matches the scanner's rule for the serif font Spectral), the spectral rule, the Earth limb glow, the hero panel glow and two pill shapes.

## Rebuild

From this folder, with Python 3.12 and network access to IRSA, CDS and the S3 bucket:

```
uv venv .venv && uv pip install --python .venv astropy numpy reproject fsspec aiohttp requests
.venv/bin/python py/fetch_targets.py
for t in wise0855 barnard epsindib rwaur rdra; do .venv/bin/python py/stack_target.py $t; done
.venv/bin/python py/make_hero.py barnard --dets 1,3,6
.venv/bin/python py/build.py ../../docs/PROJECT-CONTEXT.md phantom-worlds.html
```

Downloads go to `data/`, which git ignores. R Draconis has 2,493 frames and takes about 9 minutes. The other targets take one to two minutes each.

To change the design, edit `template.html` and run only the last command.
