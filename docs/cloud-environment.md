# Phantom Worlds: cloud environment for Claude Code on the web

A cloud environment is the saved setup a Claude Code cloud session runs in: which hosts it may reach, a setup script, and secrets. Environments belong to an account, so **each teammate creates their own once**. It takes about two minutes.

Checked on 14 Nov 2026 in a session on this repository.

## What it must contain

| Setting | Value |
|---|---|
| Name | `el-repo` |
| Network access | Limited, with package managers allowed |
| Allowed hosts | the 21 hosts below |
| Setup script | the script below |
| Environment variables | none |
| Secrets | none to start with (see "Secrets") |

### Allowed hosts

Print the current list at any time with `bash scripts/check-network.sh --allowlist`. The purpose of each host is in `scripts/hosts.txt`.

```
irsa.ipac.caltech.edu
caltech-ipac.github.io
cds.unistra.fr
vizier.idia.ac.za
simbad.cds.unistra.fr
vizier.cds.unistra.fr
tapvizier.cds.unistra.fr
aladin.cds.unistra.fr
alasky.cds.unistra.fr
ssp.imcce.fr
ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca
gea.esac.esa.int
datalab.noirlab.edu
data.desi.lbl.gov
zenodo.org
huggingface.co
us.aws.cdn.hf.co
download.pytorch.org
arxiv.org
www.spaceappschallenge.org
www.aavso.org
```

The SPHEREx S3 bucket, GitHub, PyPI and npm need no entry. They are reachable with package managers allowed.

### Setup script

It runs each time a new container is built, after the repository is cloned. The steps live in the repository, so every environment runs the same ones and the script never goes stale.

```bash
#!/bin/bash
# Phantom Worlds. The steps live in the repository: scripts/bootstrap.sh
if [ -f el-repo/scripts/bootstrap.sh ]; then
  (cd el-repo && bash scripts/bootstrap.sh) || echo "setup: bootstrap reported a problem, run it in the session"
fi
```

The image already has git, uv, Python 3.12, Node 22, pnpm and Chromium for Playwright. A problem in the script never stops the session from starting.

## How to create it

**The short way.** Start a cloud session on this repository and send:

```
Read docs/cloud-environment.md and set up that cloud environment for me. Ask before saving.
```

Claude proposes the environment and you approve it on a card. Nothing is saved without your approval.

**By hand.** In Claude Code on the web, open the environment menu, add an environment, and enter the values above: network access Limited with package managers allowed, the hosts under Allowed domains, and the setup script. The current steps are at https://code.claude.com/docs/en/claude-code-on-the-web.

Then start a new session on this repository with that environment selected and run:

```
bash scripts/check-network.sh
```

## Secrets

Save none to start with. Deploys run in GitHub Actions and read GitHub secrets (`SETUP.md` section 6).

`HF_TOKEN` is needed in a cloud environment only when a cloud session itself publishes to the Hugging Face Dataset repo (task T12). Add it then as a network secret for `huggingface.co`. The network layer adds it to each request, so no agent ever sees the value. The upload hosts Hugging Face uses must also be allowed, and they are measured at the first push.

## What to expect

Measured on 14 Nov 2026:

| Host | Result |
|---|---|
| IRSA TAP | answers. `SETUP.md` section 3 check passes |
| SPHEREx S3 bucket | lists `dr1/`, `qr2/`, `qr3/` without an account |
| `vizier.idia.ac.za` | answers Sesame name lookups while CDS is partly down. Barnard's Star resolves with its Gaia DR3 position and motion |
| `us.aws.cdn.hf.co` | serves Hugging Face large files |
| `simbad.cds.unistra.fr`, `vizier.cds.unistra.fr` | connect, and answered CDS's own "currently unavailable" page on 14 Nov |
| `tapvizier.cds.unistra.fr` | connection reset by the server on 14 Nov |
| `www.spaceappschallenge.org` | fails certificate checks from scripts. The host is allowed, the site's certificate chain is the cause |
| `www.aavso.org` | answers 403 to scripts with a bot check |

## Limits of a cloud session

- The container is temporary. Anything in `data/` is gone when it is reclaimed. Keep large downloads and long training runs on a machine you control, or publish their outputs.
- Commit and push before you stop. Unpushed work is lost with the container.
- The project's `.claude/settings.json` blocks `rm -rf`.
