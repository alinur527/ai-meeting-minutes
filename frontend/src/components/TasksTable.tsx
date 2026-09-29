import { useState, type FormEvent } from "react";
import type { ActionItem, Participant } from "../types/meeting";
import { formatDate } from "../utils/format";

interface Props {
  items: ActionItem[];
  participants: Participant[];
  editable: boolean;
  hasAudio: boolean;
  onSave: (item: ActionItem) => Promise<void>;
  onShowSource: (item: ActionItem) => void;
  onPlaySource: (item: ActionItem) => void;
}

export function TasksTable({ items, participants, editable, hasAudio, onSave, onShowSource, onPlaySource }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ActionItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const visible = items.filter((item) =>
    (!ownerFilter || (item.assignee_id ?? "__unassigned") === ownerFilter) &&
    (!reviewFilter || item.needs_review));

  function startEditing(item: ActionItem) {
    setDraft({ ...item });
    setEditingId(item.id);
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft?.text.trim()) return;
    setSaving(true);
    setError("");
    try {
      await onSave({ ...draft, text: draft.text.trim() });
      setEditingId(null);
      setDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось сохранить поручение.");
    } finally { setSaving(false); }
  }

  return (
    <section className="panel tasks-panel" aria-labelledby="tasks-heading">
      <div className="section-heading"><p className="eyebrow">К исполнению</p><h2 id="tasks-heading">Поручения <span className="count">{items.length}</span></h2></div>
      {items.length > 0 && <>
        <div className="review-filters">
          <label>Исполнитель<select aria-label="Фильтр поручений: исполнитель" value={ownerFilter} disabled={editingId !== null} onChange={(event) => setOwnerFilter(event.target.value)}>
            <option value="">Все исполнители</option><option value="__unassigned">Без ответственного</option>
            {participants.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
          </select></label>
          <label>Проверка<select aria-label="Фильтр поручений: проверка" value={reviewFilter} disabled={editingId !== null} onChange={(event) => setReviewFilter(event.target.value)}>
            <option value="">Все поручения</option><option value="needs_review">Требуют проверки</option>
          </select></label>
          <button type="button" disabled={editingId !== null || (!ownerFilter && !reviewFilter)} onClick={() => { setOwnerFilter(""); setReviewFilter(""); }}>Сбросить фильтры поручений</button>
        </div>
        <p className="filter-count muted" role="status">Поручения: {visible.length} из {items.length}. Фильтры не меняют состав экспорта.</p>
      </>}
      {items.length === 0 ? <p className="empty-state">Поручения не обнаружены.</p> :
        visible.length === 0 ? <p className="empty-state">Нет поручений с выбранными фильтрами.</p> :
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Поручение</th><th scope="col">Ответственный</th><th scope="col">Срок</th><th scope="col">Действия</th></tr></thead>
            <tbody>
              {visible.map((item) => editingId === item.id && draft && editable ?
                <tr key={item.id} className="editing-row"><td colSpan={4}>
                  <form className="edit-form" onSubmit={save}>
                    <h3>Изменить поручение</h3>
                    <label>Текст поручения<textarea value={draft.text} required rows={2} onChange={(event) => setDraft({ ...draft, text: event.target.value })} /></label>
                    <div className="edit-fields">
                      <label>Ответственный<select value={draft.assignee_id || ""} onChange={(event) => setDraft({ ...draft, assignee_id: event.target.value || null })}>
                        <option value="">Требует уточнения</option>
                        {participants.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
                      </select></label>
                      <label>Срок<input type="date" value={draft.due_date || ""} onChange={(event) => setDraft({ ...draft, due_date: event.target.value || null })} /></label>
                    </div>
                    {error && <p className="form-error" role="alert">{error}</p>}
                    <label><input type="checkbox" checked={draft.reviewed ?? false} onChange={(event) => setDraft({ ...draft, reviewed: event.target.checked })} />Я проверил поручение, ответственного и срок</label>
                    <div className="button-row"><button type="submit" className="primary-button" disabled={saving}>{saving ? "Сохраняем…" : "Сохранить"}</button>
                      <button type="button" onClick={() => { setEditingId(null); setDraft(null); }} disabled={saving}>Отмена</button></div>
                  </form>
                </td></tr> :
                <tr key={item.id}>
                  <td data-label="Поручение"><strong className="task-text">{item.text}</strong>{item.needs_review && <span className="review-note">Требует проверки: {item.review_reason || "уточните данные"}</span>}{item.deadline_text && <small>Срок в записи: {item.deadline_text}</small>}</td>
                  <td data-label="Ответственный">{participants.find((person) => person.id === item.assignee_id)?.name || "Требует уточнения"}</td>
                  <td data-label="Срок">{formatDate(item.due_date)}</td>
                  <td data-label="Действия"><div className="task-actions">
                    {editable && <button type="button" onClick={() => startEditing(item)}>Изменить</button>}
                    {item.source_segment_ids.length > 0 && <button type="button" onClick={() => onShowSource(item)}>Посмотреть источник</button>}
                    {item.source_segment_ids.length > 0 && <button type="button" onClick={() => onPlaySource(item)} disabled={!hasAudio} title={!hasAudio ? "Аудиозапись недоступна" : undefined}>Прослушать источник</button>}
                  </div></td>
                </tr>)}
            </tbody>
          </table>
        </div>}
    </section>
  );
}
