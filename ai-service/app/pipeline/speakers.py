from __future__ import annotations

import re

from app.schemas import MeetingMeta, SpeakerMatch, TranscriptSegment

INTRO_PATTERNS = (
    re.compile(r"\b(?:меня зовут|я)[, ]+([\wәіңғүұқөһё -]{2,80})", re.IGNORECASE),
    re.compile(r"\b(?:менің атым|мен)[, ]+([\wәіңғүұқөһё -]{2,80})", re.IGNORECASE),
)


def identify_speakers(
    segments: list[TranscriptSegment], meta: MeetingMeta
) -> dict[str, SpeakerMatch]:
    """Conservative MVP self-identification; unknown voices remain explicitly null."""
    labels = sorted({segment.speaker for segment in segments})
    matches = {label: SpeakerMatch() for label in labels}
    by_name = {
        " ".join(participant.name.casefold().replace("ё", "е").split()): participant.id
        for participant in meta.participants
    }
    used_ids: set[str] = set()
    for segment in segments:
        if segment.start_ms > 120_000 or matches[segment.speaker].participant_id is not None:
            continue
        normalized_text = " ".join(segment.text.casefold().replace("ё", "е").split())
        for full_name, participant_id in by_name.items():
            tokens = [token for token in full_name.split() if len(token) > 2]
            explicitly_introduced = any(
                pattern.search(normalized_text) for pattern in INTRO_PATTERNS
            )
            token_match = bool(tokens) and (
                full_name in normalized_text
                or all(token in normalized_text for token in tokens[:2])
            )
            if explicitly_introduced and token_match and participant_id not in used_ids:
                matches[segment.speaker] = SpeakerMatch(
                    participant_id=participant_id, confidence=0.9
                )
                used_ids.add(participant_id)
                break
    return matches
