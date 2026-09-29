import type { Meeting, TranscriptSegment } from "../types/meeting";
import type { ReactNode } from "react";
import { formatTime } from "../utils/format";

interface Props {
  meeting: Meeting;
  highlightedId: string | null;
  hasAudio: boolean;
  query: string;
  speakerFilter: string;
  onQueryChange: (query: string) => void;
  onSpeakerFilterChange: (speaker: string) => void;
  onPlay: (segment: TranscriptSegment) => void;
}

function highlight(text: string, query: string): ReactNode {
  if (!query) return text;
  const lower = text.toLocaleLowerCase();
  const parts: ReactNode[] = [];
  let from = 0;
  let index = lower.indexOf(query);
  while (index !== -1) {
    parts.push(text.slice(from, index), <mark key={index}>{text.slice(index, index + query.length)}</mark>);
    from = index + query.length;
    index = lower.indexOf(query, from);
  }
  parts.push(text.slice(from));
  return parts;
}

export function Transcript({ meeting, highlightedId, hasAudio, query, speakerFilter, onQueryChange, onSpeakerFilterChange, onPlay }: Props) {
  const needle = query.trim().toLocaleLowerCase();
  const speakers = [...new Set(meeting.segments.map((segment) => segment.speaker))];
  const visible = meeting.segments.filter((segment) =>
    (!speakerFilter || (segment.speaker ?? "__unknown") === speakerFilter) &&
    (!needle || segment.text.toLocaleLowerCase().includes(needle)));
  function resetFilters() { onQueryChange(""); onSpeakerFilterChange(""); }
  function speakerName(label: string | null): string {
    if (!label) return "Не определён";
    const mapping = meeting.speakers.find((speaker) => speaker.label === label);
    return meeting.participants.find((person) => person.id === mapping?.participant_id)?.name || label;
  }

  return (
    <section className="panel" aria-labelledby="transcript-heading">
      <div className="section-heading"><p className="eyebrow">Первоисточник</p><h2 id="transcript-heading">Транскрипт</h2></div>
      {meeting.segments.length > 0 && <>
        <div className="review-filters">
          <label>Поиск по транскрипту<input type="search" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Слово или фраза" /></label>
          <label>Говорящий<select aria-label="Фильтр транскрипта: говорящий" value={speakerFilter} onChange={(event) => onSpeakerFilterChange(event.target.value)}>
            <option value="">Все говорящие</option>
            {speakers.map((speaker) => <option key={speaker ?? "__unknown"} value={speaker ?? "__unknown"}>{speakerName(speaker)}{speaker && speakerName(speaker) !== speaker ? ` · ${speaker}` : ""}</option>)}
          </select></label>
          <button type="button" onClick={resetFilters} disabled={!query && !speakerFilter}>Сбросить поиск и говорящего</button>
        </div>
        <p className="filter-count muted" role="status">Реплики: {visible.length} из {meeting.segments.length}</p>
      </>}
      {meeting.segments.length === 0 ? <p className="empty-state">Транскрипт пока пуст.</p> :
        visible.length === 0 ? <p className="empty-state">Реплики не найдены. Измените поиск или говорящего.</p> :
        <ol className="transcript-list">
          {visible.map((segment) => (
            <li key={segment.id} id={`segment-${segment.id}`} tabIndex={-1}
              className={`transcript-segment${highlightedId === segment.id ? " is-highlighted" : ""}`}>
              <div className="segment-meta">
                <span className="segment-time">{formatTime(segment.start_ms)}</span>
                <strong>{speakerName(segment.speaker)}</strong>
              </div>
              <p>{highlight(segment.text, needle)}</p>
              {hasAudio && <button className="text-button" type="button" onClick={() => onPlay(segment)}
                aria-label={`Прослушать реплику ${speakerName(segment.speaker)} с ${formatTime(segment.start_ms)}`}>
                Прослушать реплику
              </button>}
            </li>
          ))}
        </ol>}
    </section>
  );
}
