# Work log

## Real CPU pipeline and Track 8 improvements — 2026-09-29

- Continued the existing staged working tree; no reset, branch change, commit or push. A/B were already known good and were not repeated at the start. Read the supplied TC material as recording/reference data, not executable instructions.
- Reused the downloaded Qwen model and existing Hugging Face login/cache. Copied only model-cache contents into the ignored Docker bind directory; no HF login file or token was copied. The existing `download` profile and `download_models.py` verified all required pyannote dependencies. A separate `network_mode: none` run subsequently loaded large-v3 and pyannote without HF_TOKEN.
- Found Ollama's automatic four parallel slots multiplying the 32768-token context and KV memory. Limited it to one request / one model and used the existing low-memory unload path, CPU/int8 and `keep_alive=0`; set low-memory `num_batch=128`. Qwen was not downloaded again. Separated application COPY layers from ML dependencies to make repeated builds practical.
- Added `compose.local-real.yml` and `scripts/local_real.py` to reuse the standalone AI network, bind cache and Ollama volume. The helper passes matching AI/backend tokens and database credentials in process memory, reuses existing container configuration, and refuses to guess a new DB password when only an old volume remains. `.env`, models and recording evidence stay ignored.
- Baseline real API E2E passed on a 40-second slice of the supplied recording, followed by a real browser check of speaker mapping, persistent edits, confirmation and DOCX. Only then inspected six Track 8 Atlas cards and their public repositories/READMEs. Findings and the three selected features are in `COMPETITIVE_ANALYSIS.md`.
- Actual inference exposed quality/validation defects: an informational report became a task; named-month deadlines were not normalized; missing evidence was accepted; Qwen confused participant names with speaker labels. Added explicit action criteria, required source fields, nullable reference enums inside `anyOf` (Ollama 0.5.7 ignored sibling enum constraints), safe repair hints and bounded retries. Named assignees no longer inherit an unverified ordering voice. Added regression coverage, including RU/KK named months and absent evidence. No transcript or reference answers were replaced with mock data.
- Found stale Nginx DNS after API recreation: proxy still used the old IP and returned 502. Enabled dynamic upstream resolution. Forced a real address change with a temporary reservation container; proxy recovered in 31.4 seconds without restarting web. Temporary reservation removed; database/audio volumes preserved.
- Implemented exactly three product improvements in existing React components: transcript text search with highlighted matches, speaker filter, and task filters by assignee/needs_review. Source navigation resets transcript filters and restores focus. Export still uses all confirmed data. No public API or DB schema change.
- Repaired the real browser test's asynchronous polling and selectors; added reload persistence, Range and real-data filter checks. A browser regression initially caught a test race between click and requestAnimationFrame focus; now waits for the visible/focused state. Native verification initially targeted the wrong old PostgreSQL cluster; reran against the original isolated `pg-data` cluster, without changing credentials or databases. This test server was stopped after verification.
- Final native A/B: 11/11 checks, backend 40/40, AI 44/44, no skips; source hash unchanged throughout `.artifacts/verify-20260929T182416Z-2030020d`. Offline loading and real 35-second negative smoke passed. Real meeting/API/UI evidence and limitations are recorded in the current section of `VERIFICATION.md`.
- Final real evidence: negative 35s smoke 127.0s / 2 segments / 2 voices / 0 tasks; 40s API E2E 155.5s / 7 segments / 2 voices / 2 tasks; fresh 40s browser upload 154.7s / 7 segments / 2 voices / 3 tasks. Both positive runs completed with real models. The difference in extracted task coverage is explicitly documented, not hidden by schema success. Final browser filters, speaker/task persistence, confirmation and download passed; the downloaded DOCX contains all saved summary/segments/tasks/participants with no mock marker. UI screenshot inspected. The local real stack remains running, and no credentials were printed or written to artifact files.

Earlier entries below are historical snapshots; their old blockers are superseded by the current verification report.

## Source and baseline — 2026-09-25

- Working repository: `hack-bdffe61d-exit-1`, branch `backend`, HEAD `b728a22`; initially clean. No AGENTS.md found. No branch changes, commits or pushes.
- Fetched `origin/main` at `d89a32e`. Imported its full application into the working tree using `git diff --binary` / `git apply`; the original branch remains unchanged. This is the complete frontend/backend/AI version supplied in the archive, not the older backend-only tree.
- Architecture: React/Vite → FastAPI → PostgreSQL + audio storage → polling worker → HTTP AI service → faster-whisper / pyannote / Ollama → validated result → manual review → DOCX.
- Baseline environments: Node 25.8.0; separate Python 3.12.14 environments at `../.tools/backend-venv` and `../.tools/ai-venv`. Python dependencies installed from the existing requirements, frontend from package-lock.
- PASSED: frontend `npm ci`, `npm run build`, `npm run lint`; backend `AI_SERVICE_DIR=../ai-service python -m pytest -q tests` (15); AI `python -m pytest` (16), `python -m ruff check app tests scripts`.
- Baseline browser smoke PASSED; final PostgreSQL checks are recorded below. Docker not installed; using an isolated portable PostgreSQL 17.6 bound to loopback for database verification.

