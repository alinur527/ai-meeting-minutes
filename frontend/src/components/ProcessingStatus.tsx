import type { MeetingStatus } from "../types/meeting";

const labels: Record<MeetingStatus, string> = {
  queued: "В очереди",
  running: "Обрабатывается",
  completed: "Готово",
  failed: "Ошибка обработки",
};

export function ProcessingStatus({ status, error, stage }: { status: MeetingStatus; error: string | null; stage?: string }) {
  return (
    <div className={`processing-status status-${status}`} role="status" aria-live="polite">
      <strong>{labels[status]}</strong>
      {status === "queued" && <span>Запись ожидает обработки. Страница обновится автоматически.</span>}
      {stage === "waiting_retry" && <span>Временная ошибка связи с AI. Повтор запланирован автоматически.</span>}
      {status === "running" && <span>Распознаём речь и составляем протокол. Страница обновится автоматически.</span>}
      {status === "failed" && <span>{error || "Обработка не удалась. Попробуйте загрузить запись заново."}</span>}
    </div>
  );
}
