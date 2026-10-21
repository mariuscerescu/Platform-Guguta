"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { withBase } from "../../lib/paths";

/**
 * Conversație ghidată cu Guguță pentru înregistrare și autentificare.
 *
 * Guguță pune întrebările pe rând, elevul răspunde în câmpul de jos (sau alege
 * o variantă), iar răspunsurile completează „fișa” din dreapta. Scenariul este
 * determinist (nu trece prin model): întrebările, validările și ordinea vin
 * din `steps`. Parola nu apare niciodată în transcript.
 */

export type TalkValues = Record<string, string>;

export interface TalkOption {
  value: string;
  label: string;
}

export interface TalkStep {
  id: string;
  kind: "text" | "email" | "password" | "choice" | "confirm" | "review";
  /** Replica lui Guguță; primește valorile de până acum. */
  ask: (values: TalkValues) => string;
  /** Conținut suplimentar sub replică (linkuri, explicații). */
  extra?: (values: TalkValues) => ReactNode;
  placeholder?: string;
  autoComplete?: string;
  options?: TalkOption[];
  /** confirm: etichetele butoanelor și ce spune Guguță la refuz. */
  confirmLabel?: string;
  declineLabel?: string;
  declineSay?: string;
  /** Mesaj de eroare sau null dacă răspunsul e bun. */
  validate?: (value: string, values: TalkValues) => string | null;
  /** Pasul se sare pentru valorile curente. */
  skip?: (values: TalkValues) => boolean;
  /** Cum apare în fișa din dreapta; lipsă = nu apare. */
  field?: { label: string; mask?: boolean; format?: (value: string) => string };
  /** review: ce câmpuri se recapitulează. */
  reviewOf?: string[];
  /** Replica lui Guguță după un răspuns acceptat (opțional). */
  after?: (value: string, values: TalkValues) => string | null;
}

interface Bubble {
  who: "guguta" | "elev";
  text: string;
  extra?: ReactNode;
}

interface Props {
  title: string;
  intro: string[];
  steps: TalkStep[];
  /** Eticheta fișei din dreapta. */
  sheetTitle: string;
  submitLabel: string;
  /** Returnează null la succes sau mesajul de eroare și pasul la care se revine. */
  onComplete: (values: TalkValues) => Promise<{ error: string; stepId?: string } | null>;
  footer?: ReactNode;
}

function labelFor(step: TalkStep, value: string): string {
  if (step.field?.mask) return "•".repeat(Math.min(12, value.length));
  if (step.field?.format) return step.field.format(value);
  if (step.kind === "choice") return step.options?.find((o) => o.value === value)?.label ?? value;
  return value;
}

