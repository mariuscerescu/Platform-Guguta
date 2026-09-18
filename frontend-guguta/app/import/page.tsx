"use client";

import { useEffect, useState } from "react";
import { api, me } from "../../lib/api";
import { withBase } from "../../lib/paths";
import { UploadIcon } from "../components/UiIcons";

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
  const [checking, setChecking] = useState(false);
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
    setChecking(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await api<PreviewData>("POST","/api/v1/imports/preview",{token:token.trim()}));
    } catch (err) {
      setError((err as Error).message || "Nu am putut verifica linkul.");
    } finally {
      setChecking(false);
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
      <div className="import-shell">
        <section className="import-card import-auth-card" aria-labelledby="import-title">
          <div className="import-icon" aria-hidden="true"><UploadIcon /></div>
          <p className="import-eyebrow">Carnet partajat</p>
          <h1 id="import-title">Autentifică-te pentru a continua</h1>
          <p className="import-lead">Codul primit este păstrat în acest browser și va fi disponibil imediat după autentificare.</p>
          <a href={withBase("/login")} className="primary import-login-link">Autentificare</a>
        </section>
      </div>
    );
  }

  return (
    <div className="import-shell">
      <section className="import-card" aria-labelledby="import-title">
        <header className="import-heading">
          <div className="import-icon" aria-hidden="true"><UploadIcon /></div>
          <div>
            <p className="import-eyebrow">Carnet partajat</p>
            <h1 id="import-title">Importă un carnet</h1>
            <p className="import-lead">Introdu codul sau linkul primit pentru a crea o copie în spațiul tău.</p>
          </div>
        </header>

        <div className="import-privacy-note">
          <strong>Datele tale rămân separate.</strong>
          <span>Se copiază doar materialele; conversațiile, notițele și memoria AI a autorului nu sunt incluse.</span>
        </div>

        {error && <p className="error-text import-message" role="alert">{error}</p>}
        {done && (
          <div className="import-success" role="status">
            <div>
              <strong>Import reușit</strong>
              <span>Carnetul este pregătit în biblioteca ta.</span>
            </div>
            <a href={withBase(`/notebook/${done}`)}>Deschide carnetul</a>
          </div>
        )}

        {!preview && !done && (
          <form className="import-form" onSubmit={(e) => { e.preventDefault(); void doPreview(); }}>
            <label htmlFor="token">Linkul sau codul primit</label>
            <div className="import-field-row">
              <input
                id="token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="ABCD-EFGH sau linkul complet"
                autoComplete="off"
                spellCheck={false}
              />
              <button className="primary" disabled={!token.trim() || checking}>
                {checking ? "Se verifică…" : "Verifică"}
              </button>
            </div>
            <p>Poți lipi linkul complet; codul va fi identificat automat.</p>
          </form>
        )}

        {preview && (
          <div className="import-preview-card">
            <div className="import-preview-heading">
              <div>
                <p className="import-eyebrow">Previzualizare</p>
                <h2>{preview.title}</h2>
              </div>
              <span>{preview.material_count} {preview.material_count === 1 ? "material" : "materiale"}</span>
            </div>
            {preview.description && <p className="import-preview-description">{preview.description}</p>}
            <ul>
              {preview.materials.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
            <div className="import-preview-actions">
              <button type="button" className="pill" onClick={() => setPreview(null)} disabled={busy}>Înapoi</button>
              <button type="button" className="primary" onClick={doImport} disabled={busy}>
                {busy ? "Se importă…" : "Importă în carnetele mele"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
