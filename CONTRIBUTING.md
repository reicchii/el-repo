# Phantom Worlds: how work flows

For every teammate and every coding agent. The rules are in [`AGENTS.md`](AGENTS.md). Setup is in [`SETUP.md`](SETUP.md). This file covers one task from start to merge.

## The loop

```
pick a task  →  claim it  →  build it  →  open for review  →  review by another lane  →  merge
```

### 1. Pick a task

Tasks and their order are in [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) section 12. Take the first unticked task in your lane that nobody has claimed.

### 2. Claim it

Look at the open pull requests first. A pull request whose title starts with a task ID means that task is taken.

Then, before writing code:

1. Create a branch from the latest `main`.
2. Push it and open a **draft** pull request titled `<task ID> <what it does>`, for example `T12 add visit stacks`.

The list of open pull requests is the team's board. Each one gets its lane label by itself.

| Work | Branch name |
|---|---|
| Engine task | `eng/<task id>-<short name>`, for example `eng/t05-cutouts` |
| ML task | `ml/<task id>-<short name>` |
| Web task | `web/<task id>-<short name>` |
| Docs or repository tooling | `docs/<short name>` or `ci/<short name>` |

A cloud session may be given its branch name by its tool, such as `claude/...`. Keep that name. The lane label then comes from the paths the pull request changes.

### 3. Build it

- One task per pull request. Keep it small.
- Write the test first where a test is possible.
- Commit messages in the imperative, task ID first: `T12 add visit stacks`.
- Never commit secrets, downloads or build output. `data/` and `.env` are git-ignored, and CI fails if they appear.
- A new dependency needs a one-line reason and its licence in the pull request.

### 4. Open it for review

Fill in the pull request template. It carries the definition of done from `AGENTS.md` section 7:

- the acceptance check output, pasted
- lint and test output, pasted
- the box ticked in `docs/PROJECT-CONTEXT.md` section 12
- one new line in [`docs/ai-log.md`](docs/ai-log.md)
- for any change under `contracts/`, a line in [`docs/decisions.md`](docs/decisions.md) and both sides changed in the same pull request

Mark the pull request ready for review when the checks are green.

### 5. Review

A person or session on **another lane** reviews it with [`prompts/3-review.md`](prompts/3-review.md) and posts the findings as a comment, ordered by severity, ending with `merge` or `do not merge`. The reviewer does not edit the author's files.

### 6. Merge

Merge on `merge`, with a squash merge, so `main` gets one commit per task. Delete the branch.

## Checks that run by themselves

| Check | What it does |
|---|---|
| Repository rules | AGENTS.md under 32 KiB, no secrets or data in git, agent configs parse, scripts pass ShellCheck, relative links in the docs resolve, a decisions line for any contract change, a reminder for the AI log line |
| Python (engine, ML, API, proof) | `uv sync --locked`, `ruff check`, `pytest`, once `pyproject.toml` exists |
| Web | install, lint, test, build, and Playwright once configured, once `web/package.json` exists |
| Label by lane | adds `lane: engine`, `lane: ml`, `lane: web`, `contracts`, `docs`, `ci` |

Lanes extend `.github/workflows/ci.yml`. They do not add a second CI workflow.

## Shared files

Three files are touched by almost every pull request. They are built to merge cleanly.

| File | How to edit it |
|---|---|
| `docs/ai-log.md` | Add one row at the end of the table. Never edit another row |
| `docs/decisions.md` | Add one line at the end of the right section. When an item under "Needs outside action" is done, move it to "Decisions" with the date |
| `docs/PROJECT-CONTEXT.md` | Tick your own task's box. Larger edits go with a line in `docs/decisions.md` |

`.gitattributes` tells git to keep both sides' lines in `docs/ai-log.md` and `docs/decisions.md`. If GitHub still reports a conflict there, run `git merge origin/main` in your branch. Git keeps both lines without help. Then push.

## Decisions, checks and blockers

- A new decision, an answer to a `[TO CHECK]` item, or a step that needs a login or a token goes in `docs/decisions.md`, with the command or URL used.
- When a decision changes the plan, update `docs/PROJECT-CONTEXT.md` in the same pull request.
- Stuck after two attempts at the same step: write what you tried and what you saw in the pull request, then take the next unblocked task.

## Stages of the build

- The Tier A gate (`docs/PROJECT-CONTEXT.md` section 12.5) decides when Tier B starts.
- [`prompts/4-wording-pass.md`](prompts/4-wording-pass.md) runs before the freeze review.
- The freeze review (section 12.9) runs before the project page is written. After it, only fixes go in.
- [`prompts/5-failed-pass-mark.md`](prompts/5-failed-pass-mark.md) runs on any failed proof test.

## Issues

Issues are optional. The forms cover three cases: a task someone wants tracked outside a pull request, an open check, and a bug. Never paste a token into an issue or a pull request.
