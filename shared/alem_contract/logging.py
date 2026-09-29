"""JSON operational logs. Callers supply only identifiers and safe metadata."""

import json
import logging
from datetime import datetime, timezone

FIELDS = (
    "request_id",
    "meeting_id",
    "job_id",
    "attempt",
    "stage",
    "duration_ms",
    "method",
    "route",
    "status",
    "error_type",
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        result = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        result.update(
            {key: getattr(record, key) for key in FIELDS if hasattr(record, key)}
        )
        # Deliberately exclude exception text: DB/validation exceptions can contain data.
        return json.dumps(result, ensure_ascii=False, default=str)


def configure_logging():
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
