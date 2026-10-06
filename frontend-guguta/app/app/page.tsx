"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, me, CatalogTemplate, Notebook } from "../../lib/api";
import NotebookMenu from "../components/NotebookMenu";
import { withBase, API_BASE } from "../../lib/paths";

type Tab = "mine" | "school";
type View = "tiles" | "rows";
type Sort = "recent" | "title" | "class";
interface ImportPreview { snapshot_id:string; title:string; description?:string|null; material_count:number; materials:string[]; expires_at?:string|null; }

/* minimal SVG icons — no emoji (design decision) */
const IconDoc = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M7 3h7l4 4v14H7z" strokeLinejoin="round" />
    <path d="M14 3v4h4" strokeLinejoin="round" />
    <path d="M9.5 12h5M9.5 15.5h5" strokeLinecap="round" />
  </svg>
);
const IconBook = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" strokeLinejoin="round" />
    <path d="M17 20h2V7a3 3 0 0 0-3-3" strokeLinejoin="round" />
    <path d="M8 8h5M8 11.5h5" strokeLinecap="round" />
  </svg>
);
const IconDownload = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M12 4v10m0 0 4-4m-4 4-4-4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M5 19h14" strokeLinecap="round" />
  </svg>
);
const IconPlus = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 5v14M5 12h14" strokeLinecap="round" />
  </svg>
);
const IconSearch = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" strokeLinecap="round" />
  </svg>
);
const IconGrid = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <rect x="4" y="4" width="7" height="7" rx="1.5" />
    <rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" />
    <rect x="13" y="13" width="7" height="7" rx="1.5" />
  </svg>
);
const IconRows = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
  </svg>
);

function NotebookIcon({ origin }: { origin: string }) {
  if (origin === "template") return <IconBook />;
  if (origin === "import") return <IconDownload />;
  return <IconDoc />;
}

function classNumber(level: string | null | undefined, title: string): number {
  const roman: Record<string, number> = { I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6, VII: 7, VIII: 8, IX: 9, X: 10, XI: 11, XII: 12 };
  const candidates = [
    /^(?:clasa\s+)?(?:a\s+)?(\d{1,2}|[IVX]+)(?:\s*[-–]\s*a)?$/i.exec(level?.trim() ?? "")?.[1],
    /\bclasa\s+(?:a\s+)?(\d{1,2}|[IVX]+)\b/i.exec(title)?.[1],
  ];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const raw = candidate.toUpperCase();
    const number = roman[raw] ?? Number(raw);
    if (Number.isInteger(number) && number > 0) return number;
  }
  return Number.MAX_SAFE_INTEGER;
}

