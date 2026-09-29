import { useState, useEffect, useRef, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createMeeting, getCapabilities } from "../api/meetings";

import media from "../../../shared/alem_contract/media.json";

interface ParticipantDraft {
  id: string;
  name: string;
}

// These IDs are React keys only; backend assigns persistent participant UUIDs.
// A counter also works on plain HTTP LAN origins where randomUUID is unavailable.
let nextParticipantId = 0;

function createParticipant(): ParticipantDraft {
  return {
    id: `participant-${++nextParticipantId}`,
    name: "",
  };
}

export function UploadForm() {
  const navigate = useNavigate();
  const isMockMode = import.meta.env.VITE_USE_MOCK === "true";
  const [title, setTitle] = useState("");
  const [startedAt, setStartedAt] = useState("");
  const [participants, setParticipants] = useState<ParticipantDraft[]>(() => [
    createParticipant(),
  ]);
  const [maxUploadMb, setMaxUploadMb] = useState(media.max_upload_mb);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(isMockMode);
  const [profile, setProfile] = useState(isMockMode ? "frontend_demo" : "");
  const [maxSeconds, setMaxSeconds] = useState(media.max_audio_seconds);
  const uploadController = useRef<AbortController | null>(null);
  useEffect(() => {
    let active = true;
    if (!isMockMode) void getCapabilities().then((limits) => {
      if (active) { setMaxUploadMb(limits.max_upload_mb); setMaxSeconds(limits.max_audio_seconds); setProfile(limits.processing_profile); setReady(true); }
    }).catch(() => { if (active) setError("Не удалось получить ограничения сервера. Обновите страницу."); });
    return () => { active = false; uploadController.current?.abort(); };
  }, [isMockMode]);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function updateParticipant(id: string, name: string) {
    setParticipants((current) =>
      current.map((participant) =>
        participant.id === id ? { ...participant, name } : participant,
      ),
    );
  }

  function removeParticipant(id: string) {
    setParticipants((current) =>
      current.filter((participant) => participant.id !== id),
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || !ready) return;
    if (!file) { setError("Выберите аудиофайл."); return; }
    if (!media.extensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
      setError("Выберите запись в формате WAV, MP3 или M4A."); return;
    }
    if (file.size === 0 || file.size > maxUploadMb * 1024 * 1024) {
      setError(`Файл должен быть непустым и не больше ${maxUploadMb} МБ.`); return;
    }
    if (!title.trim() || participants.some(({ name }) => !name.trim())) {
      setError("Заполните название и имена участников."); return;
    }
    const startedDate = new Date(startedAt);
    if (Number.isNaN(startedDate.getTime())) {
      setError("Укажите дату и время совещания."); return;
    }
    setSubmitting(true);
    setError("");
    try {
      if (isMockMode) {
        navigate("/meetings/demo", { state: { audioFile: file } }); return;
      }
      uploadController.current = new AbortController();
      const result = await createMeeting({
        title: title.trim(),
        started_at: startedDate.toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        participants: participants.map(({ name }) => ({ name: name.trim() })),
        file,
      }, uploadController.current.signal);
      navigate(`/meetings/${encodeURIComponent(result.id)}`);
    } catch (cause) {
      if (uploadController.current?.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : "Не удалось загрузить запись.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="upload-form">
      {profile && <p className={profile === "real" ? "muted" : "demo-badge"} role="status">{profile === "real" ? "Обработка локальными моделями" : "Демонстрационный режим: запись не будет распознаваться"}</p>}
      <label>
        Название совещания
        <input
          type="text"
          value={title}
          maxLength={255}
          onChange={(event) => setTitle(event.target.value)}
          required
        />
      </label>

      <label>
        Дата и время
        <input
          type="datetime-local"
          value={startedAt}
          onChange={(event) => setStartedAt(event.target.value)}
          required
        />
      </label>

      <fieldset>
        <legend>Участники</legend>

        {participants.map((participant, index) => (
          <div key={participant.id}>
            <label>
              Участник {index + 1}
              <input
                type="text"
                value={participant.name}
                maxLength={255}
                onChange={(event) =>
                  updateParticipant(participant.id, event.target.value)
                }
                required
              />
            </label>

            {participants.length > 1 && (
              <button
                type="button"
                onClick={() => removeParticipant(participant.id)}
              >
                Удалить
              </button>
            )}
          </div>
        ))}

        <button
          type="button"
          disabled={participants.length >= media.max_participants}
          onClick={() =>
            setParticipants((current) => [...current, createParticipant()])
          }
        >
          Добавить участника
        </button>
      </fieldset>

      <label>
        Запись совещания
        <input
          type="file"
          accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          required
        />
      </label>

      <p className="muted">WAV, MP3 или M4A, до {maxUploadMb} МБ и {Math.floor(maxSeconds / 60)} минут.</p>

      {error && <p role="alert" className="form-error">{error}</p>}
      <button type="submit" className="primary-button" disabled={submitting || !ready}>{submitting ? "Загружаем…" : "Обработать совещание"}</button>
    </form>
  );
}
