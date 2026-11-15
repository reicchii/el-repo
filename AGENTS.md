# Phantom Worlds: rules for every coding agent

This file is the shared rulebook. Claude Code reads it through `CLAUDE.md`. Codex reads it directly. Keep it under 32 KiB. The project is described in `docs/PROJECT-CONTEXT.md`. Every link is in `docs/DATA-LINKS.md`.

## 1. What this project is

Phantom Worlds is an entry for NASA Space Apps 2026, challenge 12, "Planet X and SPHEREx". It is a public web tool that shows NASA SPHEREx images of any patch of sky as a time series, so anyone can see what moves or changes. On top of that viewer it lets people search sources by the light they give off in 102 bands, removes every known star to expose what is left, reads molecule features, estimates the most likely object type with an honest confidence, and checks each leftover by machine before people review it.

The build window closes Sun 15 Nov 2026 23:59 WIB (16:59 UTC). Judges read the project page and open the live site.

The project is self-contained. No step waits on a named person, and nothing depends on an outside party answering.

## 2. Hard rules

1. **Time.** Run `date -u` at the start of every session. After the freeze review (`docs/PROJECT-CONTEXT.md` section 12.9) only fixes go in.
2. **Never invent a fact.** Archive column names, file paths, URL layouts, band edges, catalogue values and library behaviour are looked up or measured. If a doc marks something `[TO CHECK]` or `[check]`, check it first. If you cannot check it, record that and take the next task.
3. **Never invent a number shown to users.** Every value on screen comes from data or from a cited source. No sample data, no placeholder rows, no lorem ipsum, no fake accounts.
4. **Nothing shown that does not work.** A control is live or absent. No disabled buttons that hint at future features. Planned features appear only on the Proof panel under "Next".
5. **Follow the language.** Every label, message and identifier that reaches the interface uses the terms, verbs and formats in `docs/PROJECT-CONTEXT.md` section 5. Do not coin synonyms.
6. **Contracts are fixed.** Files under `contracts/` change only with a line in `docs/decisions.md` and a matching change on both sides in the same pull request.
7. **Tier order is the default, not a wall.** Work in the order of `docs/PROJECT-CONTEXT.md` section 12. The five test targets and the objective come first. If a later item is cheap and makes the objective stronger, or a resource offers a better route, log it in `docs/decisions.md` and do it.
8. **Licences.** Allowed: BSD, MIT, Apache-2.0, LGPL as a separate library (Aladin Lite v3). Do not use The Tractor (GPL-2) or tractorjax-spherex (GPL-3). Check every new library's licence before adding it. Our code is Apache-2.0.
9. **Secrets.** Never create accounts. Never read, print, log or commit a token. Tokens live in GitHub secrets and in local `.env` files that are git-ignored. Never ask anyone to paste a token into a chat.
10. **No outside contact.** Do not email, post, or open issues on other projects. Do not submit anything to registries or science teams.
11. **Honest wording.** "Confirmed", "discovered" and "verified" are reserved words. Model output is always an "estimate". Molecule readings are feature strengths. The only composition percentage shown is an ice molecule as a percentage of water ice.
12. **AI log.** After each task append one line to `docs/ai-log.md`: date, agent, lane, task ID, files touched.
13. **Data.** Downloads go to `data/`, which git ignores. Record name, size, checksum and source URL in `data/manifest.csv`. Download with code (`curl`, `wget`, Python). Some archive folders block web-page readers.
14. **Independence.** Do not wait on people. If a step needs a login, a token or an outside answer, skip it, add it to "Needs outside action" in `docs/decisions.md` with what it would unblock, and continue with the next task.

## 3. Read before you work

| When | Read in `docs/PROJECT-CONTEXT.md` |
|---|---|
| Every session | this file, sections 1, 4 and 12 |
| Any task that puts words or numbers on screen | sections 5 and 10 |
| Any task in `engine/`, `api/`, `proof/` | sections 7 and 8 |
| Any task that touches a test target | section 6 |
| Any model, classification, molecule reading or training data work | section 9, plus `docs/DATA-LINKS.md` sections 6, 7, 11, 12 |
| Any validation or report card work | section 13 |
| Any archive access, file layout or flag | section 14, plus `docs/DATA-LINKS.md` |
| Accounts, review, reputation, games | section 11 |
| Why something is the way it is | sections 3 and 15 |

Setting up a place to work: `SETUP.md`. One task from claim to merge: `CONTRIBUTING.md`.

## 4. Repository layout

```
AGENTS.md  CLAUDE.md  SETUP.md  CONTRIBUTING.md  README.md  LICENSE
docs/        PROJECT-CONTEXT.md, DATA-LINKS.md, decisions.md, ai-log.md, cloud-environment.md
prompts/     prompts that start sessions and tasks
scripts/     bootstrap.sh (tools and packages), check-network.sh and hosts.txt (hosts we call), check-docs.py
contracts/   JSON Schemas for data products, OpenAPI for the API, URL contract
engine/      Python package `phantom`: archive access, cutouts, registration, stacks,
             photometry, spectra, features, detectors, checks, predictions, searched map, CLI
engine/phantom/ml/   model features, inference, calibration, novelty checks
ml/          training scripts, configs, reports, model cards
api/         FastAPI app. Imports `phantom`. No science code of its own
web/         Vite + React + TypeScript single-page app
proof/       one script that produces every number on the Proof panel
data/        local cache and downloads, git-ignored
.github/workflows/   CI, deploy, weekly update
.devcontainer/       Codespaces and VS Code dev container
```

