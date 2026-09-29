"""Run from backend/: python -m app.check_ai [--audio path/to/meeting.wav]."""

import argparse
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from .config import settings
from .services.ai_processor import ProcessingParticipant, process_meeting


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the configured remote AI service")
    parser.add_argument("--audio", help="Also process this WAV/MP3/M4A (real inference may take minutes)")
    args = parser.parse_args()
    if settings.ai_mode == "mock":
        parser.exit(1, "Backend AI_MODE=mock: set AI_MODE=http to connect to your AI laptop.\n")
    url = str(settings.ai_base_url).rstrip("/")
    try:
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.get(url + "/health")
            response.raise_for_status()
        body = response.json()
        if body.get("status") != "ok" or body.get("mode") not in {"mock", "real"}:
            raise ValueError("This URL did not return the Hackalem AI health contract")
        print(f"AI reachable; AI mode={body['mode']}")
        if body["mode"] == "mock":
            print("AI mock mode returns sample text; it does not transcribe the audio.")
        if args.audio:
            result = process_meeting(
                meeting_id=uuid4(),
                audio_path=args.audio,
                meeting_date=datetime.now(ZoneInfo("Asia/Almaty")).date(),
                timezone="Asia/Almaty",
                participants=[ProcessingParticipant(id=uuid4(), name="Тестовый участник")],
            )
            print(f"Process OK: {len(result.segments)} segments; {len(result.action_items)} tasks")
        else:
            print("Health only. Use --audio PATH to verify token, upload and response format.")
    except Exception as exc:
        print(f"Check failed ({type(exc).__name__}): {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
