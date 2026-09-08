"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError, getCsrf, Note, Notebook, Source } from "../../../lib/api";

interface ChatMessage {
  id: string;
  seq: number;
  role: string;
  content: string;
  context_revision: number;
}

interface Citation {
  display_name: string;
  locator: Record<string, unknown>;
  source_removed: boolean;
}

interface ChatSession {
  id: string;
  title?: string | null;
  created_revision: number;
}

export default function NotebookPage() {
  const params = useParams<{ id: string }>();
  const nbId = params.id;

  const [nb, setNb] = useState<Notebook | null>(null);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<string, Citation[]>>({});
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newSourceTitle, setNewSourceTitle] = useState("");
  const [newSourceText, setNewSourceText] = useState("");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [srcCollapsed, setSrcCollapsed] = useState(false);
  const [studioCollapsed, setStudioCollapsed] = useState(false);
  const [addSrcOpen, setAddSrcOpen] = useState(false);
  const [noteFormOpen, setNoteFormOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  // mirror for loadMessages without adding `citations` to its deps —
  // otherwise setCitations recreates loadMessages → infinite re-render loop
  const citationsRef = useRef<Record<string, Citation[]>>({});
  useEffect(() => {
    citationsRef.current = citations;
  }, [citations]);

  const loadAll = useCallback(async () => {
    try {
      const nbData = await api<Notebook>("GET", `/api/v1/notebooks/${nbId}`);
      setNb(nbData);
      const srcs = await api<Source[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sources`,
      );
      setSources(srcs);
      const nts = await api<Note[]>(`GET`, `/api/v1/notebooks/${nbId}/notes`);
      setNotes(nts);
      const sess = await api<ChatSession[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sessions`,
      );
      setSessions(sess);
      if (sess.length > 0 && sessionId === null) setSessionId(sess[0].id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("Carnetul nu există sau nu îți aparține.");
      } else {
        setError((err as Error).message);
      }
    }
  }, [nbId, sessionId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const loadMessages = useCallback(async () => {
    if (sessionId === null) return;
    try {
      const msgs = await api<ChatMessage[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages`,
      );
      setMessages(msgs);
      const known = citationsRef.current;
      for (const m of msgs) {
        if (m.role !== "assistant" || known[m.id]) continue;
        try {
          const cites = await api<Citation[]>(
            "GET",
            `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages/${m.id}/citations`,
          );
          setCitations((prev) => ({ ...prev, [m.id]: cites }));
        } catch {
          setCitations((prev) => ({ ...prev, [m.id]: [] }));
        }
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [nbId, sessionId]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  // poll while any source is still processing (E2E bug: text sources never
  // refreshed their status — only file uploads polled)
  const hasProcessing = sources?.some((s) => s.status === "processing") ?? false;
  useEffect(() => {
    if (!hasProcessing) return;
    const t = setInterval(() => {
      void loadAll();
    }, 2000);
    return () => clearInterval(t);
  }, [hasProcessing, loadAll]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send() {
    if (!draft.trim() || sessionId === null) return;
    setSending(true);
    setError(null);
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages`, {
        content: draft.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setDraft("");
      await loadMessages();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function newSession() {
    try {
      const s = await api<ChatSession>(
        "POST",
        `/api/v1/notebooks/${nbId}/sessions`,
        {},
      );
      setSessions((prev) => [s, ...prev]);
      setSessionId(s.id);
      setMessages([]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function addSource(e: React.FormEvent) {
    e.preventDefault();
    if (!newSourceText.trim()) return;
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/sources/text`, {
        title: newSourceTitle.trim() || "Text introdus",
        text: newSourceText.trim(),
      });
      setNewSourceTitle("");
      setNewSourceText("");
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  // F04: file upload (multipart)
  const [uploadingFile, setUploadingFile] = useState(false);
  async function uploadFile(file: File) {
    setUploadingFile(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const csrf = getCsrf();
      const res = await fetch(`/guguta-api/api/v1/notebooks/${nbId}/sources/file`, {
        method: "POST",
        headers: { ...(csrf ? { "X-Guguta-CSRF": csrf } : {}), Origin: "http://localhost:3000" },
        body: formData,
      });
      if (!res.ok) {
        const d = (await res.json().catch(() => ({}))) as { code?: string; message?: string };
        throw new ApiError(res.status, d.code ?? "error", d.message ?? "Upload eșuat.");
      }
      const result = (await res.json()) as { source: Source };
      await loadAll();
      // F04: poll source status until ready/error
      const srcId = result.source.id;
      const poll = setInterval(async () => {
        const detail = await api<Source>(
          "GET", `/api/v1/notebooks/${nbId}/sources/${srcId}`,
        );
        if (detail.status === "ready" || detail.status === "error") {
          clearInterval(poll);
          await loadAll();
        }
      }, 2000);
      setTimeout(() => clearInterval(poll), 60_000); // max 60s polling
    } catch (err) {
      setError((err as Error).message);
      setUploadingFile(false);
    }
  }

  // F04: notebook management (rename/archive/delete)
  async function deleteNotebook() {
    if (!confirm(`Ștergi definitiv carnetul „${nb?.title}"?`)) return;
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}`);
      window.location.href = "/app";
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function renameNotebook() {
    const newTitle = prompt("Titlul nou:", nb?.title ?? "");
    if (!newTitle?.trim()) return;
    try {
      await api("PATCH", `/api/v1/notebooks/${nbId}`, { title: newTitle.trim() });
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function archiveNotebook(archive: boolean) {
    try {
      await api("PATCH", `/api/v1/notebooks/${nbId}`, { archive });
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function createShare() {
    if (!sources?.length) return;
    const ready = sources.filter((s) => s.status === "ready");
    if (!ready.length) { setError("Niciun material gata pentru partajare."); return; }
    try {
      const share = await api<{ share_id: string; token: string; code: string }>(
        "POST",
        `/api/v1/notebooks/${nbId}/shares`,
        { source_ids: ready.map((s) => s.id), title: nb?.title },
      );
      const link = `${window.location.origin}/import#token=${share.token}`;
      await navigator.clipboard.writeText(link);
      alert(`Link copiat:\n${link}\n\nCod: ${share.code}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function removeSource(id: string) {
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}/sources/${id}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function retrySource(id: string) {
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/sources/${id}/retry`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function addNote(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/notes`, {
        title: noteTitle.trim() || "Notiță",
        content: noteContent.trim(),
      });
      setNoteTitle("");
      setNoteContent("");
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function removeNote(id: string) {
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}/notes/${id}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (error && nb === null) {
    return (
      <>
        <p className="error-text">{error}</p>
        <a href="/app">← Înapoi la carnetele mele</a>
      </>
    );
  }


  return (
    <div className="nb-shell">
      <header className="nb-header">
        <a href="/app" className="nb-back" aria-label="Înapoi la carnetele mele">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m14 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
        <h1>{nb?.title ?? "Carnet"}</h1>
        <div className="nb-actions">
          <button
            className="pill"
            onClick={createShare}
            disabled={!sources?.some((s) => s.status === "ready")}
            title="Creează un pachet de partajare"
          >
            Partajează
          </button>
          <button className="pill" onClick={renameNotebook}>Redenumește</button>
          <button className="pill" onClick={() => archiveNotebook(nb?.status !== "archived")}>
            {nb?.status === "archived" ? "Dezarhivează" : "Arhivează"}
          </button>
          <button
            className="pill danger"
            onClick={() => {
              if (confirm(`Ștergi definitiv carnetul „${nb?.title}"?`)) void deleteNotebook();
            }}
          >
            Șterge
          </button>
        </div>
      </header>
      {error && <p className="error-text nb-error">{error}</p>}

      <div
        className={[
          "nb-grid",
          srcCollapsed ? "src-collapsed" : "",
          studioCollapsed ? "studio-collapsed" : "",
        ].join(" ")}
      >
        {/* -------- Surse (stânga, colapsabil) -------- */}
        <section
          className={`panel src ${srcCollapsed ? "collapsed" : ""}`}
          aria-label="Surse"
        >
          <div className="panel-head">
            <span className="panel-title">Surse</span>
            <button
              className="icon-btn"
              onClick={() => setSrcCollapsed((v) => !v)}
              aria-label={srcCollapsed ? "Desfă panoul Surse" : "Strânge panoul Surse"}
              title={srcCollapsed ? "Desfă" : "Strânge"}
            >
              {srcCollapsed ? "»" : "«"}
            </button>
          </div>
          <div className="panel-body">
            <button className="add-src-btn" onClick={() => setAddSrcOpen((v) => !v)}>
              + Adaugă sursă
            </button>
            {addSrcOpen && (
              <div className="add-src-box">
                <form onSubmit={addSource}>
                  <label htmlFor="src-title" className="muted">Titlu</label>
                  <input
                    id="src-title"
                    value={newSourceTitle}
                    onChange={(e) => setNewSourceTitle(e.target.value)}
                  />
                  <label htmlFor="src-text" className="muted">Text</label>
                  <textarea
                    id="src-text"
                    value={newSourceText}
                    onChange={(e) => setNewSourceText(e.target.value)}
                  />
                  <button
                    className="primary"
                    style={{ marginTop: 8, width: "100%" }}
                    disabled={!newSourceText.trim()}
                  >
                    Adaugă textul
                  </button>
                </form>
                <div className="file-box">
                  <p className="muted">PDF, DOCX, PPTX, TXT sau MD (max 25 MiB)</p>
                  <input
                    type="file"
                    accept=".pdf,.docx,.pptx,.txt,.md"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void uploadFile(file);
                      e.target.value = "";
                    }}
                    disabled={uploadingFile}
                  />
                  {uploadingFile && <p className="muted">Se încarcă și procesează…</p>}
                </div>
              </div>
            )}

            {sources === null ? (
              <p className="muted">Se încarcă…</p>
            ) : sources.length === 0 ? (
              <p className="muted">
                Nu ai materiale. Adaugă un text sau un fișier ca să poți întreba.
              </p>
            ) : (
              sources.map((s) => (
                <div className="src-card" key={s.id}>
                  <label className="src-sel" title="Folosește la răspuns">
                    <input
                      type="checkbox"
                      checked={s.selected_for_chat}
                      onChange={() =>
                        api(
                          "PATCH",
                          `/api/v1/notebooks/${nbId}/sources/${s.id}`,
                          { selected_for_chat: !s.selected_for_chat },
                        ).then(loadAll)
                      }
                    />
                  </label>
                  <span className="src-doc">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                      <path d="M7 3h7l4 4v14H7z" strokeLinejoin="round" />
                      <path d="M14 3v4h4" strokeLinejoin="round" />
                    </svg>
                  </span>
                  <span className="src-name" title={s.local_name}>{s.local_name}</span>
                  <span className={`badge ${s.status}`}>
                    {s.status === "ready" ? "Gata" : s.status === "error" ? "Eroare" : "…"}
                  </span>
                  {s.status === "error" && (
                    <button className="src-act" onClick={() => retrySource(s.id)} title="Reîncearcă">↻</button>
                  )}
                  <button
                    className="src-act"
                    onClick={() => removeSource(s.id)}
                    title="Elimină"
                  >
                    ×
                  </button>
                </div>
              ))
            )}
            {sources?.some((s) => s.status === "error" && s.status_detail) && (
              <p className="error-text">
                {sources.find((s) => s.status === "error")?.status_detail}
              </p>
            )}
          </div>
        </section>

        {/* -------- Conversație (centru) -------- */}
        <section className="panel chat" aria-label="Conversație">
          <div className="panel-head">
            <span className="panel-title">Conversație</span>
            <button className="pill small" onClick={newSession}>Conversație nouă</button>
          </div>
          <div className="panel-body chat-body">
            {sessionId === null ? (
              <div className="chat-empty">
                <p className="muted">
                  Creează o conversație ca să întrebi despre materialele selectate.
                </p>
              </div>
            ) : (
              <>
                <div className="msgs">
                  {messages.length === 0 && (
                    <p className="muted chat-hint">
                      Întreabă ceva despre materialele selectate ale carnetului.
                    </p>
                  )}
                  {messages.map((m) => (
                    <div key={m.id} className={`msg ${m.role}`}>
                      {m.content}
                      {(citations[m.id] ?? []).map((c, i) => (
                        <span className="citation" key={i}>
                          [{i + 1}] {c.source_removed ? "Sursă eliminată" : c.display_name}
                          {Object.keys(c.locator).length > 0 &&
                            ` · ${JSON.stringify(c.locator)}`}
                        </span>
                      ))}
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
                <div className="composer">
                  <textarea
                    id="draft"
                    placeholder="Pune o întrebare despre materiale…"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <button
                    className="send-btn"
                    onClick={() => void send()}
                    disabled={sending || !draft.trim()}
                    aria-label="Trimite"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M5 12h13M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </div>
              </>
            )}
          </div>
        </section>

        {/* -------- Studio (dreapta, colapsabil) -------- */}
        <section
          className={`panel studio ${studioCollapsed ? "collapsed" : ""}`}
          aria-label="Studio"
        >
          <div className="panel-head">
            <span className="panel-title">Studio</span>
            <button
              className="icon-btn"
              onClick={() => setStudioCollapsed((v) => !v)}
              aria-label={studioCollapsed ? "Desfă panoul Studio" : "Strânge panoul Studio"}
              title={studioCollapsed ? "Desfă" : "Strânge"}
            >
              {studioCollapsed ? "«" : "»"}
            </button>
          </div>
          <div className="panel-body studio-body">
            {notes === null ? (
              <p className="muted">Se încarcă…</p>
            ) : notes.length === 0 ? (
              <div className="studio-empty">
                <svg viewBox="0 0 24 24" fill="currentColor" width="34" height="34">
                  <path d="M12 2l1.8 5.6L19 9l-5.2 1.4L12 16l-1.8-5.6L5 9l5.2-1.4L12 2zm7 12l.9 2.6L22.5 18l-2.6.9L19 21.5l-.9-2.6-2.6-.9 2.6-.9L19 14z" />
                </svg>
                <p className="studio-strong">Rezultatul Studio va fi salvat aici.</p>
                <p className="muted">
                  După ce adaugi materiale, aici vor apărea rezumatele, ghidurile
                  de studiu, hărțile mentale și multe altele!
                </p>
              </div>
            ) : (
              notes.map((n) => (
                <div className="card" key={n.id}>
                  <h3>{n.title}</h3>
                  <p>{n.content}</p>
                  <button className="pill small" onClick={() => removeNote(n.id)}>
                    Șterge notița
                  </button>
                </div>
              ))
            )}
            <div style={{ marginTop: "auto", paddingTop: 16 }}>
              {noteFormOpen && (
                <form onSubmit={addNote} className="note-form">
                  <label htmlFor="note-title" className="muted">Titlu</label>
                  <input
                    id="note-title"
                    value={noteTitle}
                    onChange={(e) => setNoteTitle(e.target.value)}
                  />
                  <label htmlFor="note-content" className="muted">Conținut</label>
                  <textarea
                    id="note-content"
                    value={noteContent}
                    onChange={(e) => setNoteContent(e.target.value)}
                  />
                  <button
                    className="primary"
                    style={{ marginTop: 8, width: "100%" }}
                    disabled={!noteContent.trim()}
                  >
                    Salvează notița
                  </button>
                </form>
              )}
              <button
                className="create-btn"
                style={{ width: "100%", justifyContent: "center" }}
                onClick={() => setNoteFormOpen((v) => !v)}
              >
                + Adaugă notiță
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