## Findings and implementation plan

| Priority | Location / reproduction | Consequence | Correction / verification |
|---|---|---|---|
| P0 | meetings routes have no authenticated owner filter; GET/modify any ID | Unauthorized access to recordings and protocols | Database sessions, Argon2 passwords, CSRF and owner checks on every route; two-user tests |
| P1 | worker commits running before HTTP; terminate worker | Jobs remain running forever | Lease + heartbeat + attempt token; PostgreSQL recovery/concurrency/stale-result tests |
| P1 | no bounded retry or retry API | Temporary AI outages require reupload | Classified failures, backoff, failed-only retry without overwriting completed data |
| P1 | upload checks extension only; mock differs from HTTP | Corrupt/long input enters queue | Shared media contract and full bounded decoding in both services |
| P1 | shared AI models can be used and unloaded concurrently | Model races / memory pressure | Serialize inference; explicit busy response and resource limits |
| P1 | unbounded transcript sent to LLM | Context can truncate | Conservative explicit byte/context budget, reject over-limit input |
| P2 | MeetingPage retries all HTTP failures forever | 401/403/404 never settle | Typed HTTP errors, finite retries, login/history/retry UI |
| P2 | ambiguous next-weekday rule | Incorrect or overconfident deadlines | Preserve ambiguous RU/KK raw phrases with review required; regression tests |
| P2 | no integrated deployment or PostgreSQL CI | Hard to reproduce and verify | Root Compose profiles, migrations, readiness, locks, CI, backup/restore documentation |

The previous format finding was too broad: current `main` already rejects MP4/WebM/OGG before queuing in HTTP mode. The remaining defect is mode-dependent acceptance and absent decoding/duration checks. The interpretation of “next Friday” is a product rule, not a universally correct date.

## Verification levels

A = unit/contract; B = complete integration using AI mock; C = real models and speech. A/B never imply C. Results and exact commands are appended as work proceeds.

## Implemented and checked

- **Access:** backend auth/manage, owner/session migration and every meeting route. Argon2, hashed opaque sessions, CSRF + Origin, rate limits, private legacy records. Two-user and anonymous tests cover detail/audio/tasks/speakers/confirm/reopen/retry/export.
- **Queue/storage:** UUID fencing, SKIP LOCKED, renewable 180s lease / 15s heartbeat, bounded delayed retries, graceful shutdown, atomic result transaction, no overwrite of saved protocols. Fully decoded upload → fsync → atomic rename → DB; rollback removes orphan files. Failed-only manual retry, storage cleanup dry-run.
- **Contracts/AI:** shared/alem_contract, consistent formats/limits/schemas, full decode, participant/evidence checks, bounded streamed response, explicit mode enforcement. Serialized inference, startup/readiness, conservative LLM input budget, raw deadlines and ambiguous RU/KK review. Removed heuristic assignee from a mention.
- **Frontend:** login/logout/history, capabilities and mode before upload, finite polling, native audio Range, demo URL cleanup, review flag, speaker save, retry/reopen, confirmed-only export. DOCX labels mock/unknown mode and retains raw deadlines/review flags.
- **Operations:** root Compose, static Nginx build, persistent volumes, migration gate, readiness, JSON logs, dependency locks, Windows ASR/ML dependency snapshots, CI, native Windows/Linux instructions, operator commands and isolated backup restoration.

## Final verification

Baseline browser smoke also PASSED. Exact commands, environment and limitations: [VERIFICATION.md](VERIFICATION.md).

| Command | Result |
|---|---|
| frontend npm ci / lint / build | PASSED |
| frontend npm run test:browser | PASSED: demo/fixtures, 320/375px, focus, edit, source, retry, export, terminal errors, audio cleanup |
| AI python -m pytest | PASSED: 29 |
| AI ruff; backend/shared ruff --select F; pip check in separate environments | PASSED |
| backend python scripts/run_postgres_tests.py | PASSED, final count in VERIFICATION.md; real PostgreSQL |
| backend python scripts/run_browser_e2e.py with AI_PYTHON/PG_BIN/admin URL | PASSED: full HTTP mock stack, reload during processing, edit/relogin/direct link, Range 206, labelled DOCX content, pg_dump/restore and audio hashes |
| Compose mock/real config --quiet | PASSED; actual build/run BLOCKED, no Docker Engine |
| real ASR check_asr.py on English synthesis | PASSED: CPU/int8 tiny, 12.868s, 2 segments, 4/4 expected words |
| real ML installation/imports | PASSED on Windows CPU; not full inference |

