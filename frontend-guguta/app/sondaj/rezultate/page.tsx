"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, withBase } from "../../../lib/paths";
import { surveyRequest, type SurveyQuestion, type SurveyResults } from "../../../lib/survey";

function WrittenAnswers({ question }: { question: SurveyQuestion }) {
  const [comments, setComments] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const count = question.written_count ?? 0;
  useEffect(() => {
    let active = true;
    setBusy(true); setError("");
    void surveyRequest<{ comments: string[] }>(`/comments?question=${question.id}&offset=0`).then(result => {
      if (active) setComments(result.comments);
    }).catch(() => { if (active) setError("Nu am putut încărca răspunsurile scrise."); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [question.id, count]);

  async function more() {
    setBusy(true); setError("");
    try {
      const next = await surveyRequest<{ comments: string[] }>(`/comments?question=${question.id}&offset=${comments.length}`);
      setComments(current => [...current, ...next.comments]);
    } catch { setError("Nu am putut încărca răspunsurile scrise."); }
    finally { setBusy(false); }
  }
  return <>
    <p className="survey-help">{count} răspunsuri scrise · întrebarea a fost opțională</p>
    {!count && <p>Încă nu sunt răspunsuri la această întrebare.</p>}
    <ul className="survey-comments">{comments.map((comment, i) => <li key={`${question.id}-${i}`}>{comment}</li>)}</ul>
    {error && <p role="alert" className="survey-error">{error}</p>}
    {(comments.length < count || error) && <button className="survey-secondary" disabled={busy} onClick={() => void more()}>{busy ? "Se încarcă…" : error ? "Reîncearcă" : "Mai multe răspunsuri"}</button>}
  </>;
}

export default function SurveyResultsPage() {
  const [results, setResults] = useState<SurveyResults | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState("");
  const refresh = useCallback(async () => {
    setBusy(true);
    try { setResults(await surveyRequest<SurveyResults>("/results")); setError(""); setUpdated(new Date().toLocaleTimeString("ro-MD")); }
    catch { setError("Rezultatele nu se pot încărca acum. Încearcă din nou."); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 30_000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  return <>
    <nav className="survey-nav" aria-label="Sondaj"><a href={withBase("/sondaj")}>← Completează sondajul</a><a href={withBase("/")}>Platforma Guguță ↗</a></nav>
    <section className="survey-card survey-results-heading">
      <span className="survey-eyebrow">FEEDBACK DE LA ELEVI</span>
      <h1>Ce spun elevii despre Guguță</h1>
      <p>Rezultatele sunt publice: distribuția variantelor alese și toate comentariile anonime. Nu afișăm răspunsurile grupate pe elev.</p>
      <div className="survey-results-total"><strong>{results ? results.total.toLocaleString("ro-MD") : "…"}</strong><span>chestionare completate</span></div>
      <div className="survey-controls"><button className="survey-secondary" disabled={busy} onClick={() => void refresh()}>{busy ? "Se actualizează…" : "Actualizează"}</button>
        <a className="survey-secondary" href={`${API_BASE}/api/v1/survey/export.csv`} download>Descarcă rezultatele (CSV)</a></div>
      <p className="survey-help">{updated ? `Actualizat la ${updated}. ` : ""}Actualizare automată la 30 de secunde.</p>
      <p className="survey-help">Sondaj voluntar, fără note. Rezultatele descriu răspunsurile primite și nu reprezintă opiniile tuturor elevilor. „Nu am folosit / Nu pot aprecia” nu intră în medii.</p>
      {error && <p className="survey-error" role="alert">{error}</p>}
      {results?.total === 0 && <p className="survey-empty">Încă nu a fost trimis niciun chestionar. Primele răspunsuri vor apărea aici.</p>}
    </section>
    {results && <div className="survey-results-grid">{results.questions.map(question => <section className={`survey-result-card ${question.type === "text" ? "survey-result-card--text" : ""}`} key={question.id}>
      <span className="survey-eyebrow">ÎNTREBAREA {question.number}</span>
      <h2>{question.title}</h2>
      {question.type === "text" ? <WrittenAnswers question={question} /> : <>
        {question.mean != null && <p className="survey-average"><strong>{question.mean.toLocaleString("ro-MD", { maximumFractionDigits: 2 })} / 5</strong><span>{question.rated_count} evaluări</span></p>}
        <ul className="survey-bars">{question.options.map(option => {
          const count = option.count ?? 0;
          const percent = results.total ? Math.round(count * 1000 / results.total) / 10 : 0;
          return <li key={option.value}><div><span>{option.label}</span><strong>{count} <small>({percent.toLocaleString("ro-MD")}%)</small></strong></div>
            <div className="survey-bar-track" aria-hidden="true"><span style={{ width: `${percent}%` }} /></div>
          </li>;
        })}</ul>
        {question.type === "multiple" && <p className="survey-help">Au putut fi alese până la 3 variante. Procentele pot însuma mai mult de 100%.</p>}
      </>}
    </section>)}</div>}
  </>;
}
