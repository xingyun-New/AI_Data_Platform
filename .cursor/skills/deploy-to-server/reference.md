# Deploy-to-Server Reference

Troubleshooting and manual recovery commands. Used when `scripts/deploy.ps1` fails mid-flight.

## 1. `plink` / `pscp` not found

```
FAIL - plink.exe not found on PATH
```

**Fix (one of):**

```powershell
winget install PuTTY.PuTTY
# or download: https://www.putty.org/
# then re-open PowerShell so PATH refreshes
```

Verify:

```powershell
Get-Command plink.exe, pscp.exe
```

## 2. Host key verification failed

Symptom: first-ever connection to a new server exits immediately with
`The server's host key is not cached in the registry.`

The deploy script passes `y` on the first `plink` call to auto-accept. If that
was interrupted, manually cache the key once:

```powershell
echo y | plink.exe -ssh -pw "<password>" -P 22 user@host "exit"
```

## 3. `sudo: a password is required`

The script assumes the login password and the sudo password are identical
(typical for `sudo` configurations that prompt the user's own password). If
sudo is configured differently you will see `sudo: a password is required`.

**Options:**
- Add the user to a passwordless sudoers rule (server admin):
  ```
  mci-edpadmin ALL=(ALL) NOPASSWD: /bin/mkdir, /bin/chown
  ```
- Or pre-create the target directory once as root, then rerun the skill:
  ```bash
  sudo mkdir -p /var/opt/AI_Data_Platform
  sudo chown -R mci-edpadmin:mci-edpadmin /var/opt/AI_Data_Platform
  ```

## 4. `permission denied while trying to connect to the Docker daemon socket`

The login user is not in the `docker` group. The deploy script already falls
back to `sudo docker`. If you prefer groupless runs, add the user once:

```bash
sudo usermod -aG docker mci-edpadmin
# then log out / back in
```

## 5. Ports already in use (9000 / 8000 / 5432)

Check who holds the port:

```bash
sudo ss -ltnp | grep -E ':9000|:8000|:5432'
```

Stop the conflicting service or edit port mappings in
`/var/opt/AI_Data_Platform/docker-compose.yml` before re-running deploy.

## 6. docker build fails on the backend image

Common causes:

- Out of disk: `df -h /var/lib/docker`
- Transient pip/apt mirror issue: rerun `-Mode update`
- Corrupted build cache:
  ```bash
  cd /var/opt/AI_Data_Platform
  docker compose down
  docker builder prune -f
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
  ```

## 7. Backend container exits immediately

```bash
docker logs ai_data_platform_backend --tail 200
```

Most frequent causes:
- Missing / malformed `backend/.env` — regenerate with `-Mode fresh`
- Database not reachable — ensure `db` container is `healthy`:
  ```bash
  docker inspect --format='{{.State.Health.Status}}' ai_data_platform_db
  ```

## 8. Frontend returns 502 / cannot reach backend

Nginx inside the `frontend` container proxies to the `backend` service name on
the internal compose network. Check:

```bash
docker exec ai_data_platform_frontend wget -qO- http://backend:8000/docs | head -c 200
```

If that fails, the backend is unhealthy — see section 7.

## 9. Manual rollback (previous working revision)

```bash
cd /var/opt/AI_Data_Platform
git log --oneline -n 10            # pick a known-good commit SHA
git reset --hard <sha>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 10. Full teardown (re-start from zero)

**Warning: destroys database volume.**

```bash
cd /var/opt/AI_Data_Platform
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
sudo rm -rf /var/opt/AI_Data_Platform
# then re-run the skill with -Mode fresh
```

## 11. View service status quickly

```bash
cd /var/opt/AI_Data_Platform
docker compose ps
docker compose logs -f --tail 50 backend
docker compose logs -f --tail 50 frontend
docker stats --no-stream
```

## 12. Updating only the `.env` without redeploying code

```bash
cd /var/opt/AI_Data_Platform
nano backend/.env          # or nano .env
docker compose up -d       # recreates containers whose env changed
```

## Script layout reference

```
.cursor/skills/deploy-to-server/
├── SKILL.md           # agent-facing instructions
├── reference.md       # this file
└── scripts/
    ├── deploy.ps1     # main entry point
    └── gen_env.ps1    # interactive secret collector (called by deploy.ps1)
```

## Parameter cheat sheet

```powershell
# Full fresh deploy
./scripts/deploy.ps1 -ServerHost 172.24.122.176 -Username mci-edpadmin `
    -Password 'Mci1001' -Mode fresh

# Routine code update (no secret prompts)
./scripts/deploy.ps1 -ServerHost 172.24.122.176 -Username mci-edpadmin `
    -Password 'Mci1001' -Mode update

# Deploy a feature branch to a different directory
./scripts/deploy.ps1 -ServerHost 172.24.122.176 -Username mci-edpadmin `
    -Password 'Mci1001' -Branch feature/xyz -TargetDir /var/opt/AI_Data_Platform_staging -Mode fresh
```
