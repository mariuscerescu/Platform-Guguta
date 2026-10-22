"use client";

import { useEffect, useId, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "../../lib/api";
import { API_BASE } from "../../lib/paths";
import "./material-preview.css";

type Preview = { kind: "pdf" | "image" | "audio" | "video"; url: string }
  | { kind: "text"; text: string }
  | { kind: "unsupported" };

export default function MaterialPreview({ notebookId, source, onClose }: {
  notebookId: string; source: Source; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [zoomed, setZoomed] = useState(false);
  const base = `${API_BASE}/api/v1/notebooks/${notebookId}/sources/${source.id}`;
  const office = /officedocument\.(wordprocessingml|presentationml)/.test(source.mime_type ?? "");

  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    element?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 60_000);
    setPreview(null);
    setError("");
    setZoomed(false);
    void (async () => {
      try {
        const response = await fetch(`${base}/preview`, {
          credentials: "include", cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(response.status === 401
            ? "Sesiunea a expirat. Autentifică-te din nou pentru a vedea materialul."
            : response.status === 403 || response.status === 404
              ? "Materialul nu mai este disponibil sau nu ai acces la el."
              : "Nu am putut deschide materialul. Încearcă din nou sau descarcă fișierul.");
        }
        const mime = (response.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
        if (["text/plain", "text/markdown"].includes(mime)) {
          const text = await response.text();
          if (active) setPreview({ kind: "text", text });
          return;
        }
        const kind = mime === "application/pdf" ? "pdf"
          : ["image/png", "image/jpeg", "image/webp", "image/gif"].includes(mime) ? "image"
          : mime.startsWith("audio/") ? "audio"
          : mime.startsWith("video/") ? "video" : null;
        if (!kind) {
          if (active) setPreview({ kind: "unsupported" });
          return;
        }
        const blob = await response.blob();
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setPreview({ kind, url: objectUrl });
      } catch (cause) {
        if (active) setError(controller.signal.aborted
          ? "Încărcarea durează prea mult. Încearcă din nou."
          : cause instanceof Error ? cause.message : "Nu am putut deschide materialul.");
      } finally {
        window.clearTimeout(timeout);
      }
    })();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [base, attempt]);

  return (
    <dialog ref={dialog} className="material-preview" aria-labelledby={titleId}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
      }}>
      <header className="material-preview__header">
        <h2 id={titleId}>{source.local_name}</h2>
        <div className="material-preview__actions">
          {preview?.kind === "image" && <button type="button" onClick={() => setZoomed(value => !value)} aria-pressed={zoomed}>
            {zoomed ? "Potrivește" : "Mărește"}
          </button>}
          <a href={`${base}/download`} download={source.original_name || source.local_name}>Descarcă</a>
          <a href={`${base}/preview`} target="_blank" rel="noopener noreferrer">Filă nouă ↗</a>
          <button type="button" className="material-preview__close" aria-label="Închide previzualizarea" onClick={onClose} autoFocus>×</button>
        </div>
      </header>
      <div className={`material-preview__body material-preview__body--${preview?.kind ?? "loading"}`}>
        {error ? <div className="material-preview__notice" role="alert">
          <p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>Reîncearcă</button>
        </div> : !preview ? <div className="material-preview__notice" role="status">
          <span className="spinner" aria-hidden="true" />Se încarcă materialul…
        </div> : preview.kind === "pdf" ? <iframe src={`${preview.url}#view=FitH`} title={`PDF: ${source.local_name}`} />
          : preview.kind === "image" ? <div className={`material-preview__image ${zoomed ? "is-zoomed" : ""}`}>
            <img src={preview.url} alt={source.local_name} onError={() => setError("Imaginea nu poate fi afișată. Poți descărca fișierul original.")} />
          </div>
            : preview.kind === "audio" ? <audio controls preload="metadata" src={preview.url} aria-label={source.local_name}
              onError={() => setError("Browserul nu poate reda acest format audio. Descarcă fișierul pentru a-l asculta.")} />
              : preview.kind === "video" ? <video controls playsInline preload="metadata" src={preview.url} aria-label={source.local_name}
                onError={() => setError("Browserul nu poate reda acest format video. Descarcă fișierul pentru a-l viziona.")} />
                : preview.kind === "text" ? <article className="material-preview__text">
                  {office && <p className="material-preview__hint">Textul documentului. Pentru aspectul original, descarcă fișierul.</p>}
                  {office ? <pre>{preview.text}</pre> : <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{
                    a: ({ href, children }) => /^https?:\/\//i.test(href ?? "")
                      ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>,
                    // Never send a private document to an external viewer or load its remote images.
                    img: ({ alt }) => <span>{alt ?? "Imagine"}</span>,
                  }}>{preview.text || "Materialul nu conține text."}</ReactMarkdown>}
                </article>
                  : <div className="material-preview__notice"><p>Acest format nu poate fi afișat în browser.</p><a href={`${base}/download`} download>Descarcă fișierul original</a></div>}
      </div>
      {preview?.kind === "pdf" && !error && <p className="material-preview__hint material-preview__footer">Dacă PDF-ul nu se afișează, folosește „Filă nouă” sau „Descarcă”.</p>}
    </dialog>
  );
}
