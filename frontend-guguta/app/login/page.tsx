"use client";

import { useEffect, useState } from "react";
import { authMode, loginDev, loginPassword } from "../../lib/api";
import { withBase, API_BASE } from "../../lib/paths";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [devName, setDevName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<string>("password");
  const destination = () => sessionStorage.getItem("guguta_pending_import") ? withBase("/import") : withBase("/app");

  useEffect(() => {
    void authMode().then((value) => {
      setMode(value);
      if (value === "oidc") {
        window.location.href = `${API_BASE}/api/v1/auth/oidc/login?next=${encodeURIComponent(destination())}`;
      }
    });
  }, []);

  async function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await loginPassword(email.trim(), password);
      window.location.href = destination();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

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

  return (
    <section className="auth-shell" aria-labelledby="login-title">
      <div className="auth-visual">
        <h1 id="login-title">Intră în Guguță</h1>
        <p>Continuă să lucrezi cu materialele tale, carnetele digitale și răspunsurile cu surse.</p>
      </div>

      <div className="auth-card">
        {error && <p className="error-text">{error}</p>}

        {mode === "password" && (
          <form onSubmit={submitPassword} className="auth-form">
            <label>
              <span>Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nume@exemplu.md"
                autoComplete="email"
              />
            </label>
            <label>
              <span>Parolă</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Parola ta"
                autoComplete="current-password"
              />
            </label>
            <button className="primary auth-submit" disabled={busy || !email.trim() || !password}>
              {busy ? "Se conectează…" : "Intră în cont"}
            </button>
            <p className="auth-switch">
              Nu ai cont? <a href={withBase("/register")}>Creează unul</a>
            </p>
          </form>
        )}

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
