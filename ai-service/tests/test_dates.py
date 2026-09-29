from datetime import date

import pytest

from app.pipeline.dates import resolve_due_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("к пятнице", date(2026, 9, 25)),
        ("до конца недели", date(2026, 9, 27)),
        ("ертең", date(2026, 9, 24)),
        ("3 күннен кейін", date(2026, 9, 26)),
        ("жұмаға дейін", date(2026, 9, 25)),
        ("через 10 дней", date(2026, 10, 3)),
        ("01.10", date(2026, 10, 1)),
        ("2026-12-31", date(2026, 12, 31)),
        ("до 15 октября", date(2026, 10, 15)),
        ("до 26 сентября", date(2026, 9, 26)),
        ("к 10 января", date(2027, 1, 10)),
        ("15 қазанға дейін", date(2026, 10, 15)),
        ("26 қыркүйек", date(2026, 9, 26)),
        ("до 29 февраля 2028 года", date(2028, 2, 29)),
        ("до 31 сентября", None),
        ("15 октября или 20 октября", None),
        (None, None),
    ],
)
def test_resolve_due_date(raw, expected) -> None:
    assert resolve_due_date(raw, date(2026, 9, 23)) == expected
