"use client";

import { useRef, useState } from "react";
import SchoolField from "../components/SchoolField";
import { ApiError, registerPassword } from "../../lib/api";
import { withBase } from "../../lib/paths";

const CLASSES = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const PARENT_CLASSES = new Set(CLASSES.slice(0, 8));

export default function RegisterPage() {
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [school, setSchool] = useState("");
  const [classLevel, setClassLevel] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [privacyAccepted, setPrivacyAccepted] = useState(false);
  const [parentConsent, setParentConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const needsParent = PARENT_CLASSES.has(classLevel);
  const canSubmit = firstName.trim() && lastName.trim() && school.trim().length >= 2 &&
    classLevel && email.trim() && password.length >= 8 && confirmPassword &&
    privacyAccepted && (!needsParent || parentConsent);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !canSubmit) return;
    if (password !== confirmPassword) {
      setError("Parolele nu coincid.");
      confirmRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerPassword({
        firstName: firstName.trim(), lastName: lastName.trim(), email: email.trim(), password,
        school: school.trim(), classLevel, privacyAccepted, parentConsent: needsParent && parentConsent,
      });
      window.location.href = withBase("/app");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nu am putut crea contul. Încearcă din nou.");
      setBusy(false);
    }
  }

  return (
    <section className="auth-shell register-shell" aria-labelledby="register-title">
      <div className="auth-visual">
        <h1 id="register-title">Creează contul Guguță</h1>
        <p>Înregistrează-te pentru a salva carnetele digitale și pentru a reveni oricând la materialele tale.</p>
      </div>

      <div className="auth-card">
        {error && <p className="error-text" role="alert">{error}</p>}
        <form onSubmit={submit} className="auth-form">
          <div className="auth-two-cols">
            <label>
              <span>Prenume</span>
              <input name="given-name" required maxLength={120} autoComplete="given-name" placeholder="Maria" value={firstName} onChange={(e) => setFirstName(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span>Nume</span>
              <input name="family-name" required maxLength={120} autoComplete="family-name" placeholder="Popescu" value={lastName} onChange={(e) => setLastName(e.target.value)} disabled={busy} />
            </label>
          </div>

          <SchoolField value={school} onChange={setSchool} disabled={busy} />

          <div className="auth-two-cols register-email-class">
            <label>
              <span>Email</span>
              <input name="email" type="email" required maxLength={320} autoComplete="email" placeholder="nume@exemplu.md" value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span id="register-class-label">Clasa</span>
              <select name="class-level" aria-labelledby="register-class-label" required value={classLevel} onChange={(e) => setClassLevel(e.target.value)} disabled={busy}>
                <option value="">Selectează</option>
                {CLASSES.map((c) => <option key={c} value={c}>Clasa {c}</option>)}
              </select>
            </label>
          </div>

          <div className="auth-two-cols">
            <label>
              <span>Parolă</span>
              <input name="password" type="password" required minLength={8} maxLength={256} autoComplete="new-password" placeholder="Minimum 8 caractere" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
            </label>
            <label>
              <span>Confirmă parola</span>
              <input ref={confirmRef} name="confirm-password" type="password" required minLength={8} maxLength={256} autoComplete="new-password" placeholder="Repetă parola" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} disabled={busy} />
            </label>
          </div>

          <label className="auth-checkbox">
            <input type="checkbox" required checked={privacyAccepted} onChange={(e) => setPrivacyAccepted(e.target.checked)} disabled={busy} />
            <span>Accept <a href={withBase("/termeni")} target="_blank" rel="noopener">Termenii de utilizare</a> și <a href={withBase("/confidentialitate")} target="_blank" rel="noopener">Politica de confidențialitate</a>.</span>
          </label>
          {needsParent && (
            <label className="auth-checkbox">
              <input type="checkbox" required checked={parentConsent} onChange={(e) => setParentConsent(e.target.checked)} disabled={busy} />
              <span>Confirm că sunt părintele sau tutorele și sunt de acord cu crearea contului copilului.</span>
            </label>
          )}

          <button className="primary auth-submit" disabled={busy || !canSubmit}>
            {busy ? "Se creează contul…" : "Creează cont"}
          </button>
          <p className="auth-switch">Ai deja cont? <a href={withBase("/login")}>Intră în cont</a></p>
        </form>
      </div>
    </section>
  );
}