export default function AuthConversation({ title, intro, steps, sheetTitle, submitLabel, onComplete, footer }: Props) {
  const [values, setValues] = useState<TalkValues>({});
  const [index, setIndex] = useState(0);
  const [returnTo, setReturnTo] = useState<number | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  const step = steps[index];

  function say(text: string, extra?: ReactNode) {
    setBubbles((b) => [...b, { who: "guguta", text, extra }]);
  }

  function nextIndex(from: number, current: TalkValues): number {
    let i = from + 1;
    while (i < steps.length && steps[i].skip?.(current)) i += 1;
    return i;
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setBubbles([...intro.map((text) => ({ who: "guguta" as const, text })), { who: "guguta", text: steps[0].ask({}), extra: steps[0].extra?.({}) }]);
  }, [intro, steps]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (step && (step.kind === "text" || step.kind === "email" || step.kind === "password")) inputRef.current?.focus();
  }, [bubbles, step]);

  async function finish(current: TalkValues) {
    setBusy(true);
    const result = await onComplete(current);
    setBusy(false);
    if (!result) { setDone(true); return; }
    say(result.error);
    const target = result.stepId ? steps.findIndex((s) => s.id === result.stepId) : -1;
    if (target >= 0) {
      setIndex(target);
      setReturnTo(null);
      say(steps[target].ask(current), steps[target].extra?.(current));
    } else {
      setIndex(steps.length - 1);
    }
  }

  function advance(current: TalkValues, value: string) {
    const follow = step.after?.(value, current);
    if (follow) say(follow);
    let target: number;
    if (returnTo !== null) { target = returnTo; setReturnTo(null); }
    else target = nextIndex(index, current);
    if (target >= steps.length) { void finish(current); return; }
    setIndex(target);
    say(steps[target].ask(current), steps[target].extra?.(current));
  }

  function answer(raw: string) {
    if (!step || busy) return;
    const value = step.kind === "password" ? raw : raw.trim();
    const problem = step.validate?.(value, values) ?? (value ? null : "Scrie, te rog, un răspuns.");
    if (problem) { setError(problem); return; }
    setError(null);
    const current = { ...values, [step.id]: value };
    setValues(current);
    setBubbles((b) => [...b, { who: "elev", text: step.kind === "password" ? "•".repeat(Math.min(12, value.length)) : labelFor(step, value) }]);
    setInput("");
    advance(current, value);
  }

  function confirm(accepted: boolean) {
    if (!step || busy) return;
    if (!accepted) {
      setBubbles((b) => [...b, { who: "elev", text: step.declineLabel ?? "Nu" }]);
      if (step.declineSay) say(step.declineSay);
      return;
    }
    const current = { ...values, [step.id]: "da" };
    setValues(current);
    setBubbles((b) => [...b, { who: "elev", text: step.confirmLabel ?? "Da" }]);
    advance(current, "da");
  }

  function correct(fieldId: string) {
    const target = steps.findIndex((s) => s.id === fieldId);
    if (target < 0 || busy) return;
    setBubbles((b) => [...b, { who: "elev", text: `Vreau să corectez: ${steps[target].field?.label ?? fieldId}` }]);
    setReturnTo(index);
    setIndex(target);
    setInput(steps[target].kind === "password" ? "" : values[fieldId] ?? "");
    say(steps[target].ask(values), steps[target].extra?.(values));
  }

  const sheetSteps = steps.filter((s) => s.field && values[s.id] !== undefined);
  const inputType = step?.kind === "password" ? "password" : step?.kind === "email" ? "email" : "text";

  return (
    <section className="auth-shell talk-shell" aria-labelledby="talk-title">
      <div className="talk-column">
        <div className="talk-head">
          <img className="talk-mascot" src={withBase("/guguta-companion/assets/guguta.webp")} alt="" width={96} height={96} />
          <div>
            <h1 id="talk-title">{title}</h1>
            <p className="muted">Guguță te întreabă, tu răspunzi. Poți corecta orice înainte de final.</p>
          </div>
        </div>
        <div className="talk-log" role="log" aria-live="polite" aria-label="Conversația cu Guguță">
          {bubbles.map((bubble, i) => (
            <div key={i} className={`talk-bubble ${bubble.who}`}>
              {bubble.who === "guguta" && <span className="talk-who">Guguță</span>}
              <p>{bubble.text}</p>
              {bubble.extra && <div className="talk-extra">{bubble.extra}</div>}
            </div>
          ))}
          <div ref={endRef} />
        </div>
        {!done && step && (
          <div className="talk-input" data-step={step.id}>
            {error && <p className="error-text" role="alert">{error}</p>}
            {(step.kind === "text" || step.kind === "email" || step.kind === "password") && (
              <form onSubmit={(e) => { e.preventDefault(); answer(input); }} className="talk-form">
                <label className="sr-only" htmlFor="talk-answer">{step.field?.label ?? "Răspunsul tău"}</label>
                <input
                  id="talk-answer"
                  ref={inputRef}
                  type={inputType}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={step.placeholder ?? "Scrie răspunsul aici…"}
                  autoComplete={step.autoComplete ?? "off"}
                  disabled={busy}
                />
                <button className="primary" type="submit" disabled={busy || !input}>{busy ? "…" : "Trimite"}</button>
              </form>
            )}
            {step.kind === "choice" && (
              <div className="talk-choices" role="group" aria-label={step.field?.label ?? "Alege"}>
                {step.options?.map((option) => (
                  <button key={option.value} type="button" className="chip" disabled={busy} onClick={() => answer(option.value)}>{option.label}</button>
                ))}
              </div>
            )}
            {step.kind === "confirm" && (
              <div className="talk-choices">
                <button type="button" className="primary" disabled={busy} onClick={() => confirm(true)}>{busy ? "…" : (step.confirmLabel ?? "Da")}</button>
                <button type="button" className="chip" disabled={busy} onClick={() => confirm(false)}>{step.declineLabel ?? "Nu"}</button>
              </div>
            )}
            {step.kind === "review" && (
              <div className="talk-review">
                <ul>
                  {(step.reviewOf ?? []).map((id) => {
                    const s = steps.find((x) => x.id === id);
                    if (!s || values[id] === undefined) return null;
                    return (
                      <li key={id}>
                        <span>{s.field?.label ?? id}</span>
                        <strong>{labelFor(s, values[id])}</strong>
                        <button type="button" className="chip" disabled={busy} onClick={() => correct(id)}>Corectează</button>
                      </li>
                    );
                  })}
                </ul>
                <button type="button" className="primary" disabled={busy} onClick={() => confirm(true)}>{busy ? "…" : (step.confirmLabel ?? "Totul e corect")}</button>
              </div>
            )}
          </div>
        )}
        {footer}
      </div>

      <aside className="auth-card talk-sheet" aria-label={sheetTitle}>
        <h2>{sheetTitle}</h2>
        {sheetSteps.length === 0 && <p className="muted">Se completează pe măsură ce răspunzi.</p>}
        <dl>
          {sheetSteps.map((s) => (
            <div key={s.id} className={s.id === step?.id ? "current" : undefined}>
              <dt>{s.field!.label}</dt>
              <dd>{labelFor(s, values[s.id])}</dd>
            </div>
          ))}
        </dl>
        {done && <p className="talk-done">{submitLabel}</p>}
      </aside>
    </section>
  );
}
