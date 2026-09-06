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
  const [tab, setTab] = useState<"sources" | "chat" | "notes">("chat");
  const bottomRef = useRef<HTMLDivElement>(null);

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
      for (const m of msgs) {
        if (m.role !== "assistant" || citations[m.id]) continue;
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
  }, [nbId, sessionId, citations]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

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
      window.location.href = "/";
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
        <a href="/">← Înapoi la carnetele mele</a>
      </>
    );
  }

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>{nb?.title ?? "Carnet"}</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={renameNotebook}>Redenumește</button>
          <button onClick={() => archiveNotebook(nb?.status !== "archived")}>
            {nb?.status === "archived" ? "Dezarhivează" : "Arhivează"}
          </button>
          <button onClick={createShare} disabled={!sources?.some((s) => s.status === "ready")}>
            Partajează
          </button>
          <button onClick={deleteNotebook} style={{ borderColor: "var(--error)", color: "var(--error)" }}>
            Șterge
          </button>
        </div>
      </div>
      {error && <p className="error-text">{error}</p>}

      <div className="tabs" role="tablist">
        {(["sources", "chat", "notes"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "primary" : ""}
            onClick={() => setTab(t)}
          >
            {t === "sources" ? "Materiale" : t === "chat" ? "Conversație" : "Notițe"}
          </button>
        ))}
      </div>

      <div className="panes">
        <section className={`pane ${tab === "sources" ? "active" : ""}`} aria-label="Materiale">
          <h2>Materiale</h2>
          {sources === null ? (
            <p className="muted">Se încarcă…</p>
          ) : sources.length === 0 ? (
            <p className="muted">
              Nu ai materiale. Adaugă un text sau un fișier ca să poți întreba.
            </p>
          ) : (
            sources.map((s) => (
              <div className="card" key={s.id}>
                <h3>{s.local_name}</h3>
                <span className={`badge ${s.status}`}>
                  {s.status === "ready"
                    ? "Gata"
                    : s.status === "error"
                      ? "Eroare"
                      : "Se procesează"}
                </span>
                {s.status === "error" && s.status_detail && (
                  <p className="error-text">{s.status_detail}</p>
                )}
                <p>
                  <label>
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
                    />{" "}
                    Folosește la răspuns
                  </label>
                </p>
                {s.status === "error" && (
                  <button onClick={() => retrySource(s.id)}>Reîncearcă</button>
                )}{" "}
                <button onClick={() => removeSource(s.id)}>Elimină</button>
              </div>
            ))
          )}
          <form onSubmit={addSource}>
            <h3>Adaugă material (text)</h3>
            <label htmlFor="src-title" className="muted">
              Titlu
            </label>
            <input
              id="src-title"
              value={newSourceTitle}
              onChange={(e) => setNewSourceTitle(e.target.value)}
            />
            <label htmlFor="src-text" className="muted">
              Text
            </label>
            <textarea
              id="src-text"
              value={newSourceText}
              onChange={(e) => setNewSourceText(e.target.value)}
            />
            <button className="primary" style={{ marginTop: 8 }} disabled={!newSourceText.trim()}>
              Adaugă materialul
            </button>
          </form>
          <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            <h3>Adaugă fișier</h3>
            <p className="muted">PDF, DOCX, PPTX, TXT sau Markdown (max 25 MiB)</p>
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
        </section>

        <section className={`pane ${tab === "chat" ? "active" : ""}`} aria-label="Conversație">
          <h2>Conversație</h2>
          <p>
            <button onClick={newSession}>Conversație nouă</button>
          </p>
          {sessionId === null ? (
            <p className="muted">Creează o conversație ca să întrebi.</p>
          ) : (
            <>
              {messages.length === 0 && (
                <p className="muted">
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
              <label htmlFor="draft" className="muted">
                Întrebarea ta
              </label>
              <textarea
                id="draft"
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
                className="primary"
                style={{ marginTop: 8 }}
                onClick={send}
                disabled={sending || !draft.trim()}
              >
                {sending ? "Se generează…" : "Trimite"}
              </button>
            </>
          )}
        </section>

        <section className={`pane ${tab === "notes" ? "active" : ""}`} aria-label="Notițe">
          <h2>Notițe</h2>
          {notes === null ? (
            <p className="muted">Se încarcă…</p>
          ) : notes.length === 0 ? (
            <p className="muted">Nu ai notițe în acest carnet.</p>
          ) : (
            notes.map((n) => (
              <div className="card" key={n.id}>
                <h3>{n.title}</h3>
                <p>{n.content}</p>
                <button onClick={() => removeNote(n.id)}>Șterge notița</button>
              </div>
            ))
          )}
          <form onSubmit={addNote}>
            <h3>Notiță nouă</h3>
            <label htmlFor="note-title" className="muted">
              Titlu
            </label>
            <input
              id="note-title"
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
            />
            <label htmlFor="note-content" className="muted">
              Conținut
            </label>
            <textarea
              id="note-content"
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
            />
            <button className="primary" style={{ marginTop: 8 }} disabled={!noteContent.trim()}>
              Salvează notița
            </button>
          </form>
        </section>
      </div>
    </>
  );
}
