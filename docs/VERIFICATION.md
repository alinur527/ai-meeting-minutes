# Verification

This report separates application tests from real-model evidence. **A** means unit / contract checks; **B** means real application components with explicitly mocked AI; **C** means actual Whisper, Pyannote and Qwen inference. A/B success is not evidence of model accuracy.

## Public-copy validation — 2026-09-30

The public copy was created from the current working files, including uncommitted changes. It does not include the old Git database, credentials, recordings, weights or private artifacts. The migration INI contains only an example URL; actual migrations read `DATABASE_URL` from environment-backed settings.

Fresh Python environments were installed from this copy's backend / AI lockfiles, and the frontend was installed with `npm ci`. All **11 A/B checks passed**, with **40/40 backend tests**, **44/44 AI tests**, zero skips and unchanged source files during the run. Checks included Ruff / Python errors, both `pip check` runs, frontend lint / TypeScript / build, browser regressions and an isolated HTTP mock E2E with database / audio restore. `python scripts/local_real.py check` also passed.

The pre-Git test manifest identifies the tested non-Markdown files with SHA-256 `14f7041303b5ff28b734e98fcce18b6844323441b0ddf29538a592c3d2bcba57`; generated dependencies, caches and test output were excluded. Trailing empty lines in five existing files were normalized afterward without changing configuration or dependency content. Fresh local diagnostics are retained outside the public repository. The check runner used the same underlying commands as the combined gate, before Git initialization.

The real-model measurements below belong to the original working tree; they are not new benchmarks of this public copy. No heavy real inference was repeated for documentation, the example migration URL, the isolated Compose project name or the conservative example memory setting.

Early public Linux CI runs passed the container deployment and 10 of 11 A/B checks. Browser smoke exposed a navigation timing race: a URL change preceded React's page render, and the demo badge existed on both the old and new pages. The test now waits for destination-only summary content and observable edit / confirmation / keyboard-focus results before asserting them. This changes test synchronization, not application behavior. Current public results are available in [GitHub Actions](https://github.com/alinur527/ai-meeting-minutes/actions/workflows/verify.yml).

## Confirmed baseline — 2026-09-29

| Level / component | Result | What was checked |
|---|---|---|
| A: backend | PASS, 40/40, no skips | Isolated PostgreSQL 17.6; authentication, ownership, CSRF, media / AI contracts, migrations, lease renewal, fencing, retries and preservation of manual edits |
| A: AI | PASS, 44/44, no skips | Schema / evidence validation, bounded repair, memory behavior, Russian / Kazakh date parsing and separation of speaker identity from task ownership; fakes used |
| A: static / dependencies | PASS | Frontend lint, TypeScript, production build; AI Ruff; Python error checks; pip check in both environments |
| B: browser / HTTP mock | PASS | Search, filters, source focus, 320 / 375 px layouts; real API / PostgreSQL / worker, reload, edits, confirmation, DOCX and database / audio backup restore with explicit AI mock |
| A/B combined gate | PASS, 11/11 | One unchanged source snapshot throughout the run |
| C: ASR | PASS | `Systran/faster-whisper-large-v3`, CPU / int8, Russian speech and timestamps |
| C: diarization | PASS | `pyannote/speaker-diarization-3.1`, CPU, segmentation-3.0 and wespeaker embeddings; two detected voices on the checked excerpt |
| C: LLM | PASS | Actual Ollama 0.5.7 `/api/chat`, `qwen2.5:7b-instruct-q4_K_M`, temperature zero, schema and evidence validation |
| C: offline loading | PASS | ASR / diarization loaded with `network_mode: none`, no HF token and actual cached weights |
| C: API / worker | PASS | Real audio upload, queued → running → completed, byte-equal audio round trip, Range 206, speaker / task patches, confirmation and DOCX content |
| C: fresh browser upload | PASS | Real inference, filters / source navigation, speaker and task persistence after reload, confirmation and DOCX |
| Docker DNS recovery | PASS | Forced API container address change; Nginx recovered in 31.4 seconds without a web restart |
| Configuration | PASS | Standalone AI and root + local-real `config --quiet`; `nginx -t` |
| GitHub CI / GPU | NOT RUN in this baseline | No passing public CI or GPU claim follows from these local checks |

The baseline source digest was `25b5a00e3a9e3f0bfc3e3b21883a27c3876ffe125027d348f1baa23ae6082c4a`. The original A/B report was `verify-20260929T182416Z-2030020d/report.json`. Its manifest included tracked and non-ignored working files; the aggregate code hash excluded Markdown. This digest identifies the original baseline, not the later sanitized public copy.

Private evidence remains with the original local project and is deliberately not published as a dataset. Evidence identifiers include `real-c/api-report.json`, `real-c/ui-final/ui-report.json`, `real-c/offline-report.json`, `real-c/dns-report.json` and `real-c/runtime-report.json`. These are identifiers, not downloadable public links.

## Real recordings and measured performance

The source recording was supplied for local testing; its provenance was recorded as unknown. It is not claimed to be an independent corpus of human meetings. Reference protocols were not supplied to the model. Mono 16 kHz WAV excerpts were used; no source recording, transcript artifact or real-run screenshot is distributed with this public copy.

