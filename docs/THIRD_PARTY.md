# Third-party acknowledgements

AI Meeting Minutes grew from the HackAlem **Exit 1** team project. The [original repository](https://github.com/BAITC-Hacks/hack-bdffe61d-exit-1) is acknowledged in the root README; starting a separate public Git history does not change that attribution. No project license has been selected.

## Libraries and tools

The project installs dependencies through Python lockfiles, npm and container images; dependency source trees and model weights are not vendored in this repository. Their own license / copyright notices remain applicable and are provided with the installed distributions. Do not infer a license for this project's code from a dependency's license.

Key upstream projects include [React](https://github.com/facebook/react), [Vite](https://github.com/vitejs/vite), [FastAPI](https://github.com/fastapi/fastapi), [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), [Alembic](https://github.com/sqlalchemy/alembic), [PostgreSQL](https://www.postgresql.org/about/licence/), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [Pyannote](https://github.com/pyannote/pyannote-audio), [PyTorch](https://github.com/pytorch/pytorch), [Ollama](https://github.com/ollama/ollama) and [python-docx](https://github.com/python-openxml/python-docx).

## Separately downloaded models

The backend also uses [Psycopg](https://www.psycopg.org/psycopg3/), whose installed package metadata identifies `LGPL-3.0-only`, and [PyAV](https://github.com/PyAV-Org/PyAV), whose package metadata identifies BSD-3-Clause. These dependencies are installed separately with their notices; this repository does not relicense or vendor them. The frontend lockfile likewise records the licenses of its direct and transitive packages.

Consult the upstream model cards and distribution terms before downloading or redistributing weights:

- [Systran / Faster Whisper large-v3](https://huggingface.co/Systran/faster-whisper-large-v3): CTranslate2 conversion of Whisper large-v3; model card identifies MIT.
- [Pyannote speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1): model card identifies MIT and gated access conditions. Its [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) dependency also requires acceptance of access conditions. [Wespeaker embeddings](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM) are downloaded separately.
- [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct): upstream model card and license. The application obtains the `qwen2.5:7b-instruct-q4_K_M` distribution through Ollama.

No model license is applied to the application itself. Access conditions and downstream redistribution obligations should be checked for the exact distributions used.

## Demo and comparison material

The README screenshot is generated from the repository's fictional frontend fixture, with DEMO / MOCK labelling. It contains no private recording and is not a model-quality benchmark. Comparative product references are credited in [the historical analysis](COMPETITIVE_ANALYSIS.md); they do not imply inclusion of those teams' code or assets.
