---
name: deploy-to-server
description: Deploy the AI_Data_Platform project to a remote Linux server via SSH (plink) + Docker. Clones the repo from GitHub into /var/opt/, generates backend/.env and root compose .env interactively, then runs docker compose up with the prod override and verifies container health. Use when the user asks to deploy, publish, release, 上线, 部署, 发布, 发布到服务器, or push the project to a server.
---

# Deploy to Server (SSH + Docker)

Automates remote deployment of **AI_Data_Platform** to a Linux server: pulls code from GitHub into `/var/opt/AI_Data_Platform`, builds & runs the full `docker-compose` stack (db + backend + frontend) with the production override, and verifies service health.

## Prerequisites

**Local machine (Windows PowerShell):**
- PuTTY tools installed and on `PATH`: `plink.exe`, `pscp.exe`
  - Download: https://www.putty.org/ — or `winget install PuTTY.PuTTY`
- PowerShell 5.1+ (Windows default) or PowerShell 7

**Remote server (Linux):**
- `git`, `docker`, `docker compose` (v2 plugin) installed
- Login user has `sudo` rights (needed only for initial `/var/opt/` chown)
- Ports **9000** (frontend), **8000** (backend API) open
- Port **5432** (Postgres) only if external DB access is required

## Parameters

| Parameter    | Required | Default                                                   | Example                |
| ------------ | -------- | --------------------------------------------------------- | ---------------------- |
| `Host`       | yes      | —                                                         | `172.24.122.176`       |
| `Username`   | yes      | —                                                         | `mci-edpadmin`         |
| `Password`   | yes      | —                                                         | `Mci1001`              |
| `Port`       | no       | `22`                                                      | `22`                   |
| `RepoUrl`    | no       | `https://github.com/xingyun-New/AI_Data_Platform.git`     | same                   |
| `TargetDir`  | no       | `/var/opt/AI_Data_Platform`                               | same                   |
| `Branch`     | no       | `main`                                                    | `main`                 |
| `Mode`       | no       | `auto`                                                    | `auto` / `fresh` / `update` |

**Mode semantics:**
- `auto`: detect — if `.git` exists on server → `update`, otherwise → `fresh`
- `fresh`: force re-clone (deletes existing `TargetDir`, regenerates `.env`)
- `update`: only `git fetch` + `reset --hard` + `docker compose up -d --build`; never touch `.env`

## Workflow

Copy this checklist and track progress:

```
Deploy Progress:
- [ ] Step 1: Collect parameters (prompt user if missing)
- [ ] Step 2: Verify plink.exe / pscp.exe are on PATH
- [ ] Step 3: Test SSH connectivity + accept host key
- [ ] Step 4: Verify remote git / docker / docker compose
- [ ] Step 5: Ensure TargetDir exists and is owned by login user
- [ ] Step 6: Clone (fresh) or fetch+reset (update) the repo
- [ ] Step 7: Generate backend/.env on remote (if missing or fresh)
- [ ] Step 8: Write root-level .env (DB_PASSWORD / SECRET_KEY / UNIFIED_PASSWORD)
- [ ] Step 9: mkdir data/raw data/redacted data/index
- [ ] Step 10: docker compose up -d --build (with prod override) + health check
```

### Step 1 – Collect parameters

If the user did not supply all required params, prompt for them **before** launching the script. At minimum you need `Host`, `Username`, `Password`.

### Step 2–10 – Run the deploy script

Execute the full workflow with:

```powershell
powershell -ExecutionPolicy Bypass -File .cursor/skills/deploy-to-server/scripts/deploy.ps1 `
    -ServerHost "172.24.122.176" `
    -Username "mci-edpadmin" `
    -Password "Mci1001" `
    -Port 22 `
    -RepoUrl "https://github.com/xingyun-New/AI_Data_Platform.git" `
    -TargetDir "/var/opt/AI_Data_Platform" `
    -Branch "main" `
    -Mode "auto"
```

The script chains all remote steps and exits non-zero on any failure. Watch the console output — each step is clearly labelled `[1/10] ...`, `[2/10] ...`, etc.

### First-time secrets prompt

On `fresh` deployments the script internally calls `scripts/gen_env.ps1` which will **interactively** ask for:

- `DASHSCOPE_API_KEY` (required)
- `UNIFIED_PASSWORD` (login password for the platform UI; default `admin123`)
- `DIFY_API_KEY` / `DIFY_BASE_URL` / `DIFY_DATASET_ID` (required if using Dify)
- `INNOMATE_API_URL` (optional)
- `DB_PASSWORD` (Postgres password; auto-generated if left empty)
- `SECRET_KEY` (auto-generated random 48-byte hex if left empty)

Values are written **directly on the remote server** via SSH heredoc — nothing touches the local disk.

## Re-deployments (code updates)

For routine code-only updates (no secret changes), run with `-Mode update`:

```powershell
powershell -ExecutionPolicy Bypass -File .cursor/skills/deploy-to-server/scripts/deploy.ps1 `
    -ServerHost "172.24.122.176" -Username "mci-edpadmin" -Password "Mci1001" -Mode update
```

This skips Step 7–8 (env generation) entirely and only pulls the latest branch HEAD + rebuilds containers.

## Health Check Output

After startup, the script runs:

```bash
docker compose ps
curl -sf http://localhost:8000/docs
curl -sf http://localhost:9000/
```

Expected final output:

```
[10/10] Health check ...
  backend  : OK (http://172.24.122.176:8000/docs)
  frontend : OK (http://172.24.122.176:9000/)
  db       : running

Deployment finished successfully.
```

## Troubleshooting

If a step fails, consult [reference.md](reference.md) for:
- Host key / known_hosts issues
- `sudo` password prompts
- Port already in use (80 / 8000 / 5432)
- Docker build failures
- Manual rollback commands

## Security Notes

- **Password handling**: `Password` is passed to `plink.exe -pw`. It never gets written to disk or committed. On Windows it is visible in the parent PowerShell process command line — do not use this on shared / audited machines without compensating controls.
- **Idempotency**: `update` mode always does `git reset --hard origin/<branch>` — any manual edits on the server will be wiped.
- **`.env` protection**: existing `backend/.env` is **never overwritten** unless `-Mode fresh` is explicitly passed.
- **Root .env**: the root-level `.env` holds only compose-substitution secrets (`DB_PASSWORD`, `SECRET_KEY`, `UNIFIED_PASSWORD`) and is regenerated on `fresh` only.
