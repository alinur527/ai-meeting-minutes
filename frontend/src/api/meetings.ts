import type { ActionItem, CreateMeetingResponse, Meeting, MeetingListResponse, SpeakerMapping } from "../types/meeting";

const baseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
let csrfToken = "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
  get retryable() { return this.status === 0 || this.status === 429 || this.status >= 500; }
}

async function fetchChecked(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    if (init?.method && !["GET", "HEAD"].includes(init.method)) headers.set("X-CSRF-Token", csrfToken);
    response = await fetch(`${baseUrl}${path}`, { ...init, headers, credentials: "include" });
  } catch (cause) {
    if (init?.signal?.aborted) throw cause;
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение.", 0);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch { /* The server may return an empty error body. */ }
    if (response.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("alem:unauthorized"));
    throw new ApiError(detail || `Ошибка сервера (${response.status}).`, response.status);
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchChecked(path, init);
  const body = await response.text();
  return (body ? JSON.parse(body) : undefined) as T;
}

function jsonPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface NewMeeting {
  title: string;
  started_at: string;
  timezone: string;
  participants: { name: string }[];
  file: File;
}

export function createMeeting(input: NewMeeting, signal?: AbortSignal): Promise<CreateMeetingResponse> {
  const form = new FormData();
  form.append("title", input.title);
  form.append("started_at", input.started_at);
  form.append("timezone", input.timezone);
  form.append("participants_json", JSON.stringify(input.participants));
  form.append("file", input.file);
  return request<CreateMeetingResponse>("/meetings", { method: "POST", body: form, signal });
}

export function listMeetings(signal?: AbortSignal, offset = 0): Promise<MeetingListResponse> {
  return request<MeetingListResponse>(offset ? `/meetings?offset=${offset}` : "/meetings", { signal });
}

export function getMeeting(id: string, signal?: AbortSignal): Promise<Meeting> {
  return request<Meeting>(`/meetings/${encodeURIComponent(id)}`, { signal });
}

export function updateActionItem(meetingId: string, item: ActionItem): Promise<ActionItem> {
  return jsonPatch<ActionItem>(
    `/meetings/${encodeURIComponent(meetingId)}/tasks/${encodeURIComponent(item.id)}`,
    { text: item.text, assignee_id: item.assignee_id, due_date: item.due_date, reviewed: item.reviewed ?? false },
  );
}

export function updateSpeaker(meetingId: string, speaker: SpeakerMapping): Promise<unknown> {
  return jsonPatch<unknown>(
    `/meetings/${encodeURIComponent(meetingId)}/speakers`,
    { mappings: [{ speaker: speaker.label, participant_id: speaker.participant_id }] },
  );
}

export async function confirmMeeting(id: string): Promise<Meeting> {
  await request<unknown>(`/meetings/${encodeURIComponent(id)}/confirm`, { method: "POST" });
  return getMeeting(id);
}

export async function getMeetingAudio(id: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetchChecked(`/meetings/${encodeURIComponent(id)}/audio`, { signal });
  return response.blob();
}

export async function exportMeetingDocx(id: string): Promise<Blob> {
  const response = await fetchChecked(`/meetings/${encodeURIComponent(id)}/export?format=docx`);
  return response.blob();
}

export interface SessionUser { id: string; email: string; name: string; csrf_token: string }
export async function getSession(): Promise<SessionUser> {
  const user = await request<SessionUser>("/auth/session"); csrfToken = user.csrf_token; return user;
}
export async function login(email: string, password: string): Promise<SessionUser> {
  const user = await request<SessionUser>("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
  csrfToken = user.csrf_token; return user;
}
export async function logout() { await request("/auth/logout", { method: "POST" }); csrfToken = ""; }
export function retryMeeting(id: string) { return request<CreateMeetingResponse>(`/meetings/${encodeURIComponent(id)}/retry`, { method: "POST" }); }
export function reopenMeeting(id: string) { return request<CreateMeetingResponse>(`/meetings/${encodeURIComponent(id)}/reopen`, { method: "POST" }); }
export function meetingAudioUrl(id: string) { return `${baseUrl}/meetings/${encodeURIComponent(id)}/audio`; }
export interface Capabilities { extensions: string[]; max_upload_mb: number; max_audio_seconds: number; max_participants: number; processing_profile: string }
export function getCapabilities() { return request<Capabilities>("/capabilities"); }
