"use client";

import { useEffect, useState } from "react";
import { authMode, loginDev } from "../../lib/api";

export default function LoginPage() {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<string | null>(null);

  useEffect(() => {
    void authMode().then(setMode);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await loginDev(name.trim());
      window.location.href = "/";
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Autentificare</h1>
      {error && <p className="error-text">{error}</p>}

      {mode === "test" && (
        <>
          <p className="muted">
            Mod de dezvoltare: cont sintetic local. În producție autentificarea
            se face prin furnizorul de identitate al școlii (OIDC).
          </p>
          <form onSubmit={submit} style={{ maxWidth: 360 }}>
            <label htmlFor="name" className="muted">
              Numele tău
            </label>
            <input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ex. Maria Popescu"
            />
            <button
              className="primary"
              style={{ marginTop: 12 }}
              disabled={busy || !name.trim()}
            >
              {busy ? "Se conectează…" : "Intră în Guguță"}
            </button>
          </form>
        </>
      )}

      {mode === "oidc" && (
        <p>
          <a className="btn" href="/guguta-api/api/v1/auth/oidc/login">
            Conectare prin școală (OIDC)
          </a>
        </p>
      )}

      {mode === null && <p className="muted">Se încarcă…</p>}
    </>
  );
}
