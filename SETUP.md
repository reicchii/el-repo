# Phantom Worlds: setup

Takes any teammate or coding agent from nothing to a working session. No step waits on a named person. Work that needs a login or a token is skipped, recorded in `docs/decisions.md`, and the session moves on.

| You want | Read |
|---|---|
| The rules | [`AGENTS.md`](AGENTS.md) |
| How work flows, from claiming a task to merge | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| The project | [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) |
| A link, file name, table or query | [`docs/DATA-LINKS.md`](docs/DATA-LINKS.md) |

## Contents

1. Get access
2. Choose where you work
3. Check your environment
4. Start a lane
5. More than one session on one machine
6. Secrets and tokens
7. One-time steps for the repository owner
8. Troubleshooting

---

## 1. Get access

1. The repository owner adds you as a collaborator (section 7).
2. To use Claude Code on the web, connect your GitHub account to Claude at https://claude.ai/connect-github. The Claude GitHub App must be installed on this repository, which the owner does once.

---

## 2. Choose where you work

All three routes run the same script, `scripts/bootstrap.sh`, so they end in the same state.

| Route | Good for | Watch out for |
|---|---|---|
| A. Claude Code on the web | Starting in a minute, several lanes in parallel, working from a phone | The container is temporary. Files in `data/` are gone when it is reclaimed, so large downloads repeat |
| B. GitHub Codespaces or a VS Code dev container | A full editor with every tool installed | Codespaces hours are limited by your GitHub plan |
| C. A terminal on your machine | Long jobs and large downloads that should stay on disk: SPLICES (3.1 GB), cube tiles (about 300 MB each), model training | You install the tools yourself |

### A. Claude Code on the web

Follow [`docs/cloud-environment.md`](docs/cloud-environment.md) once to create your own cloud environment. Then start a session on this repository with that environment selected.

### B. Codespaces or a dev container

- Codespaces: on the repository page choose Code, Codespaces, Create codespace on main.
- VS Code: open the folder and choose "Reopen in Container".

`.devcontainer/devcontainer.json` installs Python 3.12, uv, Node 22, pnpm 10 and Claude Code, then runs `scripts/bootstrap.sh`.

### C. A terminal on your machine

Install these once:

| Tool | Install |
|---|---|
| git | https://git-scm.com |
| uv (it installs Python 3.12 for you) | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, or see https://docs.astral.sh/uv/ |
| Node 22 | https://nodejs.org |
| pnpm 10 | `npm install --global pnpm@10` |
| Claude Code | `npm install --global @anthropic-ai/claude-code` |

Then:

```
git clone https://github.com/CapCayHambar/el-repo.git
cd el-repo
bash scripts/bootstrap.sh
claude
```

---

## 3. Check your environment

Run both in the repository root:

```
bash scripts/bootstrap.sh
bash scripts/check-network.sh
```

`bootstrap.sh` lists the tools it found and installs packages from the lockfiles once they exist. It ends with `Ready.` when nothing is missing.

`check-network.sh` probes every host in `scripts/hosts.txt`, then asks the IRSA archive for three table names. It ends with `Archive reachable.` when the archive answers. Two hosts are known to fail from scripts, and neither blocks work (section 8).

---

## 4. Start a lane

Lanes are areas of code. Any person or session can take any lane. They meet only at `contracts/`.

| Lane | Owns | Branch prefix |
|---|---|---|
| Engine | `engine/phantom/` except `ml/`, `api/`, `proof/`, `.github/workflows/weekly.yml` | `eng/` |
| ML | `engine/phantom/ml/`, `ml/` | `ml/` |
| Web | `web/`, `.github/workflows/deploy-web.yml` | `web/` |

1. Open [`prompts/1-session-start.md`](prompts/1-session-start.md), fill in the lane, and paste it into a new Claude Code session.
2. For the ML lane, paste [`prompts/6-ml-start.md`](prompts/6-ml-start.md) after it.
3. The session reads the rules, answers the comprehension questions, does the open checks that block its first tasks, and starts on the first free task in `docs/PROJECT-CONTEXT.md` section 12.

The other prompts:

| Prompt | Use it to |
|---|---|
| [`prompts/2-task.md`](prompts/2-task.md) | run one task |
| [`prompts/3-review.md`](prompts/3-review.md) | review another lane's pull request |
| [`prompts/4-wording-pass.md`](prompts/4-wording-pass.md) | check every interface string against the language, before the freeze review |
| [`prompts/5-failed-pass-mark.md`](prompts/5-failed-pass-mark.md) | handle a failed proof test |

