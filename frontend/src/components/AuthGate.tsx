import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, getSession, login, logout, type SessionUser } from "../api/meetings";

export function AuthGate({ children }: { children: ReactNode }) {
  const demo = import.meta.env.VITE_USE_MOCK === "true";
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(!demo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  useEffect(() => {
    if (demo) return;
    let active = true;
    void getSession().then((value) => { if (active) setUser(value); }).catch((cause) => {
      if (active && (!(cause instanceof ApiError) || cause.status !== 401)) setError("Сервер недоступен. Повторите вход позже.");
    }).finally(() => { if (active) setLoading(false); });
    const expired = () => { setUser(null); setError("Сессия завершилась. Войдите снова."); };
    window.addEventListener("alem:unauthorized", expired);
    return () => { active = false; window.removeEventListener("alem:unauthorized", expired); };
  }, [demo]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try { setUser(await login(email, password)); setPassword(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось войти"); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="page-shell"><p role="status">Проверяем сессию…</p></main>;
  if (demo) return children;
  if (!user) return <main className="page-shell"><section className="panel login-panel"><h1>Вход в AlemProtocol</h1>
    <p>Учётную запись создаёт администратор команды.</p>
    <form className="upload-form" onSubmit={(event) => void submit(event)}>
      <label>Email<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label>Пароль<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p role="alert">{error}</p>}
      <button className="primary-button" disabled={busy}>{busy ? "Входим…" : "Войти"}</button>
    </form></section></main>;
  return <><div className="account-bar"><span>{user.name}</span><button disabled={busy} onClick={() => {
    setBusy(true); void logout().then(() => setUser(null)).catch((cause) => setError(cause.message)).finally(() => setBusy(false));
  }}>Выйти</button>{error && <span role="alert">{error}</span>}</div>{children}</>;
}
