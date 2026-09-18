"use client";

import { useEffect, useState } from "react";
import { api, me } from "../../lib/api";
import { withBase } from "../../lib/paths";

interface PreviewData {
  snapshot_id: string;
  title: string;
  description?: string | null;
  material_count: number;
  materials: string[];
}

export default function ImportPage() {
  const [token, setToken] = useState("");
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // F05: extract the token from the URL fragment (#token=...) or query param
  useEffect(() => {
    const frag = window.location.hash;
    let incoming = "";
    if (frag.startsWith("#token=")) {
      incoming = decodeURIComponent(frag.slice(7));
      setToken(incoming);
      window.location.hash = ""; // clean the URL (don't leak in referrer)
    }
    const pending = sessionStorage.getItem("guguta_pending_import");
    if (!incoming && pending) setToken(pending);
    void me().then((u) => {
      setAuthed(u !== null);
      if (u !== null) sessionStorage.removeItem("guguta_pending_import");
    });
  }, []);

  async function doPreview() {
    setError(null);
    setPreview(null);
    try {
      setPreview(await api<PreviewData>("POST","/api/v1/imports/preview",{token:token.trim()}));
    } catch (err) {
      setError((err as Error).message || "Nu am putut verifica linkul.");
    }
  }

  async function doImport() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ notebook_id: string }>("POST", "/api/v1/imports", {
        token: token.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      if (r.notebook_id) {
        setDone(r.notebook_id);
        setPreview(null);
        setToken("");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (authed === false) {
    // preserve the token for after login (F05)
    sessionStorage.setItem("guguta_pending_import", token);
    return (
      <>
        <h1>Import materiale</h1>
        <p className="muted">
          Trebuie să te autentifici ca să poți importa materialele.
        </p>
        <a href={withBase("/login")} className="btn">Autentificare</a>
        <p className="muted" style={{ marginTop: 12 }}>
          Codul este păstrat în acest browser și va fi disponibil după autentificare.
        </p>
      </>
    );
  }

  return (
    <>
      <h1>Import materiale</h1>
      <p className="muted">
        Se transferă numai materialele. Conversațiile, notițele și memoria AI a
        autorului nu sunt incluse.
      </p>
      {error && <p className="error-text">{error}</p>}
      {done && (
        <div className="card">
          <h3>Import reușit!</h3>
          <p>
            Carnetul a fost creat. <a href={withBase(`/notebook/${done}`)}>Deschide carnetul</a>
          </p>
        </div>
      )}

      {!preview && (
        <form onSubmit={(e) => { e.preventDefault(); void doPreview(); }} style={{ maxWidth: 480 }}>
          <label htmlFor="token" className="muted">Linkul sau codul primit</label>
          <input id="token" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="ABCD-EFGH sau linkul complet" />
          <button className="primary" style={{ marginTop: 8 }} disabled={!token.trim()}>
            Verifică
          </button>
        </form>
      )}

      {preview && (
        <div className="card" style={{ maxWidth: 480 }}>
          <h3>{preview.title}</h3>
          {preview.description && <p className="muted">{preview.description}</p>}
          <p className="muted">{preview.material_count} materiale:</p>
          <ul>
            {preview.materials.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
          <button className="primary" onClick={doImport} disabled={busy}>
            {busy ? "Se importă…" : "Importă în carnetele mele"}
          </button>
        </div>
      )}
    </>
  );
}