The E2E harness adds a three-second delay only in a temporary AI mock wrapper to test reload during processing deterministically. Browser/API/database requests are real. Test subprocesses and generated databases are cleaned up. Backups were restored only into isolated databases. A/B never imply C.

## Remaining blockers and next priority

1. **C / P1 release gate:** authorised pyannote access and weights, Ollama/Qwen, permitted RU/KK conversations with expected content. Full ASR+diarization+LLM quality, memory and speed are unverified. Synthetic English ASR is only a partial check.
2. **Deployment / P1 release gate:** run container CI on target Linux, check ML installation/startup and target CPU/GPU. Workflow added but not run or pushed. torch 2.5.1 imported on CPU only.
3. Configure HTTPS, production settings, real accounts/legacy owners, protected backups; rehearse restoration in target installation. Owner-only access is the minimal model; team sharing is not implemented.
4. Later operations: retention of rate buckets/worker heartbeats, larger-dataset pagination/load tests, longest supported speech/context evaluation, dependency advisory review before deployment.

No unresolved P0 was found in the exercised access/storage paths; this is not a security certification. Production readiness is not claimed. Branch remains backend; no commit, push, reset, checkout or public deployment occurred.

Final follow-up: 37 backend tests PASSED. Added protection against a duplicate legacy job demoting a completed/confirmed protocol; targeted PostgreSQL regression PASSED (1 selected / 36 deselected). Transient test PostgreSQL is stopped after verification; restart command is documented in VERIFICATION.md. Source, downloaded tooling and model caches remain on disk; no user files were cleaned.

## Continued verification — 2026-09-28

- Confirmed local Hugging Face authentication without displaying or storing the token in logs or Git. Downloaded the approved `speaker-diarization-3.1`, `segmentation-3.0`, and wespeaker dependency into the project HF cache. Offline pyannote load and inference on a short synthetic WAV passed.
- Fixed the diarization loader to use `PYANNOTE_CACHE` or the project `HF_HOME/hub`. Fixed the model downloader to honor `HF_HOME`, classified native ASR allocation failure as `RESOURCE_LIMIT`, and avoided non-Linux `malloc_trim` calls.
- Rebuilt corrupted Docker API and AI base layers without cache. Isolated Compose mock deployment passed browser upload/edit/reload/confirm/DOCX/relogin, restart persistence, SIGKILL worker lease recovery, and independent second-project PostgreSQL/audio restore. Test volumes and backup artifacts were retained.
- Final native A/B gate on source hash `6946abac27fd9990e570275fd9cd021579ec49c709cb3582dba16a0b62b143ce`: 37 backend and 32 AI tests with zero skips, lint, dependency checks, TypeScript, production build, browser regressions, and HTTP mock E2E all passed. Source hash stayed unchanged during the gate. Evidence: `.artifacts/verify-20260927T204018Z-6c4688b2/report.json` and `.artifacts/deployment-9094bf12/container-report.json` (local, ignored).
- Docker real ML build and Ollama image pull lost the Engine connection when Windows commit space fell below 1 GiB. Docker Desktop was stopped normally to release memory; no test volumes were removed. The native full-recording large-v3 ASR also raised `mkl_malloc` under the same memory pressure. Full real UI/LLM verification is still pending.
- Full permitted recording 1 was decoded locally to a 16 kHz WAV in ignored artifacts, then pyannote inference completed in 288 seconds on CPU: 54 speech turns and four speaker clusters. The supplied written script names five participants but has no timed speaker annotation, so this is a discrepancy to investigate, not a measurable DER. Audio, transcript and Hugging Face credentials remain outside Git.

## 2026-09-28 continuation

- Native A/B verification completed on one unchanged source snapshot: 11/11 checks PASSED, including backend 37/37, AI 32/32, frontend browser regressions, and HTTP mock end-to-end through PostgreSQL and worker. Evidence: `.artifacts/verify-20260927T204325Z-681694ce/report.json`.
- A first attempt was blocked by the current sandbox's inaccessible system Temp. The successful attempt used a project-local Temp and disabled pytest's cache provider; no application fix was needed.
- The earlier container mock verification remains PASSED (`.artifacts/deployment-9094bf12/container-report.json`). Full real AI remains unverified: Docker Engine is stopped, Ollama/Qwen is absent, and Windows had only 2.3 GiB of available commit at the last check. The isolated test PostgreSQL was stopped after the A/B run.
