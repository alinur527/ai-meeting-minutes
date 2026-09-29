export function Summary({ text }: { text: string | null }) {
  return (
    <section className="panel" aria-labelledby="summary-heading">
      <div className="section-heading"><p className="eyebrow">Обзор</p><h2 id="summary-heading">Краткое содержание</h2></div>
      <p className="summary-text">{text || "Краткое содержание пока не готово."}</p>
    </section>
  );
}
