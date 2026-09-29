# Deployment and operations

Start from the repository root unless a command states otherwise. Python 3.12 and Docker Engine / Compose v2 are required; Docker Desktop must use Linux containers. Native frontend development needs Node >=22.12; the Docker frontend uses Node 22.16. PostgreSQL is pinned to 17.6.

The verified real setup used Docker Desktop Linux / WSL2, CPU inference, 20 allocated CPU and 11.54 GiB Docker RAM. It is a measured setup, not a guaranteed minimum. Reserve several gigabytes for weights plus images, audio and database storage. GPU and native Windows full inference have not been validated. See [verification](VERIFICATION.md) for limits and observations.

## Local application with explicit mock AI

```bash
python scripts/init_env.py
docker compose --profile mock config --quiet
docker compose --profile mock up -d --build
docker compose exec api python -m app.manage create-user --email owner@example.test --name Owner
```

Use `py -3.12` on Windows or `python3.12` on Linux when needed. The script creates fresh database and internal-service secrets in `.env`; it refuses to overwrite existing configuration. The account command prompts for a password of at least 12 characters. Open [localhost:8088](http://localhost:8088). Mock AI returns labelled demonstration output, not transcription.

Root Compose uses project name `ai-meeting-minutes`. It publishes only the web port, bound to `127.0.0.1`. PostgreSQL, AI and Ollama stay on the container network. Database, audio and model volumes persist across ordinary restarts. Do not delete volumes to repair a configuration error.

If another application already uses port 8088, set both `WEB_PORT` and `FRONTEND_ORIGIN` in the root `.env` to the selected port before starting. Keep the browser hostname consistent with the configured origin.

## Real AI with root Compose

The following steps are for a fresh installation. They do not reuse another checkout's standalone bind-mounted model cache. Reuse an existing installation through the separate helper section below when appropriate.

1. Create root `.env` with `scripts/init_env.py` if it does not exist.
2. Accept the access conditions for [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0). Supply a Hugging Face read token with access to both repositories for the download step.
3. Build the ML image and prepare Qwen:

```bash
docker compose -f compose.yml -f compose.real.yml --profile real build ai-real
docker compose --profile real up -d ollama
docker compose exec ollama ollama list
docker compose exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
```

If the exact model is already present, skip the pull. Compose provides Ollama; no host installation is necessary.

4. Set `HF_TOKEN` in the current shell without putting its value in command arguments or tracked files. PowerShell 7 supports hidden input:

```powershell
$env:HF_TOKEN = Read-Host 'Hugging Face token' -MaskInput
```

For Bash:

```bash
read -rs HF_TOKEN
export HF_TOKEN
```

Download the model cache into the named volume:

```bash
docker compose --profile real run --rm --no-deps -e HF_TOKEN -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 ai-real python scripts/download_models.py --model-dir /models
```

The script downloads Faster Whisper large-v3, Pyannote speaker-diarization-3.1, segmentation-3.0 and wespeaker-voxceleb-resnet34-LM. It opens the Pyannote pipeline to check its dependencies. Only weights and cache metadata are needed for inference; do not copy Hugging Face login files into the cache.

5. Remove the token from the shell (`Remove-Item Env:HF_TOKEN` in PowerShell, `unset HF_TOKEN` in Bash), then switch profiles:

```bash
docker compose --profile mock stop ai-mock
docker compose -f compose.yml -f compose.real.yml --profile real up -d --build
docker compose exec api python -m app.check_ai
```

Mock and real AI must not run together under the `ai` network alias. The real override requires real results on the API / worker side. There is no automatic mock fallback.

Root real Compose sets CPU / int8, CPU diarization, `LOW_MEMORY_MODE=1`, `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. ASR / diarization offline loading was verified with networking disabled and no HF token. Application services still need their local container network, including Ollama at `http://ollama:11434`.

## Reuse a prepared local stack

`scripts/local_real.py` supports the original split installation: an `ai-service` Compose project with a bind-mounted `ai-service/models` directory, and an `exit1-real` application project joined to its network. **A fresh public clone has no models in that directory.** Do not run this helper against an unrelated existing project with those names.

For a newly prepared standalone installation, copy the AI example to `ai-service/.env` once, set a matching internal token in the process environment when starting manually, and prepare the downloads:

```bash
docker compose -p ai-service --env-file ai-service/.env -f ai-service/docker-compose.yml --profile download run --rm --build hf-model-init
docker compose -p ai-service --env-file ai-service/.env -f ai-service/docker-compose.yml --profile download run --rm ollama-model-init
```

Use the hidden `HF_TOKEN` setup above for `hf-model-init`, then remove it. The standalone example uses host Ollama port 11435; the internal container port remains 11434. Keep `LOW_MEMORY_MODE=1` for the documented CPU setup.

Once weights and Qwen are present:

```bash
python scripts/local_real.py check
python scripts/local_real.py start --build
python scripts/local_real.py status
docker exec -it exit1-real-api-1 python -m app.manage create-user --email owner@example.test --name Owner
```

`check` validates Compose configuration only; it is not a readiness or model-quality test. `start` creates a missing AI example configuration and generates secrets, or reuses its existing containers' credentials in process memory. It does not print or save credential values. Docker stores container environment values, so Docker access must be trusted.

The helper has fixed legacy project names, port 8088 and origin `http://localhost:8088`. Use root Compose for separately named or independently configured installations. Root named volumes and standalone bind mounts are different caches; do not accidentally download both.

For a temporary stop, wait for processing to finish and stop the helper's containers without removing them. A later `start` can reuse their configuration. If the database container was removed but its volume remains, supply the original `POSTGRES_PASSWORD` in the process environment; the helper refuses to invent a replacement password for an existing volume.

## Native development

Backend and AI both contain a Python package called `app`; use separate environments and working directories. Install locked dependencies:

```bash
python -m venv backend/.venv
python -m venv ai-service/.venv
```

In `backend`, use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Linux to install `-r requirements-dev.lock`. Do the same from `ai-service`. Run `npm ci` from `frontend`.

Copy the service `.env.example` files only if local files do not exist. Configure a private PostgreSQL instance, `DATABASE_URL`, `STORAGE_DIR`, `FRONTEND_ORIGIN=http://localhost:5173` and `COOKIE_SECURE=false`. Use a consistent absolute storage directory for API and worker. Alembic reads `DATABASE_URL` through application settings; its INI contains only a placeholder.

For native HTTP mock development, set backend `AI_MODE=http` / `AI_EXPECTED_MODE=mock` and AI `AI_MODE=mock`. Set one random 32+ character token as backend `AI_INTERNAL_TOKEN` and AI `INTERNAL_TOKEN`. Native AI needs `OLLAMA_URL=http://127.0.0.1:11434` only when real mode is used.

From the backend environment:

```bash
python -m alembic upgrade head
python -m app.manage create-user --email owner@example.test --name Owner
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Start `python -m app.worker` in a second backend terminal. From the AI environment, run `python -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000`. From `frontend`, run `npm run dev -- --host 127.0.0.1`. See the [frontend guide](../frontend/README.md) for proxy configuration.

## Readiness and failure handling

- `/health`: liveness only.
- AI `/ready`: requires the internal token; confirms initialized models and Ollama readiness.
- API `/ready`: checks database / migrations, writable storage, a recent worker heartbeat, AI readiness and compatible mode / limits.
- `docker compose exec api python -m app.check_ai`: safe service diagnostics without printing credentials.

Application logs include request or job IDs and stage durations, not transcript text or credentials. Infrastructure tools have their own log formats. Nginx uses Docker DNS to recover after API container IP changes.

The worker renews a 180-second lease every 15 seconds. Attempt fencing prevents stale workers from saving results. Transient network / server failures receive bounded backoff, up to three attempts. Invalid JSON, authentication failures and corrupt media are permanent errors. Retry is available only for eligible failed meetings; completed results cannot be overwritten by reprocessing.

One inference runs at a time. `LOW_MEMORY_MODE=1` unloads models between stages; Ollama uses one parallel slot, one loaded model, `keep_alive=0` and low-memory `num_batch=128`. Scaling workers requires separate testing because busy retries can exhaust attempts during another long meeting.

For diagnostics:

```bash
docker compose ps
docker compose logs --tail 100 api worker
curl http://localhost:8088/api/ready
```

## Backup and restore

Back up database and audio together while writes are stopped. Backups contain sensitive meeting data and password hashes; store them outside Git with restricted access. Use a new backup directory:

```bash
mkdir backup
docker compose stop web api worker
docker compose exec -T db pg_dump -U alem -d alem -Fc -f /tmp/alem-backup.dump
docker compose cp db:/tmp/alem-backup.dump backup/db.dump
docker compose cp api:/data/audio backup/audio
docker compose start api worker web
```

Keep a protected copy of configuration and the application revision. Avoid piping a binary dump through Windows PowerShell 5; `-f` and `docker compose cp` preserve bytes.

Restore only into a new isolated project, never over the live database. For a project name not already in use:

```bash
docker compose -p minutes-restore up -d db
docker compose -p minutes-restore cp backup/db.dump db:/tmp/restore.dump
docker compose -p minutes-restore exec -T db pg_restore -U alem -d alem /tmp/restore.dump
docker compose -p minutes-restore create api worker
docker compose -p minutes-restore cp backup/audio api:/data/audio
docker compose -p minutes-restore run --rm --no-deps --user root api chown -R appuser:appuser /data/audio
```

Set `WEB_PORT=8089`, `FRONTEND_ORIGIN=http://localhost:8089`, `APP_ENV=development` and `COOKIE_SECURE=false` in that shell, then start the isolated mock profile with `docker compose -p minutes-restore --profile mock up -d`. Check login, saved edits, audio Range requests and DOCX. Native restores must preserve original storage paths: the database stores absolute audio paths, so relocating storage requires an explicit migration.

The native harness has tested database restoration, audio byte equality and persisted edits; an earlier isolated container run also checked restore. Rehearse this procedure on the intended deployment environment before relying on it.

`python -m app.manage cleanup-storage` reports orphaned files; deletion requires `--apply` and has a minimum 24-hour safety interval. Back up first. Legacy ownerless meetings stay inaccessible until assigned explicitly with `assign-legacy`. Access-migration downgrade is prohibited; rollback requires a coordinated backup.

## Beyond local development

Use HTTPS, `APP_ENV=production`, `COOKIE_SECURE=true`, an exact HTTPS `FRONTEND_ORIGIN`, real AI and fresh credentials. Place an operator-managed TLS reverse proxy in front of the loopback web port. Accounts are created by the operator; team sharing is not implemented. Public hosting, firewall changes and production readiness are not part of the verified local setup.
