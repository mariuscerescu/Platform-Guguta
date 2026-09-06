"use client";

import { useState } from "react";
import { loginDev } from "../../lib/api";

export default function LoginPage() {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      <p className="muted">
        Mod de dezvoltare: cont sintetic local. În producție autentificarea se
        face prin furnizorul de identitate al școlii (OIDC).
      </p>
      {error && <p className="error-text">{error}</p>}
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
      <p className="muted" style={{ marginTop: 24 }}>
        Cont de editor/administrator? Autentificarea OIDC:{" "}
        <a href="/guguta-api/api/v1/auth/oidc/login">conectare prin școală</a>
      </p>
    </>
  );
}
