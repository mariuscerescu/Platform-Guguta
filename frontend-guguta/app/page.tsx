"use client";

import { useEffect, useMemo, useState } from "react";
import { api, me, CatalogTemplate, Notebook } from "../lib/api";

type Tab = "mine" | "school";
type View = "tiles" | "rows";
type Sort = "recent" | "title";

export default function HomePage() {
  const [notebooks, setNotebooks] = useState<Notebook[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogTemplate[] | null>(null);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("mine");
  const [view, setView] = useState<View>("tiles");
  const [sort, setSort] = useState<Sort>("recent");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [importToken, setImportToken] = useState("");
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/guguta-api/api/v1/catalog/templates");
        setCatalog(res.ok ? await res.json() : []);
      } catch { setCatalog([]); }
      const user = await me();
      setAuthed(user !== null);
      if (!user) return;
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
        title: "Carnet nou",
      });
      window.location.href = `/notebook/${nb.id}`;
    } catch (err) { setError((err as Error).message); setCreating(false); }
  }

  async function instantiate(templateId: string) {
    setImporting(true);
    setError(null);
    try {
      await api("POST", `/api/v1/catalog/templates/${templateId}/instances`, {
        idempotency_key: crypto.randomUUID(),
      });
      setTab("mine");
      const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
      setNotebooks(list.items);
    } catch (err) { setError((err as Error).message); setImporting(false); }
  }

  async function importPackage() {
    if (!importToken.trim()) return;
    setImporting(true);
    setError(null);
    try {
      await api("POST", "/api/v1/imports", {
        token: importToken.trim(), idempotency_key: crypto.randomUUID(),
      });
      setImportToken("");
      setTab("mine");
      const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
      setNotebooks(list.items);
    } catch (err) { setError((err as Error).message); setImporting(false); }
  }

  const filtered = useMemo(() => {
    if (tab === "school") return null;
    if (!notebooks) return null;
    const query = search.trim().toLowerCase();
    const sorted = [...notebooks].sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title, "ro");
      return (b.created_at ?? "").localeCompare(a.created_at ?? "");
    });
    return query ? sorted.filter((n) => n.title.toLowerCase().includes(query)) : sorted;
  }, [notebooks, tab, search, sort]);

  const catalogFiltered = useMemo(() => {
    if (tab !== "school" || !catalog) return null;
    const query = search.trim().toLowerCase();
    const sorted = [...catalog].sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title, "ro");
      return 0;
    });
    return query ? sorted.filter((t) => t.title.toLowerCase().includes(query)) : sorted;
  }, [catalog, tab, search, sort]);

  return (
    <>
      {/* Toolbar: filter chips + search + view controls + create */}
      <div className="toolbar">
        <button className={`chip ${tab === "mine" ? "active" : ""}`}
          onClick={() => setTab("mine")} disabled={!authed}>
          Carnetele mele
        </button>
        <button className={`chip ${tab === "school" ? "active" : ""}`}
          onClick={() => setTab("school")}>
          Carnete școlare
        </button>
        <div className="toolbar-spacer" />
        <input className="search-input" placeholder="Caută carnet după titlu"
          value={search} onChange={(e) => setSearch(e.target.value)} />
        <button className={`icon-btn ${view === "tiles" ? "active" : ""}`}
          onClick={() => setView("tiles")} title="Afișare în rânduri">▦</button>
        <button className={`icon-btn ${view === "rows" ? "active" : ""}`}
          onClick={() => setView("rows")} title="Afișare în listă">☰</button>
        <select className="select" value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="recent">Cele mai recente</option>
          <option value="title">După titlu</option>
        </select>
        <button className="create-btn" onClick={createNotebook}
          disabled={creating || !authed}>
          + Carnet nou
        </button>
      </div>

      {error && <p className="error-text" style={{ padding: "0 24px" }}>{error}</p>}

      {/* My notebooks tab */}
      {tab === "mine" && (
        <>
          <h2 className="section-title">Carnetele mele</h2>
          {authed === null ? (
            <p className="muted" style={{ padding: "0 24px" }}>Se încarcă…</p>
          ) : !authed ? (
            <div className="empty-state">
              <p>Nu ești autentificat. Intră în Guguță ca să îți vezi carnetele.</p>
              <a href="/login" className="create-btn" style={{ display: "inline-flex" }}>
                Autentificare
              </a>
            </div>
          ) : filtered === null ? (
            <p className="muted" style={{ padding: "0 24px" }}>Se încarcă…</p>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <p>Nu ai încă carnete. Creează unul sau alege din Carnetele școlare.</p>
              <button className="chip" onClick={() => setTab("school")}>
                Vezi Carnetele școlare
              </button>
            </div>
          ) : (
            <div className="grid-cards" style={view === "rows" ? { gridTemplateColumns: "1fr" } : undefined}>
              <button className="create-card" onClick={createNotebook} disabled={creating}>
                <span className="plus-circle">+</span>
                <span>Creează carnet nou</span>
              </button>
              {filtered.map((nb) => (
                <div className="nb-card" key={nb.id}
                  onClick={() => { window.location.href = `/notebook/${nb.id}`; }}>
                  <span className="nb-icon">
                    {nb.origin === "template" ? "📗" : nb.origin === "import" ? "📥" : "📝"}
                  </span>
                  <h3 className="nb-title">{nb.title}</h3>
                  <p className="nb-meta">
                    {nb.origin === "template" ? "Din catalog" : nb.origin === "import" ? "Importat" : "Personal"}
                  </p>
                  <div className="nb-menu"><button title="Meniu">⋮</button></div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* School catalog tab */}
      {tab === "school" && (
        <>
          <h2 className="section-title">Carnete școlare</h2>
          {authed === null ? (
            <p className="muted" style={{ padding: "0 24px" }}>Se încarcă…</p>
          ) : !authed ? (
            <div className="empty-state">
              <p>Autentifică-te ca să poți începe un carnet din catalogul școlar.</p>
              <a href="/login" className="create-btn" style={{ display: "inline-flex" }}>
                Autentificare
              </a>
            </div>
          ) : catalogFiltered === null ? (
            <p className="muted" style={{ padding: "0 24px" }}>Se încarcă…</p>
          ) : catalogFiltered.length === 0 ? (
            <div className="empty-state">
              <p>Catalogul școlar nu are încă carnete publicate.</p>
            </div>
          ) : (
            <div className="grid-cards" style={view === "rows" ? { gridTemplateColumns: "1fr" } : undefined}>
              {catalogFiltered.map((t) => (
                <div className="nb-card" key={t.id}
                  onClick={() => instantiate(t.id)}
                  title={t.description ?? t.title}>
                  <span className="nb-icon">📚</span>
                  <h3 className="nb-title">{t.title}</h3>
                  <p className="nb-meta">
                    Clasa {t.class_level ?? "—"} · {t.discipline ?? "—"} · {t.material_count} materiale
                  </p>
                  <div className="nb-menu"><button title="Meniu">⋮</button></div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Import — secondary section at bottom */}
      <section style={{ padding: "var(--space-8) var(--space-6) 0" }}>
        <h2 className="section-title" style={{ padding: 0 }}>Importă prin link sau cod</h2>
        {authed ? (
          <form onSubmit={(e) => { e.preventDefault(); void importPackage(); }}
            style={{ display: "flex", gap: 12, padding: "0 24px", alignItems: "center" }}>
            <input style={{ flex: 1, maxWidth: 480 }} placeholder="Lipește linkul sau codul"
              value={importToken} onChange={(e) => setImportToken(e.target.value)} />
            <button className="create-btn" disabled={importing || !importToken.trim()}>
              {importing ? "Se importă…" : "Importă"}
            </button>
          </form>
        ) : (
          <p className="muted" style={{ padding: "0 24px" }}>
            <a href="/login">Autentifică-te</a> ca să poți importa materiale.
          </p>
        )}
      </section>
    </>
  );
}
