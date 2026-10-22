"use client";

import { useEffect, useRef, useState } from "react";
import { withBase } from "../../lib/paths";
import { hasAnswer, surveyRequest, type Questionnaire, type SurveyAnswers, type SurveySession } from "../../lib/survey";
import SurveyQr from "./SurveyQr";

const DRAFT_KEY = "guguta.survey.draft.v1";
type Stage = "intro" | "questions" | "done";

export default function SurveyPage() {
  const [form, setForm] = useState<Questionnaire | null>(null);
  const [stage, setStage] = useState<Stage>("intro");
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<SurveyAnswers>({});
  const [session, setSession] = useState<SurveySession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [reload, setReload] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const sendLock = useRef(false);

  useEffect(() => {
    let active = true;
    void surveyRequest<Questionnaire>().then(data => {
      if (!active) return;
      setForm(data); setError("");
      try {
        const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
        if (saved?.version === data.version) {
          if (saved.completed) setStage("done");
          else if (saved.session && saved.answers && Number.isInteger(saved.index)) {
            setAnswers(saved.answers); setSession(saved.session);
            setIndex(Math.max(0, Math.min(19, saved.index))); setStage("questions");
          }
        }
      } catch { /* Storage is optional on shared/restricted school browsers. */ }
      setLoaded(true);
    }).catch(() => { if (active) setError("Nu am putut încărca sondajul. Verifică internetul și încearcă din nou."); });
    return () => { active = false; };
  }, [reload]);

  useEffect(() => {
    if (!loaded || !form || stage === "intro") return;
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(stage === "done" ? { version: form.version, completed: true }
        : { version: form.version, answers, index, session }));
    } catch { /* Form still works without browser storage. */ }
  }, [answers, index, session, stage, loaded, form]);

  useEffect(() => {
    if (stage !== "intro") {
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView({ block: "nearest" });
    }
  }, [stage, index]);

  async function start() {
    setBusy(true); setError("");
    try { setSession(await surveyRequest<SurveySession>("/session")); setStage("questions"); }
    catch { setError("Nu am putut începe sondajul. Încearcă din nou."); }
    finally { setBusy(false); }
  }

  function reset() {
    try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* optional */ }
    setAnswers({}); setSession(null); setIndex(0);
    setError(""); setStage("intro");
  }

  async function submit() {
    if (!form || !session || sendLock.current) return;
    const missing = form.questions.findIndex(q => !hasAnswer(q, answers[q.id]));
    if (missing >= 0) { setIndex(missing); setStage("questions"); return; }
    sendLock.current = true; setBusy(true); setError("");
    try {
      const complete = Object.fromEntries(form.questions.map(q => [q.id, answers[q.id] ?? ""]));
      const result = await surveyRequest<{ saved: boolean }>("/responses", { ...session, version: form.version, acknowledged: true, answers: complete });
      if (!result.saved) throw new Error("Răspunsurile nu au fost confirmate. Încearcă din nou.");
      setStage("done"); setAnswers({}); setSession(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Nu am putut salva răspunsurile. Încearcă din nou."); }
    finally { setBusy(false); sendLock.current = false; }
  }

  const question = form?.questions[index];
  const value = question ? answers[question.id] : undefined;

  if (!form) return <section className="survey-card"><p role={error ? "alert" : "status"}>{error || "Se încarcă sondajul…"}</p>{error && <button className="survey-primary" onClick={() => setReload(n => n + 1)}>Reîncearcă</button>}</section>;

  return <>
    <nav className="survey-nav" aria-label="Sondaj"><a href={withBase("/app")}>← Platforma Guguță</a><div className="survey-nav-actions"><a href={withBase("/sondaj/rezultate")}>Vezi rezultatele publice ↗</a><SurveyQr /></div></nav>
    <section className="survey-card">
      {stage === "intro" && <>
        <span className="survey-eyebrow">SONDAJ PENTRU ELEVI</span>
        <h1>Părerea ta despre Guguță</h1>
        <p className="survey-lead">Ai explorat platforma? Spune-ne cum ți s-a părut și ce putem îmbunătăți.</p>
        <div className="survey-facts"><span>20 de întrebări</span><span>Aproximativ 5 minute</span><span>Fără cont</span></div>
        <p>Nu există răspunsuri corecte sau greșite și nu primești o notă. Participarea este voluntară. Răspunde după experiența ta; dacă nu ai încercat o funcție, alege „Nu am folosit / Nu pot aprecia”.</p>
        <div className="survey-privacy">
          <strong>Anonim, cu rezultate publice</strong>
          <p>Nu cerem numele, emailul sau școala și nu legăm răspunsurile de contul tău. Graficele și răspunsurile scrise vor fi publice. Le folosim pentru îmbunătățirea platformei și cercetare educațională.</p>
          <p>În cele două întrebări libere, nu scrie nume, numere de telefon, emailuri, școala sau alte date care te pot identifica pe tine ori pe altcineva. Aceste întrebări sunt opționale.</p>
        </div>
        <button className="survey-primary" onClick={() => void start()} disabled={busy}>{busy ? "Se pregătește…" : "Începe sondajul →"}</button>
      </>}

      {stage === "questions" && question && <>
        <div className="survey-progress-label"><span>{question.section}</span><strong>{index + 1} / 20</strong></div>
        <progress value={index + 1} max={20} aria-label="Progresul chestionarului" />
        <h1 ref={heading} tabIndex={-1}>{question.title}</h1>
        <p className="survey-help">{question.type === "text" ? "Opțional. Răspunsul va fi public; nu include date personale." : question.type === "multiple" ? "Alege cel mult 3 variante." : "Alege o singură variantă."}</p>
        {question.type === "text" ? <div className="survey-writing">
          <textarea aria-label={question.title} rows={6} maxLength={1000} disabled={busy} value={typeof value === "string" ? value : ""}
            placeholder="Scrie aici, dacă dorești…" onChange={event => setAnswers(current => ({ ...current, [question.id]: event.target.value }))} />
          <span>{typeof value === "string" ? value.length : 0} / 1000</span>
        </div> : <fieldset className={`survey-options ${question.options.length > 7 ? "survey-options--columns" : ""}`}>
          <legend className="sr-only">{question.title}</legend>
          {question.options.map(option => {
            const checked = Array.isArray(value) ? value.includes(option.value) : value === option.value;
            const disabled = question.type === "multiple" && !checked && Array.isArray(value) && value.length >= 3 && !question.exclusive?.includes(option.value);
            return <label key={option.value} className={`survey-option ${checked ? "is-selected" : ""} ${disabled ? "is-disabled" : ""}`}>
              <input type={question.type === "multiple" ? "checkbox" : "radio"} name={question.id} value={option.value} checked={checked} disabled={disabled}
                onChange={() => {
                  if (question.type !== "multiple") setAnswers(current => ({ ...current, [question.id]: option.value }));
                  else {
                    const selected = Array.isArray(value) ? value : [];
                    const next = checked ? selected.filter(v => v !== option.value) : question.exclusive?.includes(option.value) ? [option.value]
                      : [...selected.filter(v => !question.exclusive?.includes(v)), option.value];
                    setAnswers(current => ({ ...current, [question.id]: next }));
                  }
                }} />
              <span>{option.label}</span>
            </label>;
          })}
        </fieldset>}
        {index === 19 && <p className="survey-help">Apăsând „Trimite răspunsurile”, ești de acord ca răspunsurile tale, inclusiv cele scrise, să fie publice. Nu include date personale.</p>}
        <div className="survey-controls">
          <button className="survey-secondary" disabled={busy} onClick={() => { setError(""); index ? setIndex(i => i - 1) : setStage("intro"); }}>← Înapoi</button>
          <button className="survey-primary" disabled={busy || !hasAnswer(question, value)} onClick={() => {
            setError(""); if (index === 19) void submit(); else setIndex(i => i + 1);
          }}>{busy ? "Se salvează răspunsurile…" : index === 19 ? "Trimite răspunsurile" : "Continuă →"}</button>
        </div>
        {error.includes("Sesiunea sondajului a expirat") && <button className="survey-secondary" disabled={busy} onClick={async () => {
          try { setSession(await surveyRequest<SurveySession>("/session")); setError(""); } catch { setError("Nu am putut reînnoi sesiunea. Încearcă din nou."); }
        }}>Reînnoiește sesiunea</button>}
      </>}

      {stage === "done" && <div className="survey-thanks">
        <span className="survey-success-mark" aria-hidden="true">✓</span>
        <h1 ref={heading} tabIndex={-1}>Mulțumim pentru părerea ta!</h1>
        <p>Răspunsurile au fost salvate. Ne ajută să îmbunătățim Guguță pentru elevi.</p>
        <a className="survey-primary" href={withBase("/sondaj/rezultate")}>Vezi rezultatele publice</a>
        <a className="survey-secondary" href={withBase("/app")}>Înapoi la platformă</a>
        <button className="survey-new" onClick={reset}>Alt elev folosește acest dispozitiv? Începe un chestionar nou.</button>
      </div>}
      {error && <p className="survey-error" role="alert">{error}</p>}
    </section>
    <p className="survey-bottom-note">Proiectul „Platformă Educațională bazată pe Inteligența Artificială Guguță” · 25.80012.0807.21TC</p>
  </>;
}
