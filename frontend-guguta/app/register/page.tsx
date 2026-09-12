"use client";

import { useState } from "react";
import { registerPassword } from "../../lib/api";
import { withBase } from "../../lib/paths";

export default function RegisterPage() {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!firstName.trim() || !lastName.trim() || !email.trim() || password.length < 8) return;
    if (password !== confirmPassword) {
      setError("Parolele nu coincid.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerPassword(firstName.trim(), lastName.trim(), email.trim(), password);
      window.location.href = withBase("/app");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <section className="auth-shell" aria-labelledby="register-title">
      <div className="auth-visual">
        <h1 id="register-title">Creează contul Guguță</h1>
        <p>Înregistrează-te pentru a salva carnetele digitale și pentru a reveni oricând la materialele tale.</p>
      </div>

      <div className="auth-card">
        {error && <p className="error-text">{error}</p>}
        <form onSubmit={submit} className="auth-form">
          <div className="auth-two-cols">
            <label>
              <span>Prenume</span>
              <input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="Maria"
                autoComplete="given-name"
              />
            </label>
            <label>
              <span>Nume</span>
              <input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Popescu"
                autoComplete="family-name"
              />
            </label>
          </div>
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
              placeholder="Minimum 8 caractere"
              autoComplete="new-password"
            />
          </label>
          <label>
            <span>Confirmă parola</span>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repetă parola"
              autoComplete="new-password"
            />
          </label>
          <button
            className="primary auth-submit"
            disabled={
              busy ||
              !firstName.trim() ||
              !lastName.trim() ||
              !email.trim() ||
              password.length < 8 ||
              password !== confirmPassword
            }
          >
            {busy ? "Se creează contul…" : "Creează cont"}
          </button>
          <p className="auth-switch">
            Ai deja cont? <a href={withBase("/login")}>Intră în cont</a>
          </p>
        </form>
      </div>
    </section>
  );
}
