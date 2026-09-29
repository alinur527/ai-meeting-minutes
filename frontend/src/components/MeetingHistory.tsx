import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listMeetings } from "../api/meetings";
import type { MeetingListItem } from "../types/meeting";

export function MeetingHistory() {
  const [items, setItems] = useState<MeetingListItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void listMeetings(controller.signal, offset).then((result) => {
      if (!controller.signal.aborted) { setItems((old) => offset ? [...old, ...result.items] : result.items); setMore(result.items.length === 50); setError(""); }
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset]);
  return <section className="panel"><h2>Мои совещания</h2>
    {error && <p role="alert">{error}</p>}
    {!loading && !items.length && !error && <p>Сохранённых совещаний пока нет.</p>}
    <ul className="meeting-history">{items.map((item) => <li key={item.id}><Link to={`/meetings/${item.id}`}>{item.title}</Link><span>{item.confirmed_at ? "Подтверждён" : ({ queued: "В очереди", running: "Обрабатывается", completed: "Готово", failed: "Ошибка" })[item.status]}</span></li>)}</ul>
    {loading && <p role="status">Загружаем историю…</p>}
    {more && <button disabled={loading} onClick={() => { setLoading(true); setOffset((value) => value + 50); }}>Ещё совещания</button>}
  </section>;
}
