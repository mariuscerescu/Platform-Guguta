"use client";

import { useEffect, useState } from "react";
import { api, bootstrapCsrf, me, setCsrf } from "../../lib/api";
import { withBase } from "../../lib/paths";

export default function LogoutButton() {
  const [authenticated, setAuthenticated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void me().then((user) => { if (alive) setAuthenticated(user !== null); });
    return () => { alive = false; };
  }, []);

  async function logout() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await bootstrapCsrf();
      await api("POST", "/api/v1/auth/logout");
      setCsrf("");
      window.location.replace(withBase("/login"));
    } catch {
      setError("Delogarea a eșuat. Te rugăm să reîncerci.");
      setBusy(false);
    }
  }

  if (!authenticated) return null;

  return (
    <div className="logout-control">
      <button type="button" className="logout-button" onClick={() => void logout()}
        disabled={busy} aria-label="Delogare" aria-busy={busy}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M9 5H5v14h4M9 12h11m-4-4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>{busy ? "Se deloghează…" : "Delogare"}</span>
      </button>
      {error && <p className="logout-error" role="alert">{error}</p>}
    </div>
  );
}
