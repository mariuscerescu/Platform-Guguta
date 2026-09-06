"use client";

import { useEffect, useState } from "react";
import {
  api,
  CatalogTemplate,
  me,
  Notebook,
} from "../lib/api";

export default function HomePage() {
  const [notebooks, setNotebooks] = useState<Notebook[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogTemplate[] | null>(null);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [importToken, setImportToken] = useState("");
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    (async () => {
      // F06: the public catalog loads regardless of session.
      try {
        const res = await fetch("/guguta-api/api/v1/catalog/templates");
        if (res.ok) setCatalog((await res.json()) as CatalogTemplate[]);
        else setCatalog([]);
      } catch {
        setCatalog([]);
      }
      // F02: session via authenticated endpoint.
      const user = await me();
      setAuthed(user !== null);
      if (user === null) return;
      try {
        const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
        setNotebooks(list.items);
      } catch (err) {
        if ((err as { status?: number }).status === 401) setAuthed(false);
        else setError((err as Error).message);
      }
    })();
  }, []);

  async function createNotebook() {
    setCreating(true);
    setError(null);
    try {
      const nb = await api<Notebook>("POST", "/api/v1/notebooks", {
        title: "Carnet digital nou",
      });
      window.location.href = `/notebook/${nb.id}`;
    } catch (err) {
      setError((err as Error).message);
      setCreating(false);
    }
  }

  async function instantiate(templateId: string) {
    setImporting(true);
    setError(null);
    try {
      await api("POST", `/api/v1/catalog/templates/${templateId}/instances`, {
        idempotency_key: crypto.randomUUID(),
      });
      window.location.reload();
    } catch (err) {
      setError((err as Error).message);
      setImporting(false);
    }
  }

  async function importPackage() {
    if (!importToken.trim()) return;
    setImporting(true);
    setError(null);
    try {
      await api("POST", "/api/v1/imports", {
        token: importToken.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setImportToken("");
      window.location.reload();
    } catch (err) {
      setError((err as Error).message);
      setImporting(false);
    }
  }

  return (
    <>
      <h1>Carnete digitale Guguță</h1>
      {error && <p className="error-text">{error}</p>}

      {/* A01: catalog is always visible, even for visitors */}
      <section aria-labelledby="catalog">
        <h2 id="catalog">Catalogul oficial Guguță</h2>
        {catalog === null ? (
          <p className="muted">Se încarcă…</p>
        ) : catalog.length === 0 ? (
          <p className="muted">Catalogul oficial nu are încă carnete publicate.</p>
        ) : (
          <div className="grid-cards">
            {catalog.map((t) => (
              <div className="card" key={t.id}>
                <h3>{t.title}</h3>
                <p className="muted">{t.description}</p>
                <p>
                  <span className="badge">
                    Clasa {t.class_level ?? "—"} · {t.discipline ?? "—"}
                  </span>
                </p>
                <p className="muted">
                  Publicat de Guguță · {t.material_count} materiale · ediția {t.current_version}
                </p>
                {authed ? (
                  <button className="primary" onClick={() => instantiate(t.id)} disabled={importing}>
                    Începe un carnet nou
                  </button>
                ) : (
                  <p className="muted">
                    <a href="/login">Autentifică-te</a> ca să începi un carnet din acest șablon.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Personal notebooks — only for authenticated users */}
      {authed && (
        <section aria-labelledby="me">
          <h2 id="me">Carnetele mele</h2>
          {notebooks === null ? (
            <p className="muted">Se încarcă…</p>
          ) : notebooks.length === 0 ? (
            <p className="muted">Nu ai încă carnete. Creează unul sau alege din catalogul oficial.</p>
          ) : (
            <div className="grid-cards">
              {notebooks.map((nb) => (
                <div className="card" key={nb.id}>
                  <h3><a href={`/notebook/${nb.id}`}>{nb.title}</a></h3>
                  {nb.description && <p className="muted">{nb.description}</p>}
                  <span className="badge">
                    {nb.origin === "template" ? "Din catalogul oficial" : nb.origin === "import" ? "Importat" : "Personal"}
                  </span>
                </div>
              ))}
            </div>
          )}
          <p>
            <button className="primary" onClick={createNotebook} disabled={creating}>
              {creating ? "Se creează…" : "Creează un Carnet digital"}
            </button>
          </p>
        </section>
      )}

      {/* Import — visible to all, but requires auth to execute */}
      <section aria-labelledby="import">
        <h2 id="import">Importă prin link sau cod</h2>
        <p className="muted">Se transferă numai materialele. Conversațiile și notițele autorului nu sunt incluse.</p>
        {authed ? (
          <form onSubmit={(e) => { e.preventDefault(); void importPackage(); }}>
            <label htmlFor="token" className="muted">Linkul sau codul primit</label>
            <input id="token" value={importToken} onChange={(e) => setImportToken(e.target.value)}
              placeholder="Lipește aici linkul sau codul" />
            <button className="primary" style={{ marginTop: 8 }} disabled={importing}>
              {importing ? "Se importă…" : "Importă materialele"}
            </button>
          </form>
        ) : (
          <p className="muted">
            <a href="/login">Autentifică-te</a> ca să poți importa un pachet de materiale.
          </p>
        )}
      </section>

      {authed === false && (
        <p className="muted" style={{ marginTop: 32 }}>
          Nu ești autentificat. <a href="/login">Intră în Guguță</a> ca să îți vezi carnetele.
        </p>
      )}
    </>
  );
}
