# Phantom Worlds: UI prototype

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

## Design decisions

| Choice | Reason |
|---|---|
| A dark, neutral surround | Images need a surround that does not tint what the eye sees |
| Accent `#9db8ff` | The colour of a B-type star |
| Warm `#ff9a52` only for uncatalogued sources, signals and cases | The infrared end of the spectrum |
| Detector colours violet to red | Wavelength order, D1 to D6 |
| Atkinson Hyperlegible Next and Mono | Designed by the Braille Institute so I, l, 1 and O, 0 never mix, which matters in designations and coordinates. Mono for every reading, so digits line up |
| Radius 4 and 6 px, no gradients, no glow | An instrument console, quiet around the images |
| Separate views with a top bar | The owner asked for the best fit over the single-surface rule of section 10.1 |

The page passes the `unslop-ui` and `unslop-text` scanners from https://github.com/JCarterJohnson/vibecoded-design-tells with no findings. Four lines carry `unslop-ignore`, because the astronomy term "spectral" matches the scanner's rule for the serif font Spectral.

## Rebuild

From this folder, with Python 3.12 and network access to IRSA, CDS and the S3 bucket:

```
uv venv .venv && uv pip install --python .venv astropy numpy reproject fsspec aiohttp requests
.venv/bin/python py/fetch_targets.py
for t in wise0855 barnard epsindib rwaur rdra; do .venv/bin/python py/stack_target.py $t; done
.venv/bin/python py/build.py ../../docs/PROJECT-CONTEXT.md phantom-worlds.html
```

Downloads go to `data/`, which git ignores. R Draconis has 2,493 frames and takes about 9 minutes. The other targets take one to two minutes each.

To change the design, edit `template.html` and run only the last command.
