FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models/huggingface XDG_CACHE_HOME=/models/cache PYANNOTE_CACHE=/models/huggingface/hub
COPY shared /shared
WORKDIR /service
COPY ai-service/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home --uid 10001 appuser && mkdir -p /models && chown -R appuser:appuser /models /service
USER appuser
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "8"]

# Keep dependency layers independent of application edits.
FROM runtime AS base
COPY --chown=appuser:appuser ai-service/app ./app
COPY --chown=appuser:appuser ai-service/scripts ./scripts

FROM runtime AS ml-dependencies
USER root
RUN apt-get update && apt-get install --no-install-recommends -y libsndfile1 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY ai-service/requirements.txt ai-service/requirements-ml.txt ai-service/requirements-ml-windows.lock ./
# The shipped real profile explicitly runs diarization on CPU. Pin CPU wheels
# to avoid downloading an unused CUDA runtime and keep its device choice explicit.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1+cpu torchaudio==2.5.1+cpu
RUN sed '/^-e /d' requirements.lock > base-constraints.txt && sed '/^-e /d' requirements-ml-windows.lock > ml-constraints.txt && pip install --no-cache-dir -c base-constraints.txt -c ml-constraints.txt -r requirements-ml.txt
USER appuser

FROM ml-dependencies AS ml
COPY --chown=appuser:appuser ai-service/app ./app
COPY --chown=appuser:appuser ai-service/scripts ./scripts
