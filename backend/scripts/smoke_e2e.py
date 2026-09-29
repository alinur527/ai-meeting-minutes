"""Create a test meeting, wait for its worker, and download the DOCX protocol."""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=3700)
    parser.add_argument("--output", type=Path, default=Path("test-protocol.docx"))
    args = parser.parse_args()
    base = args.backend_url.rstrip("/")
    with httpx.Client(timeout=120, trust_env=False) as client:
        with args.audio.open("rb") as audio:
            response = client.post(
                base + "/meetings",
                files={"file": (args.audio.name, audio, "application/octet-stream")},
                data={
                    "title": "Проверка связи двух ноутбуков",
                    "started_at": datetime.now(ZoneInfo("Asia/Almaty")).isoformat(),
                    "timezone": "Asia/Almaty",
                    "participants_json": json.dumps(
                        [{"name": "Султан"}, {"name": "Даурен"}], ensure_ascii=False
                    ),
                },
            )
        response.raise_for_status()
        meeting_id = response.json()["id"]
        print(f"Created meeting {meeting_id}", flush=True)
        deadline = time.monotonic() + args.timeout
        previous_status = None
        while time.monotonic() < deadline:
            response = client.get(base + f"/meetings/{meeting_id}")
            response.raise_for_status()
            meeting = response.json()
            status = meeting["status"]
            if status != previous_status:
                print(f"Status: {status}", flush=True)
                previous_status = status
            if status == "failed":
                raise SystemExit(f"Processing failed: {meeting['error']}")
            if status == "completed":
                print(
                    f"Segments: {len(meeting['segments'])}; tasks: {len(meeting['action_items'])}"
                )
                document = client.get(
                    base + f"/meetings/{meeting_id}/export?format=docx"
                )
                document.raise_for_status()
                args.output.write_bytes(document.content)
                print(f"Saved {args.output.resolve()}")
                return
            time.sleep(2)
    raise SystemExit(
        "Timeout: check the worker console and AI logs; the meeting may still be running."
    )


if __name__ == "__main__":
    main()
