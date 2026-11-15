@AGENTS.md

## Claude Code specifics

- The lane is given in the first message of the session. Use its branch prefix: `eng/`, `ml/` or `web/`.
- Before any change to `contracts/`, the photometry solver, the prediction check or a model release, write the plan in the pull request description and the line in `docs/decisions.md` first.
- For a task with a `[TO CHECK]` or `[check]` dependency, do the check first and record the answer in `docs/decisions.md` with the command or URL used.
- Download and query archives with Bash (`curl`, `wget`, `uv run python`). Web-page readers are blocked on some IRSA and DESI folders.
- For TAP from code, use POST with `QUERY`, `LANG=ADQL`, `FORMAT=csv`. List real columns from `TAP_SCHEMA.columns` before writing a query.
- Long jobs (cutouts, joint fits, training) run in the background with their log in `data/logs/`. Report the command and the log path, then keep working on the next task.
- When reviewing another lane's pull request, use `prompts/3-review.md` and report findings ordered by severity. Do not rewrite that code unless the review says to.
- Keep replies short: what changed, the acceptance check output, the next task.
