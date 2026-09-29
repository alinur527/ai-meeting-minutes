# AI service

Local HTTP inference for AI Meeting Minutes. See the [deployment guide](../docs/DEPLOYMENT.md) for complete startup and [verification](../docs/VERIFICATION.md) for measured results.

## Pipeline

Audio decode → Faster Whisper large-v3 → Pyannote 3.1 → timestamp alignment → Ollama / Qwen summary and tasks → schema / evidence validation.

The verified setup uses CPU / int8 ASR and CPU diarization. Models are downloaded separately with `scripts/download_models.py`. It prepares `Systran/faster-whisper-large-v3`, `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0` and `pyannote/wespeaker-voxceleb-resnet34-LM`. Accept both gated Pyannote repositories' conditions before supplying `HF_TOKEN` through the process environment. Qwen is prepared separately with `ollama pull qwen2.5:7b-instruct-q4_K_M`.

The [root Compose procedure](../docs/DEPLOYMENT.md#real-ai-with-root-compose) handles cache volumes, token input and offline runtime. ASR / diarization loading without network access has been verified. Ollama remains a required local HTTP dependency; errors are not replaced with mock results.

## Contract

`POST /internal/process` requires `X-Internal-Token`. Multipart fields are `audio` (WAV / MP3 / M4A bytes) and `meta` (JSON meeting metadata). The backend sends participant IDs and the meeting calendar date in its timezone. It does not send a filesystem path from another host.

The [shared schemas](../shared/alem_contract/schemas.py) define `ProcessResponse`: processing mode, millisecond transcript segments, speaker mappings, summary and action items with evidence IDs. Original deadline wording is preserved in `due_text_raw`. Invalid JSON and nonexistent evidence references are rejected. A person mentioned as a task owner is not automatically identified as the current speaker.

`GET /health` checks liveness. `GET /ready` requires the internal token and checks readiness. Startup checks models and Ollama. One inference runs at a time; a concurrent request receives `503 BUSY`.

## Configuration

| Variable | Verified value / behavior |
|---|---|
| `AI_MODE` | `real` or explicitly `mock` |
| `INTERNAL_TOKEN` | Required in both modes; match backend `AI_INTERNAL_TOKEN` |
| `MODEL_DIR`, `HF_HOME` | `/models`, `/models/huggingface` in containers |
| `ASR_MODEL` | `Systran/faster-whisper-large-v3` |
| `ASR_DEVICE`, `ASR_COMPUTE_TYPE` | `cpu`, `int8` |
| `DIARIZATION_MODEL`, `DIARIZATION_DEVICE` | `pyannote/speaker-diarization-3.1`, `cpu` |
| `OLLAMA_URL` | `http://ollama:11434` inside Docker; loopback for native Ollama |
| `LLM_MODEL`, `LLM_RETRIES` | `qwen2.5:7b-instruct-q4_K_M`, `2` repair retries |
| `LOW_MEMORY_MODE` | `1` unloads models between stages |
| `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | `1` after cache preparation |
| `MAX_AUDIO_MB`, `MAX_AUDIO_SECONDS` | Hard caps of `200`, `1800` |
| `LLM_MAX_INPUT_BYTES`, `LLM_CONTEXT_TOKENS` | `16000`, `32768` |

The Python settings default to real mode and automatic device selection; the example and root real Compose explicitly select CPU. The standalone Compose file defaults to mock when no mode is supplied. The prepared-stack helper sets real mode explicitly. An `.env` file is loaded by Compose or `uvicorn --env-file`, not directly by `Settings.from_env`.

The serialized LLM input limit includes instructions and schema. Input beyond the limit fails explicitly rather than losing its tail. Ambiguous relative dates and uncertain ownership remain marked for review.

## Development and tests

Use Python 3.12 and an environment separate from the backend, because both services have an `app` package. From this directory:

```bash
python -m pip install -r requirements-dev.lock
python -m ruff check app tests scripts
python -m pytest
```

Unit tests use fakes / explicit mock processing; they do not establish model accuracy. `requirements-ml.txt` pins the core ML stack. `requirements-ml-windows.lock` also provides constraints for the Linux CPU Docker build. GPU and native Windows full inference need separate validation.

For isolated ASR diagnostics, install `requirements-asr.lock` in another environment, prepare a local cache, then run `python -m scripts.check_asr recording.wav --expected-word WORD`. Add `--synthetic` for generated speech. Recordings, weights and diagnostic output are intentionally excluded from Git.