## 5. Lanes

| Lane | Owns | Branch prefix |
|---|---|---|
| Engine | `engine/phantom/` except `ml/`, `api/`, `proof/`, `.github/workflows/weekly.yml` | `eng/` |
| ML | `engine/phantom/ml/`, `ml/` | `ml/` |
| Web | `web/`, `.github/workflows/deploy-web.yml` | `web/` |

Any session can take any lane. Lanes meet only at `contracts/`. Each session works in its own branch, and in its own git worktree when sessions share a machine. A session on another lane reviews each pull request with `prompts/3-review.md` before merge.

Claim a task before you write code. Check the open pull requests, then open a draft pull request named `<ID> <what it does>`. An open pull request with that task ID means the task is taken.

A cloud session may be given its branch name by its tool, such as `claude/...`. Keep that name. The lane label comes from the paths the pull request changes.

## 6. Tooling and commands

Python 3.12 with `uv`. Lint with `ruff`. Tests with `pytest`. Node LTS with `pnpm`. TypeScript strict. Tests with `vitest`, end-to-end with Playwright.

Commands, created in tasks T01 and kept with these names:

```
uv run ruff check . && uv run pytest            # engine, ml, api, proof
uv run phantom --help                           # pipeline CLI
uv run python ml/train.py --help                # model training
uv run python proof/run.py                      # writes proof/report.json and proof/report.md
pnpm -C web lint && pnpm -C web test            # web
pnpm -C web build                               # must stay under the size budget
pnpm -C web e2e                                 # Playwright on the five targets
```

Commands that work today:

```
bash scripts/bootstrap.sh                       # checks the tools, installs packages from the lockfiles
bash scripts/check-network.sh                   # shows which archive hosts this machine reaches
python3 scripts/check-docs.py                   # relative links in the docs resolve
```

CI runs on every pull request from `.github/workflows/ci.yml`. Lanes extend that file and do not add a second CI workflow. A new host goes into `scripts/hosts.txt` in the pull request that first calls it.

## 7. Definition of done for any task

1. The acceptance check in the build plan passes, and its output is pasted in the pull request.
2. Lint and tests pass in the lane.
3. Every string added to the interface matches the language. Every number has a unit and an origin label.
4. Loading, empty, partial and error states exist for anything that fetches.
5. No new dependency without a one-line reason and its licence in the pull request.
6. The build plan checkbox is ticked and the AI log has its line.

## 8. Engineering rules

- One code path. The API, the pipeline and model inference call the same `phantom` functions, so live results and precomputed results match.
- The site works with the API switched off. Showcase targets and fields load from static data products.
- Every data product carries `data_as_of`, `pipeline_version` and its source file list. Every model output carries `model_version`.
- Network calls from the API go only to an allowlist of hosts. Inputs are validated. Responses are cached by request.
- Read only the bytes you need from archive files (HTTP range). Never use the IRSA cutout service on the live path.
- Like with like. Never blink, subtract or compare two images whose band ranges differ.
- Positions of catalogued sources are moved to each frame's date with proper motion and parallax before any match or overlay.
- Pixels with IRSA's rejected flag bits get zero weight in every fit and stack. Bit 21 marks a pixel on a known source and is never masked.
- Science wavelengths come from `CWAVE` and `CBAND`, never from hardcoded band edges.
- Models: test split by sky tile, gold labels only in the test set, scores per brightness bin, release gate in `docs/PROJECT-CONTEXT.md` section 9.9. A model that fails the gate is not published.
- Molecule readings first. The type model stores three results per source: molecule readings alone, spectrum alone, all data. Every estimate carries its feature contributions (`docs/PROJECT-CONTEXT.md` sections 3.11 and 9.6).
- Small pull requests. One task per pull request. Commit messages in the imperative, task ID first: `T12 add visit stacks`.
- When a pass mark fails, report the measured value. Do not tune a threshold to make it pass.

## 9. When you are stuck

Stop after two failed attempts at the same step. Write in the pull request or in `docs/decisions.md` what you tried, what you saw, and the smallest question that would unblock it. Then move to the next unblocked task. Do not guess around an unknown archive detail, and do not swap in fake data to keep going.

## 10. The plan serves the project

The docs are a starting point and wrong somewhere. When the data, a tutorial or a test shows a better way, take it.

- Propose improvements freely: a faster data route, a clearer control, a stronger check, a new idea that uses SPHEREx's bands. State the gain and the cost in two lines.
- Small improvements inside your task: do them and note them in the pull request.
- Changes to scope, contracts or wording rules: write them in `docs/decisions.md`, update `docs/PROJECT-CONTEXT.md`, then build.
- Open the resource pages yourself. Do not rely only on the summaries.
- What stays fixed: never invent facts or numbers, nothing shown that does not work, licences, secrets, no outside contact, honest wording.

## 11. Links to open first

Full list: `docs/DATA-LINKS.md`.

- Challenge: https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/
- IRSA SPHEREx pages: https://irsa.ipac.caltech.edu/Missions/spherex.html
- Tutorials: https://caltech-ipac.github.io/irsa-tutorials/spherex/
- Data access paths: https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access
- Explanatory Supplement v2.1: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf
- TAP: https://irsa.ipac.caltech.edu/TAP/sync
- SIA: https://irsa.ipac.caltech.edu/SIA
- Files: https://irsa.ipac.caltech.edu/ibe/data/spherex/
- Moving Object Search Tool API: https://irsa.ipac.caltech.edu/applications/MOST/MOSTProgramInterface.html
- WiseView: http://byw.tools/wiseview
