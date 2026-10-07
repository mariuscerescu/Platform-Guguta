"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, getCsrf, type Source } from "../../lib/api";
import { API_BASE } from "../../lib/paths";
import PrivateImagePreview from "./PrivateImagePreview";

export interface ChatAttachment extends Source {
  byte_size: number;
  chat_message_id: string | null;
}
interface Limits {
  max_file_mib: number; max_total_mib: number; max_per_message: number; max_per_session: number;
}
const ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp";
const DEFAULT_LIMITS: Limits = { max_file_mib: 25, max_total_mib: 25, max_per_message: 5, max_per_session: 20 };
const allowed = new Set(ACCEPT.split(",").map((ext) => ext.slice(1)));

export function AttachmentCards({ attachments, notebookId, sessionId, onRemove, disabled }: {
  attachments: ChatAttachment[]; notebookId: string; sessionId: string;
  onRemove?: (id: string) => void; disabled?: boolean;
}) {
  const [preview, setPreview] = useState<ChatAttachment | null>(null);
  function url(file: ChatAttachment) {
    return `${API_BASE}/api/v1/notebooks/${notebookId}/sessions/${sessionId}/attachments/${file.id}/download`;
  }
  return <>
    <div className="chat-attachment-list">
      {attachments.map((file) => <div className="chat-attachment-card" key={file.id}>
        {file.mime_type?.startsWith("image/") ?
          <button type="button" className="attachment-image" onClick={() => setPreview(file)} aria-label={`Afișează imaginea ${file.local_name}`}>
            <img src={url(file)} alt={file.local_name} />
          </button> : <span className="attachment-file-icon" aria-hidden="true">▤</span>}
        <div className="attachment-file-copy">
          <a href={url(file)} download title={file.local_name}>{file.local_name}</a>
          <small>{file.status === "processing" ? "Se procesează…" : file.status === "error" ? file.status_detail || "Procesare eșuată" : `${(file.byte_size / 1024 / 1024).toFixed(1)} MiB`}</small>
        </div>
        {onRemove && <button type="button" className="attachment-remove" onClick={() => onRemove(file.id)} disabled={disabled} aria-label={`Elimină atașamentul ${file.local_name}`}>×</button>}
      </div>)}
    </div>
    {preview && <PrivateImagePreview url={url(preview)} name={preview.local_name} onClose={() => setPreview(null)} />}
  </>;
}

export default function ChatAttachments({ notebookId, sessionId, disabled, refreshToken, submittedAttachmentIds, onChange, onBusy }: {
  notebookId: string; sessionId: string; disabled: boolean; refreshToken: number;
  submittedAttachmentIds: ReadonlySet<string>;
  onChange: (files: ChatAttachment[]) => void; onBusy: (busy: boolean) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [limits, setLimits] = useState(DEFAULT_LIMITS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endpoint = `/api/v1/notebooks/${notebookId}/sessions/${sessionId}/attachments`;
  const pending = files.filter((file) => !file.chat_message_id && !submittedAttachmentIds.has(file.id));
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const refresh = useCallback(async () => {
    try {
      const data = await api<{ attachments: ChatAttachment[]; limits: Limits }>("GET", endpoint);
      if (!alive.current) return;
      setFiles(data.attachments); setLimits(data.limits); onChange(data.attachments);
    } catch (err) { if (alive.current) setError((err as Error).message); }
  }, [endpoint, onChange]);
  useEffect(() => { void refresh(); }, [refresh, refreshToken]);
  const processing = files.some((file) => file.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  async function upload(selected: File[]) {
    if (!selected.length || busy || disabled) return;
    setError(null);
    if (selected.some((file) => !allowed.has(file.name.split(".").pop()?.toLowerCase() || ""))) {
      setError("Formate acceptate: PDF, DOCX, PPTX, TXT, Markdown, PNG, JPEG și WebP."); return;
    }
    if (pending.length + selected.length > limits.max_per_message) {
      setError(`Maximum ${limits.max_per_message} fișiere într-un mesaj.`); return;
    }
    if (files.length + selected.length > limits.max_per_session) {
      setError(`Maximum ${limits.max_per_session} atașamente într-o conversație.`); return;
    }
    if (selected.some((file) => file.size > limits.max_file_mib * 1024 * 1024)) {
      setError(`Maximum ${limits.max_file_mib} MiB pe fișier.`); return;
    }
    if (selected.reduce((sum, file) => sum + file.size, pending.reduce((sum, file) => sum + file.byte_size, 0)) > limits.max_total_mib * 1024 * 1024) {
      setError(`Maximum ${limits.max_total_mib} MiB în total pentru un mesaj.`); return;
    }
    setBusy(true); onBusy(true);
    try {
      const body = new FormData(); selected.forEach((file) => body.append("files", file));
      const csrf = getCsrf();
      const response = await fetch(`${API_BASE}${endpoint}`, { method: "POST", credentials: "same-origin", body,
        headers: csrf ? { "X-Guguta-CSRF": csrf } : {} });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "Încărcarea atașamentelor a eșuat.");
      await refresh();
    } catch (err) { if (alive.current) setError((err as Error).message); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  }
  async function remove(id: string) {
    if (busy || disabled) return;
    setBusy(true); onBusy(true); setError(null);
    try { await api("DELETE", `${endpoint}/${id}`); await refresh(); }
    catch (err) { if (alive.current) setError((err as Error).message); }
    finally { if (alive.current) { setBusy(false); onBusy(false); } }
  }
  return <div className="chat-attachments">
    <div className="attachment-toolbar">
      <button type="button" className="attachment-upload" onClick={() => input.current?.click()} disabled={disabled || busy || pending.length >= limits.max_per_message || files.length >= limits.max_per_session} aria-label="Atașează fișiere sau imagini">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9" strokeLinecap="round" /></svg>
        {busy ? "Se încarcă…" : "Atașează"}
      </button>
      <small>Max. {limits.max_per_message} fișiere · {limits.max_total_mib} MiB / mesaj</small>
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => {
        const selected = Array.from(e.target.files || []); e.target.value = ""; void upload(selected);
      }} />
    </div>
    {pending.length > 0 && <AttachmentCards attachments={pending} notebookId={notebookId} sessionId={sessionId} onRemove={(id) => void remove(id)} disabled={disabled || busy} />}
    {error && <p className="attachment-error" role="alert">{error}</p>}
  </div>;
}
