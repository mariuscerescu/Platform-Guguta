"use client";

import { useEffect, useMemo, useState } from "react";
import AuthConversation, { type TalkStep, type TalkValues } from "../components/AuthConversation";
import { authMode, loginDev, loginPassword } from "../../lib/api";
import { withBase, API_BASE } from "../../lib/paths";

export default function LoginPage() {
  const [devName, setDevName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<string>("password");
  const destination = () => {
    return sessionStorage.getItem("guguta_pending_import") ? withBase("/import") : withBase("/app");
  };

  useEffect(() => {
    void authMode().then((value) => {
      setMode(value);
      if (value === "oidc") {
        window.location.href = `${API_BASE}/api/v1/auth/oidc/login?next=${encodeURIComponent(destination())}`;
      }
    });
  }, []);

  async function submitDev(e: React.FormEvent) {
    e.preventDefault();
    if (!devName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await loginDev(devName.trim());
      window.location.href = destination();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const steps = useMemo<TalkStep[]>(() => [
    {
      id: "email", kind: "email", field: { label: "E-mail" }, autoComplete: "email", placeholder: "nume@exemplu.md",
      ask: () => "Bine ai revenit! Spune-mi e-mailul cu care te-ai înregistrat.",
      validate: (v) => (/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v) ? null : "Adresa de e-mail nu arată bine."),
    },
    {
      id: "password", kind: "password", field: { label: "Parola", mask: true }, autoComplete: "current-password", placeholder: "Parola ta",
      ask: () => "Acum parola, cheia de la dulapul tău cu carnete.",
    },
  ], []);

  async function completeLogin(values: TalkValues) {
    try {
      await loginPassword(values.email, values.password);
      window.location.href = destination();
      return null;
    } catch (err) {
      return { error: `${(err as Error).message} Hai să încercăm din nou.`, stepId: "email" };
    }
  }

  if (mode === "password") {
    return (
      <AuthConversation
        title="Intră în Guguță"
        intro={["Bună! Eu sunt Guguță."]}
        steps={steps}
        sheetTitle="Contul tău"
        submitLabel="Te-am recunoscut. Deschid carnetele…"
        onComplete={completeLogin}
        footer={<p className="auth-switch">Nu ai cont? <a href={withBase("/register")}>Creează unul</a></p>}
      />
    );
  }

  return (
    <section className="auth-shell" aria-labelledby="login-title">
      <div className="auth-visual">
        <h1 id="login-title">Intră în Guguță</h1>
        <p>Continuă să lucrezi cu materialele tale, carnetele digitale și răspunsurile cu surse.</p>
      </div>

      <div className="auth-card">
        {error && <p className="error-text">{error}</p>}

        {mode === "test" && (
          <form onSubmit={submitDev} className="auth-form">
            <p className="muted">Mod de dezvoltare: cont sintetic local.</p>
            <label>
              <span>Numele tău</span>
              <input
                value={devName}
                onChange={(e) => setDevName(e.target.value)}
                placeholder="ex. Maria Popescu"
              />
            </label>
            <button className="primary auth-submit" disabled={busy || !devName.trim()}>
              {busy ? "Se conectează…" : "Intră în Guguță"}
            </button>
          </form>
        )}

        {mode === "oidc" && <p className="muted">Te trimitem către autentificare…</p>}
      </div>
    </section>
  );
}