Working without Claude Code is fine. The same rules, task order and pull request template apply.

---

## 5. More than one session on one machine

Give each session its own folder with git worktrees, so two sessions never share a working directory:

```
git worktree add ../pw-engine -b eng/start
git worktree add ../pw-ml -b ml/start
git worktree add ../pw-web -b web/start
```

Start one session in each folder. Cloud sessions and codespaces are already separate machines.

---

## 6. Secrets and tokens

Agents never create accounts and never see token values. Values go into GitHub secrets (repository Settings, Secrets and variables, Actions) and, for local runs, into a `.env` file that git ignores. `.env.example` lists the names.

| Name | Used by |
|---|---|
| `HF_TOKEN` | pushing data products and models to the Hugging Face Dataset repo, deploying the API Space |
| `HF_DATASET_REPO`, `HF_SPACE` | names of the Dataset repo and the Space |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | deploying the site to Cloudflare Pages |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | accounts and reviews, Tier C only |

If a token is absent, its job reports the missing name and stops. Everything else keeps working. Never paste a token into a chat, an issue or a pull request.

---

## 7. One-time steps for the repository owner

Only the owner's account can do these. Each is also listed in `docs/decisions.md` under "Needs outside action" until done.

1. **Add teammates.** Repository Settings, Collaborators, Add people.
2. **Install the Claude GitHub App** on this repository: https://github.com/apps/claude/installations/select_target
3. **Protect `main`.** Settings, Rules, Rulesets, New branch ruleset, target the default branch. Require a pull request before merging with 0 required approvals. Require the status checks `Repository rules`, `Python (engine, ML, API, proof)` and `Web`. Block force pushes. Keep approvals at 0 while sessions share one GitHub account, because an account cannot approve its own pull request.
4. **Merge settings.** Settings, General, Pull Requests: allow squash merging only, and turn on "Automatically delete head branches". `main` then gets one commit per task.
5. **Deploy tokens.** Create the Cloudflare and Hugging Face accounts and add the values of section 6 as GitHub secrets.
6. **Secret scanning with push protection**, at the latest when the repository goes public.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `check-network.sh` ends with `Archive NOT reachable` | This machine's network blocks IRSA. In a cloud session, the environment is missing the hosts in `docs/cloud-environment.md`. Otherwise work in a terminal on your own machine |
| A push or clone answers 403 in a cloud session | Claude has no write access. Do section 1 step 2 and section 7 step 2, then push again |
| `www.spaceappschallenge.org` gives no answer from scripts | The site sends a certificate chain that script tools do not trust. The challenge text is in `docs/PROJECT-CONTEXT.md` section 2 |
| `www.aavso.org` answers 403 to scripts | It runs a bot check. Try the VSX copy on VizieR (`B/vsx`, `[check]` once CDS answers) |
| SIMBAD, VizieR or Sesame answer "This page is currently unavailable" | CDS is partly down, as on 14 Nov. Sesame redirects to the mirror `vizier.idia.ac.za`, which answers. Follow redirects (`curl -L`) and keep the built-in table of named targets as the last fallback |
| A web-page reader is refused on IRSA or DESI folders | Those folders block robots. Use `curl`, `wget` or Python |
| TAP answers "QUERY must be set" | The URL encoding broke the query. Encode spaces as `+`, quotes as `%27`, `%` as `%25`, or use POST from code |
| TAP answers that the URL is too long | Use POST |
| A sync TAP query times out | The limit is 5 minutes. Use `/TAP/async` or a smaller region |
| The IRSA cutout service is slow or answers 503 | Expected under load. Read byte ranges of the full file instead (`docs/PROJECT-CONTEXT.md` section 8, stage 2) |
| A fact in the docs is marked `[check]` and the check fails | Record the result in `docs/decisions.md`, update `docs/PROJECT-CONTEXT.md` or `docs/DATA-LINKS.md`, and continue |
| A command with `rm -rf` is refused in Claude Code | `.claude/settings.json` blocks it on purpose. Delete single files, or ask a person |
| Codex cannot reach the network | `.codex/config.toml` turns network on inside its sandbox. If a setting seems ignored, pass it on the command line: `codex -c 'sandbox_workspace_write.network_access=true'` |