| Run | Audio | Wall time | Observed output |
|---|---:|---:|---|
| Informational AI smoke | First 35 seconds | 127.0 s | HTTP 200, real mode, Russian, 2 segments / 2 speakers, summary and 0 tasks |
| Final API / worker | 40 seconds, source interval 65–105 s | 155.5 s | 7 segments / 2 speakers / 2 tasks, with owners and normalized dates |
| Final fresh browser upload | Same 40-second excerpt | 154.7 s | 7 segments / 2 speakers / 3 tasks; the third had unknown owner / date and required review |

The source is 274.25 seconds long. **The complete source recording was not processed and evaluated end to end in this run.** These are local validation observations, not a general latency or quality benchmark. An earlier 40-second API baseline took 141.3 seconds and yielded three tasks; subsequent browser resume time was not counted as inference time.

The two final positive runs had different meeting / participant IDs. The two-versus-three task difference occurred despite temperature zero. The API result included two fully specified tasks with evidence; a partially stated final point appeared only in the summary. The browser upload also extracted that point and marked its missing owner / date for review. Task extraction completeness is therefore known to vary; valid JSON does not establish completeness or correctness.

The final browser run checked case-insensitive search and highlighting, speaker filtering, task owner / review filters, revealing hidden source segments, persisted speaker mappings, task corrections with explicit null fields, confirmation and export. The DOCX XML contained the saved summary, every segment, task and participant, without DEMO / MOCK markers. This checks document contents, not page layout in Word.

The public README screenshot is a separately captured fictional demo fixture. It is not evidence of C and does not contain material from the private real recording.

## Models and resource observations

- Docker Desktop Linux / WSL2 allocated 20 CPU and 11.54 GiB RAM. Inference used CPU, not GPU.
- Large-v3 cache: `model.bin` size 3,087,284,237 bytes; revision `edaa852ec7e145841d8ffdb056a99866b5f0a478`. Segmentation weights: 5,905,440 bytes; wespeaker weights: 26,645,418 bytes; diarization 3.1 uses its pipeline configuration. A pre-existing tiny model was not used for C.
- Only cache content was transferred; Hugging Face login files were excluded. Runtime did not contain `HF_TOKEN`. Qwen was reused rather than downloaded again.
- `LOW_MEMORY_MODE=1` unloads ASR and diarization between stages. Ollama used one parallel slot and one loaded model; LLM calls used `keep_alive=0` and low-memory `num_batch=128`.
- Point-in-time memory observations: Ollama approximately 8.4–8.9 GiB; AI after unloading approximately 0.4–0.5 GiB. Continuous peak memory was not measured. Final containers reported `OOMKilled=false`.

## Failure behavior exercised

During development, real extraction failed when participant names were emitted as speaker labels. The meeting reached an explicit failed state rather than remaining running or saving invalid data. Ollama 0.5.7 did not constrain a string branch when the enum was a sibling of `anyOf`; moving the enum inside the nullable string branch and providing allowlisted repair hints resolved the diagnostic case.

Other corrections covered informational speech incorrectly becoming a task, missing evidence references and named-month Russian / Kazakh dates. Unknown speaker identity stays separate from a named task owner. Tests cover these boundaries; they are not a statistical quality evaluation.

Existing job behavior was retained: 180-second leases, 15-second heartbeats, stale-attempt fencing, at most three worker attempts, bounded backoff, failed-only retry and protection of saved edits. Upload validation checks actual decoding. Unknown AI server messages are not forwarded as raw text to users.

An earlier isolated container mock run also exercised migrations, browser interaction, restart, worker termination / lease recovery and restoration of database plus audio. Historical resource failures during real-model setup were superseded by the successful CPU runs above; GPU remained untested.

## Reproduce application checks

Create the separate Python environments and frontend dependencies described in [deployment](DEPLOYMENT.md). Use an isolated PostgreSQL 17 test instance with permission to create databases. Configure these environment variables without logging their values:

- `TEST_POSTGRES_ADMIN_URL`: administrative URL for the isolated test instance.
- `AI_PYTHON`: absolute path to the AI environment's Python executable.
- `PG_BIN`: directory containing PostgreSQL 17+ `pg_dump` and `pg_restore`.

From a Git checkout, using the backend Python:

```bash
python scripts/verify.py
```

This runs the 11 A/B checks, rejects skipped tests, snapshots the source and writes private diagnostics under ignored `.artifacts`. It requires Git metadata and therefore runs after repository initialization. For a pre-Git copy, invoke its underlying commands directly:

```bash
# Backend directory, backend environment
python scripts/run_postgres_tests.py -ra
python scripts/run_browser_e2e.py

# AI directory, AI environment
python -m pytest -ra
python -m ruff check app tests scripts

# Frontend directory
npm run lint
npm run build
npm run test:browser
```

Build the frontend before the connected backend/browser harness. Run `python -m pip check` in both environments. The isolated harness creates uniquely named test databases and destroys only those it creates. Missing AI / backup prerequisites must not be reported as passed coverage. Browser setup is documented in the [frontend guide](../frontend/README.md).

`python scripts/local_real.py check` checks Compose syntax without starting inference. It requires a running Docker engine, but does not prove model availability. Use only authorized recordings and the explicit real browser harness for new C evaluations; routine documentation changes do not need another heavy inference run.

## Remaining limits

No formal WER / CER / DER, independent extraction-recall study, Kazakh / mixed-language benchmark, complete long-meeting run or sustained-load measurement has been performed. LLM input including schema / instructions is capped at 16,000 UTF-8 bytes, potentially below the 30-minute media cap. Ambiguous dates and unknown people require human review. Local C success is not a production-readiness claim.
