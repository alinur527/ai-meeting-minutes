from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

logger = logging.getLogger("ai_service.timing")


@contextmanager
def timed_stage(stage: str, meeting_id: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        logger.info(
            "pipeline_stage_finished",
            extra={"stage": stage, "meeting_id": meeting_id, "duration_ms": elapsed_ms},
        )
