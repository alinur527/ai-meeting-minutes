import { UploadForm } from "../components/UploadForm";
import { Link } from "react-router-dom";
import { MeetingHistory } from "../components/MeetingHistory";

export function HomePage() {
  const isMockMode = import.meta.env.VITE_USE_MOCK === "true";

  return (
    <main className="page-shell home-page">
      <nav className="top-nav" aria-label="Основная навигация"><Link className="brand" to="/">AlemProtocol</Link>{isMockMode && <Link to="/meetings/demo">Открыть демо</Link>}</nav>
      <header className="home-header">

        {isMockMode && (
          <p className="demo-badge" role="status">DEMO / MOCK MODE</p>
        )}

        <h1>Автоматический протокол совещания</h1>
        <p>
          Загрузите запись, чтобы получить транскрипт, краткое содержание
          и список поручений.
        </p>
      </header>

      <section className="panel upload-panel" aria-labelledby="upload-heading">
        <h2 id="upload-heading">Новое совещание</h2>
        <UploadForm />
      </section>
      {!isMockMode && <MeetingHistory />}
    </main>
  );
}