function formatDate(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("ro-MD", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function HomePage() {
  const [notebooks, setNotebooks] = useState<Notebook[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogTemplate[] | null>(null);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("mine");
  const [view, setView] = useState<View>("tiles");
  const [sort, setSort] = useState<Sort>("recent");
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const createMenuRef = useRef<HTMLDivElement>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importToken, setImportToken] = useState("");
  const [importing, setImporting] = useState(false);
  const [importPreview,setImportPreview]=useState<ImportPreview|null>(null);
  const [importedNotebookId,setImportedNotebookId]=useState<string|null>(null);

  // Reîncărcabilă: meniul fiecărui carnet o cheamă după redenumire, fixare sau
  // ștergere, ca lista să reflecte imediat schimbarea (inclusiv ordinea).
  const loadNotebooks = useCallback(async () => {
    try {
      const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
      setNotebooks(list.items);
    } catch (err) {
      if ((err as { status?: number }).status === 401) setAuthed(false);
      else setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/catalog/templates`);
        setCatalog(res.ok ? await res.json() : []);
      } catch {
        setCatalog([]);
      }
      const user = await me();
      setAuthed(user !== null);
      if (!user) return;
      await loadNotebooks();
    })();
  }, [loadNotebooks]);

  useEffect(() => {
    if (!createMenuOpen) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (!createMenuRef.current?.contains(event.target as Node)) setCreateMenuOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setCreateMenuOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [createMenuOpen]);

  function openImport() {
    setCreateMenuOpen(false);
    setImportOpen(true);
    setImportPreview(null);
    setImportedNotebookId(null);
    setImportToken("");
  }

  async function createNotebook() {
    setCreateMenuOpen(false);
    setCreating(true);
    setError(null);
    try {
      const nb = await api<Notebook>("POST", "/api/v1/notebooks", {
        title: "Carnet nou",
      });
      window.location.href = withBase(`/notebook/${nb.id}`);
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
      setTab("mine");
      const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
      setNotebooks(list.items);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setImporting(false);
    }
  }

  function openSchoolTemplate(template: CatalogTemplate) {
    if (!authed) {
      window.location.href = withBase("/login");
      return;
    }
    const owned = notebooks?.find((notebook) =>
      notebook.origin === "school" &&
      notebook.current_template_version_id === template.current_version_id
    );
    if (owned) {
      window.location.href = withBase(`/notebook/${owned.id}`);
      return;
    }
    void instantiate(template.id);
  }

  async function importPackage() {
    if (!importToken.trim()) return;
    setImporting(true);
    setError(null);
    try {
      if(!importPreview) {
        setImportPreview(await api<ImportPreview>("POST","/api/v1/imports/preview",{token:importToken.trim()}));
        return;
      }
      const result=await api<{notebook_id:string}>("POST", "/api/v1/imports", {
        token: importToken.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setImportedNotebookId(result.notebook_id);
      setTab("mine");
      const list = await api<{ items: Notebook[] }>("GET", "/api/v1/notebooks");
      setNotebooks(list.items);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setImporting(false);
    }
  }

  const filtered = useMemo(() => {
    if (tab === "school" || !notebooks) return null;
    const q = search.trim().toLowerCase();
    const sorted = notebooks.filter((notebook) =>
      notebook.origin !== "school" && !(
        notebook.origin === "template" &&
        notebooks.some((school) => school.origin === "school" &&
          school.current_template_version_id &&
          school.current_template_version_id === notebook.current_template_version_id)
      )
    ).sort((a, b) => {
      // Fixate sus: ordinea de fixare (cea mai recent fixată deasupra) are
      // prioritate față de sortarea aleasă; restul rămân sortate ca înainte.
      if (a.pinned && b.pinned) {
        const pa = a.pinned_at ?? "";
        const pb = b.pinned_at ?? "";
        if (pa !== pb) return pb.localeCompare(pa);
      } else if (a.pinned !== b.pinned) {
        return a.pinned ? -1 : 1;
      }
      if (sort === "class") {
        const byClass = classNumber(null, a.title) - classNumber(null, b.title);
        if (byClass) return byClass;
      }
      if (sort === "title" || sort === "class") return a.title.localeCompare(b.title, "ro");
      return (b.created_at ?? "").localeCompare(a.created_at ?? "");
    });
    return q ? sorted.filter((n) => n.title.toLowerCase().includes(q)) : sorted;
  }, [notebooks, tab, search, sort]);

  const catalogFiltered = useMemo(() => {
    if (tab !== "school" || !catalog) return null;
    const q = search.trim().toLowerCase();
    const sorted = [...catalog].sort((a, b) => {
      const byClass = classNumber(a.class_level, a.title) - classNumber(b.class_level, b.title);
      return byClass || a.title.localeCompare(b.title, "ro");
    });
    return q ? sorted.filter((t) => t.title.toLowerCase().includes(q)) : sorted;
  }, [catalog, tab, search]);

  const loadingCards = Array.from({ length: 4 }, (_, i) => i);

  return (
    <div className="library-shell">
      <section className="library-heading" aria-label="Acțiuni pentru carnete">
        <div className="library-primary-actions">
          <div className="library-create-menu" ref={createMenuRef}>
            <button
              type="button"
              className="create-btn library-create-trigger"
              aria-expanded={createMenuOpen}
              aria-controls="create-notebook-options"
              onClick={() => setCreateMenuOpen((open) => !open)}
              disabled={creating || !authed}
            >
              <IconPlus />
              <span>{creating ? "Se creează…" : "Carnet nou"}</span>
            </button>
            {createMenuOpen && (
              <div className="library-create-options" id="create-notebook-options">
                <button type="button" onClick={() => void createNotebook()}>
                  <IconPlus />
                  <span>Creează carnet</span>
                </button>
                <button type="button" onClick={openImport}>
                  <IconDownload />
                  <span>Importă carnet</span>
                </button>
              </div>
            )}
          </div>
        </div>
        {/* Filele și instrumentele folosesc același rând cu butonul de creare. */}
        <div className="toolbar">
        <div className="library-tabs" role="tablist" aria-label="Tipul carnetelor">
          <button
            role="tab"
            aria-selected={tab === "mine"}
            className={tab === "mine" ? "active" : ""}
            onClick={() => setTab("mine")}
            disabled={!authed}
          >
            Carnetele mele
          </button>
          <button
            role="tab"
            aria-selected={tab === "school"}
            className={tab === "school" ? "active" : ""}
            onClick={() => setTab("school")}
          >
            Carnete școlare
          </button>
        </div>
        <div className="toolbar-spacer" />
        <div className="search-wrap">
          {searchOpen && (
            <input
              className="search-pop"
              placeholder="Caută carnet după titlu"
              value={search}
              autoFocus
              onChange={(e) => setSearch(e.target.value)}
              onBlur={() => {
                if (!search.trim()) setSearchOpen(false);
              }}
            />
          )}
          <button
            className={`search-circle ${searchOpen ? "active" : ""}`}
            onClick={() => setSearchOpen((v) => !v)}
            title="Caută carnet după titlu"
            aria-label="Caută carnet după titlu"
          >
            <IconSearch />
          </button>
        </div>
        <div className="segmented" role="group" aria-label="Mod de afișare">
          <button
            className={view === "tiles" ? "active" : ""}
            onClick={() => setView("tiles")}
            title="Afișare în rânduri"
            aria-label="Afișare în rânduri"
          >
            <IconGrid />
          </button>
          <button
            className={view === "rows" ? "active" : ""}
            onClick={() => setView("rows")}
            title="Afișare în listă"
            aria-label="Afișare în listă"
          >
            <IconRows />
          </button>
        </div>
        <select
          className="select-pill"
          value={tab === "school" ? "class" : sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          aria-label="Sortare"
          disabled={tab === "school"}
        >
          {tab === "mine" && <option value="recent">Cele mai recente</option>}
          {tab === "mine" && <option value="title">După titlu</option>}
          <option value="class">După clasă</option>
        </select>
        </div>
      </section>

      {error && <p className="error-text" style={{ padding: "0 24px" }}>{error}</p>}

      {/* Carnetele mele */}
      {tab === "mine" && (
        <>
          <h2 className="section-title">Carnetele tale</h2>
          {authed === null ? (
            <div className="grid-cards" aria-label="Se încarcă lista de carnete">
              {loadingCards.map((i) => (
                <div className="nb-card skeleton-card" key={i}>
                  <span className="skeleton-icon" />
                  <span className="skeleton-line wide" />
                  <span className="skeleton-line" />
                </div>
              ))}
            </div>
          ) : !authed ? (
            <div className="empty-state">
              <p>Nu ești autentificat. Intră în Guguță ca să îți vezi carnetele.</p>
              <a href={withBase("/login")} className="create-btn" style={{ display: "inline-flex" }}>
                Autentificare
              </a>
            </div>
          ) : filtered === null ? (
            <div className="grid-cards" aria-label="Se încarcă lista de carnete">
              {loadingCards.map((i) => (
                <div className="nb-card skeleton-card" key={i}>
                  <span className="skeleton-icon" />
                  <span className="skeleton-line wide" />
                  <span className="skeleton-line" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="grid-cards library-empty-grid">
              <button className="create-card" onClick={createNotebook} disabled={creating}>
                <span className="plus-circle"><IconPlus /></span>
                <span>Creează un Carnet digital</span>
              </button>
              <div className="empty-state library-empty-copy">
                <span className="empty-state-icon"><IconBook /></span>
                <div>
                  <strong>Începe cu materialele tale</strong>
                  <p>Poți crea un carnet nou sau porni de la unul pregătit pentru școală.</p>
                </div>
                <button className="chip" onClick={() => setTab("school")}>
                  Vezi Carnetele școlare
                </button>
              </div>
            </div>
          ) : view === "rows" ? (
            /* list view: table ca în NotebookLM (Titlu | Materiale | Creat | Rol) */
            <table className="nb-table">
              <thead>
                <tr>
                  <th className="col-title">Titlu</th>
                  <th>Materiale</th>
                  <th>Creat</th>
                  <th>Rol</th>
                  <th className="col-menu" aria-label="Meniu" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((nb) => (
                  <tr
                    key={nb.id}
                    onClick={() => {
                      window.location.href = withBase(`/notebook/${nb.id}`);
                    }}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter")
                        window.location.href = withBase(`/notebook/${nb.id}`);
                    }}
                  >
                    <td className="col-title">
                      <span className="nb-icon-sm">
                        <NotebookIcon origin={nb.origin} />
                      </span>
                      <span className="table-title">{nb.title}</span>
                    </td>
                    <td>
                      {nb.source_count ?? 0}{" "}
                      {(nb.source_count ?? 0) === 1 ? "material" : "materiale"}
                    </td>
                    <td>{formatDate(nb.created_at)}</td>
                    <td>Deținător</td>
                    <td className="col-menu">
                      <NotebookMenu
                        notebook={nb}
                        onChanged={loadNotebooks}
                        onError={setError}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="grid-cards">
              <button className="create-card" onClick={createNotebook} disabled={creating}>
                <span className="plus-circle"><IconPlus /></span>
                <span>Creează un Carnet digital</span>
              </button>
              {filtered.map((nb) => (
                <div
                  className="nb-card"
                  key={nb.id}
                  role="link"
                  tabIndex={0}
                  onClick={() => {
                    window.location.href = withBase(`/notebook/${nb.id}`);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") window.location.href = withBase(`/notebook/${nb.id}`);
                  }}
                >
                  <div className="nb-top">
                    <span className="nb-icon"><NotebookIcon origin={nb.origin} /></span>
                    <NotebookMenu
                      notebook={nb}
                      onChanged={loadNotebooks}
                      onError={setError}
                    />
                  </div>
                  <div className="nb-body">
                    <h3 className="nb-title">{nb.title}</h3>
                    <p className="nb-meta">
                      {formatDate(nb.created_at)}
                      {nb.created_at ? " · " : ""}
                      {nb.source_count ?? 0}{" "}
                      {(nb.source_count ?? 0) === 1 ? "material" : "materiale"}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Carnete școlare */}
      {tab === "school" && (
        <>
          <h2 className="section-title">Carnete școlare</h2>
          {catalogFiltered === null ? (
            <div className="grid-cards" aria-label="Se încarcă catalogul școlar">
              {loadingCards.map((i) => (
                <div className="nb-card skeleton-card" key={i}>
                  <span className="skeleton-icon" />
                  <span className="skeleton-line wide" />
                  <span className="skeleton-line" />
                </div>
              ))}
            </div>
          ) : catalogFiltered.length === 0 ? (
            <div className="empty-state">
              <p>Catalogul școlar nu are încă carnete publicate.</p>
            </div>
          ) : view === "rows" ? (
            <table className="nb-table" aria-label="Carnete școlare">
              <thead>
                <tr>
                  <th className="col-title">Titlu</th>
                  <th>Materiale</th>
                  <th>Clasa</th>
                  <th>Disciplina</th>
                  <th className="col-menu" />
                </tr>
              </thead>
              <tbody>
                {catalogFiltered.map((template) => (
                  <tr
                    key={template.id}
                    tabIndex={importing ? -1 : 0}
                    aria-disabled={importing || undefined}
                    onClick={() => !importing && openSchoolTemplate(template)}
                    onKeyDown={(event) => {
                      if ((event.key === "Enter" || event.key === " ") && !importing) {
                        event.preventDefault();
                        openSchoolTemplate(template);
                      }
                    }}
                    title={template.description ?? template.title}
                  >
                    <td className="col-title">
                      <span className="nb-icon-sm"><IconBook /></span>
                      <span className="table-title">{template.title}</span>
                    </td>
                    <td>
                      {template.material_count}{" "}
                      {template.material_count === 1 ? "material" : "materiale"}
                    </td>
                    <td>{template.class_level ?? "—"}</td>
                    <td>{template.discipline ?? "—"}</td>
                    <td className="col-menu" />
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="grid-cards">
              {catalogFiltered.map((t) => (
                <div
                  className="nb-card"
                  key={t.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => !importing && openSchoolTemplate(t)}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === " ") && !importing) {
                      e.preventDefault();
                      openSchoolTemplate(t);
                    }
                  }}
                  title={t.description ?? t.title}
                >
                  <div className="nb-top">
                    <span className="nb-icon"><IconBook /></span>
                  </div>
                  <div className="nb-body">
                    <h3 className="nb-title">{t.title}</h3>
                    <p className="nb-meta">
                      Clasa {t.class_level ?? "—"} · {t.discipline ?? "—"} ·{" "}
                      {t.material_count} materiale
                    </p>
                    <p className="nb-meta" style={{ marginTop: 8 }}>
                      {!authed
                        ? "Autentifică-te pentru a începe."
                        : notebooks?.some((notebook) => notebook.origin === "school" && notebook.current_template_version_id === t.current_version_id)
                          ? "Deschide carnetul școlar."
                          : "Se creează o copie personală, editabilă independent."}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* Dialog: import prin link sau cod */}
      {importOpen && (
        <div
          className="modal-overlay"
          onClick={() => !importing && setImportOpen(false)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="audio-modal-heading"><div><h2 id="import-title">Importă carnet</h2><p className="muted">Folosește codul de 8 caractere sau linkul primit de la autor.</p></div><button className="icon-btn" type="button" onClick={()=>setImportOpen(false)}>×</button></div>
            <p className="muted">
              Se transferă numai materialele selectate — conversațiile, notițele și progresul autorului nu sunt incluse.
            </p>
            {importedNotebookId?<div className="share-created"><div className="share-success">✓ Carnet importat</div><p>Copia ta este independentă și poate fi modificată fără a afecta autorul.</p><a className="create-btn" href={withBase(`/notebook/${importedNotebookId}`)}>Deschide carnetul</a></div>:
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void importPackage();
              }}
            >
              <input
                style={{ width: "100%" }}
                placeholder="ABCD-EFGH sau linkul complet"
                value={importToken}
                autoFocus
                onChange={(e) => {setImportToken(e.target.value);setImportPreview(null);}}
              />
              {importPreview&&<div className="import-preview"><strong>{importPreview.title}</strong>{importPreview.description&&<p>{importPreview.description}</p>}<small>{importPreview.material_count} materiale incluse</small><ul>{importPreview.materials.map((m,i)=><li key={`${m}-${i}`}>{m}</li>)}</ul></div>}
              <div className="modal-actions">
                <button
                  type="button"
                  className="chip"
                  onClick={() => setImportOpen(false)}
                  disabled={importing}
                >
                  Anulează
                </button>
                <button
                  type="submit"
                  className="create-btn"
                  disabled={importing || !importToken.trim()}
                >
                  {importing ? (importPreview?"Se importă…":"Se verifică…") : importPreview?"Importă copia":"Verifică codul"}
                </button>
              </div>
            </form>}
          </div>
        </div>
      )}
    </div>
  );
}
