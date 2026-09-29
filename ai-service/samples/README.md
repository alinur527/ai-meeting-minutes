# Samples

Generate a small, privacy-safe test WAV without an external TTS service:

```bash
python scripts/generate_sample.py
```

The generated file contains tones and silence, so it only exercises upload/audio decoding. Use an
approved, locally recorded RU/KK meeting clip for an end-to-end ASR quality check.
