# Phantom Worlds

[![CI](https://github.com/CapCayHambar/el-repo/actions/workflows/ci.yml/badge.svg)](https://github.com/CapCayHambar/el-repo/actions/workflows/ci.yml)

Phantom Worlds lets anyone search NASA's SPHEREx sky by the light each object gives off in 102 infrared bands, to find moving and unexplained objects that no catalogue lists yet, including in the crowded Milky Way.

Entry for NASA Space Apps Challenge 2026, challenge 12, "Planet X and SPHEREx". The build window closes Sun 15 Nov 2026 23:59 WIB.

## New here

1. Read this page, then [`AGENTS.md`](AGENTS.md).
2. Set up a place to work with [`SETUP.md`](SETUP.md). Three routes, one script.
3. Pick a lane and a task, and follow [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Find what you need

| You want to | Read |
|---|---|
| Know the rules every person and coding agent follows | [`AGENTS.md`](AGENTS.md) |
| Get a working environment | [`SETUP.md`](SETUP.md) |
| Claim a task, open a pull request, review, merge | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Understand the product, the methods and every decision | [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) |
| See the build plan and what is done | [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) section 12 |
| See who is working on what | the [open pull requests](https://github.com/CapCayHambar/el-repo/pulls) |
| Find a link, file name, table or query | [`docs/DATA-LINKS.md`](docs/DATA-LINKS.md) |
| See new decisions and what waits on outside action | [`docs/decisions.md`](docs/decisions.md) |
| Create your Claude Code cloud environment | [`docs/cloud-environment.md`](docs/cloud-environment.md) |

## What we are building

| Layer | Contents | Tier |
|---|---|---|
| Viewer | Any position plays as a time series. The five test targets and all eight optional considerations of the challenge | A, built first |
| Search and checks | Remove known, Search by light, molecule readings, type estimates with a stated confidence, machine checks, cases, the prediction check, searched depth | B |
| Community | Accounts, blind review, evidence, forecasts, reputation, games | C |

The tool gives readings and estimates. People decide what an object is.

## Repository layout

Folders marked with a task ID do not exist yet. That task creates them.

```
README.md          this page
AGENTS.md          rules for every person and coding agent
CLAUDE.md          loads AGENTS.md into Claude Code and adds its habits
SETUP.md           get a working environment
CONTRIBUTING.md    one task from claim to merge
LICENSE            Apache-2.0

docs/              PROJECT-CONTEXT.md   the product, decisions, methods, build plan, proof
                   DATA-LINKS.md        every link, file name, table name and query
                   decisions.md         new decisions, open check answers, needs outside action
                   ai-log.md            one line per task, for the AI-use statement
                   cloud-environment.md the Claude Code cloud environment
prompts/           prompts that start sessions, tasks and reviews
design/DESIGN-BRIEF.md  the brief for whoever designs the interface: the product, every capability, the truths to keep
design/prototype/  earlier UI experiments and the scripts that make real SPHEREx images for the design
scripts/           bootstrap.sh, check-network.sh, check-docs.py, hosts.txt

contracts/         JSON Schemas for data products, OpenAPI for the API, URL contract   (T02-E)
engine/            Python package `phantom`: archive access, cutouts, stacks,
                   photometry, spectra, features, detectors, checks, predictions, CLI   (T01-E)
engine/phantom/ml/ model features, inference, calibration, novelty checks              (T01-M)
ml/                training scripts, configs, reports, model cards                      (T01-M)
api/               FastAPI app. Imports `phantom`. No science code of its own           (T01-E)
web/               Vite + React + TypeScript single-page app                            (T01-W)
proof/             one script that produces every number on the Proof panel            (T01-E)
data/              local cache and downloads, git-ignored

.github/           CI, labels, pull request and issue templates
.devcontainer/     Codespaces and VS Code dev container
.claude/ .codex/   settings for Claude Code and Codex
```

## Lanes

Each lane owns a set of folders and a branch prefix. Lanes meet only at `contracts/`. Any person or session can take any lane.

| Lane | Owns | Branch prefix | Label |
|---|---|---|---|
| Engine | `engine/phantom/` except `ml/`, `api/`, `proof/`, weekly update | `eng/` | `lane: engine` |
| ML | `engine/phantom/ml/`, `ml/` | `ml/` | `lane: ml` |
| Web | `web/`, site deploy | `web/` | `lane: web` |

## Checks on every pull request

| Check | What it does | When it runs |
|---|---|---|
| Repository rules | AGENTS.md under 32 KiB, no secrets or data in git, agent configs parse, scripts pass ShellCheck, relative links resolve, a decisions line for any contract change | always |
| Python (engine, ML, API, proof) | `uv sync --locked`, `ruff check`, `pytest` | once `pyproject.toml` exists |
| Web | install, lint, test, build, and Playwright once configured | once `web/package.json` exists |
| Label by lane | adds the lane, `contracts`, `docs` and `ci` labels | always |

## Licence

Our code is Apache-2.0. See [`LICENSE`](LICENSE).
