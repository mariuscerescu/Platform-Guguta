"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import type { GugutaContext } from "./guguta-companion";
import { useCompanionDictation } from "./useCompanionDictation";
import { useChatWaitingMessage } from "./useChatWaitingMessage";

type Message = { id: string; role: string; content: string };
type Target = { notebookId: string; sessionId: string };
type Auth = { csrf: string; actor_id: string };
type Notebook = { id: string; title: string; description?: string; origin?: string; status?: string };
export type CompanionChatState = "idle" | "running" | "waiting" | "failed";
export interface CompanionChatProps {
  context: GugutaContext;
  apiBase: string;
  loginHref: string;
  onClose: () => void;
  sessionId?: string | null;
  onStateChange?: (state: CompanionChatState) => void;
}
const GENERAL_TITLE = "Conversația cu Guguță";
const GENERAL_DESCRIPTION = "Conversația personală cu asistentul Guguță.";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

class RequestError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
function errorText(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.trim()) return value;
  if (Array.isArray(value)) return value.map(item => typeof item?.msg === "string" ? item.msg : "").filter(Boolean).join(" ") || fallback;
  return fallback;
}

/** The same authenticated notebook chat API is used in both applications. */
export default function CompanionChat({ context, apiBase, loginHref, onClose, sessionId, onStateChange }: CompanionChatProps) {
  const [authState, setAuthState] = useState<"loading" | "ready" | "guest" | "error">("loading");
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState("");
  const [sending, setSending] = useState(false);
  const waitingMessage = useChatWaitingMessage(sending && !streaming);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const actor = useRef<string | null>(null);
  const target = useRef<Target | null>(null);
  const operation = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const sendingRef = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const messageBox = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const contextJson = JSON.stringify(context);
  const scope = `${contextJson}:${sessionId ?? ""}`;
  const onTranscript = useCallback((text: string) => {
    setDraft(previous => [previous.trim(), text.trim()].filter(Boolean).join(" ").slice(0, 18000));
    textarea.current?.focus({ preventScroll: true });
  }, []);
  const dictation = useCompanionDictation({ apiBase, scope, onTranscript });

  const request = useCallback(async <T,>(path: string, signal: AbortSignal, method = "GET", body?: unknown, csrf?: string): Promise<T> => {
    const response = await fetch(`${apiBase}/api/v1${path}`, {
      method, credentials: "same-origin", signal, cache: "no-store",
      headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...(csrf ? { "X-Guguta-CSRF": csrf } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new RequestError(response.status, errorText(data.message ?? data.detail, response.status === 401 ? "Autentifică-te pentru a continua conversația." : "Cererea nu a reușit. Încearcă din nou."));
    return data as T;
  }, [apiBase]);

  const readHistory = useCallback((value: Target, signal: AbortSignal) => request<Message[]>(`/notebooks/${value.notebookId}/sessions/${value.sessionId}/messages`, signal), [request]);

  useEffect(() => {
    const token = ++generation.current;
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    target.current = null;
    actor.current = null;
    sendingRef.current = false;
    setAuthState("loading"); setMessages([]); setStreaming(""); setSending(false); setError(""); setDraft("");
    const active = () => token === generation.current && !controller.signal.aborted;
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    void (async () => {
      try {
        const auth = await request<Auth>("/auth/csrf", controller.signal);
        if (!active()) return;
        actor.current = auth.actor_id;
        let notebookId = context.notebookId;
        if (!notebookId) {
          try { notebookId = localStorage.getItem(`guguta.companion.chat.${auth.actor_id}`) || undefined; } catch { /* Optional preference. */ }
        }
        if (notebookId && UUID.test(notebookId)) {
          try {
            await request<Notebook>(`/notebooks/${notebookId}`, controller.signal);
            const sessions = await request<{ id: string }[]>(`/notebooks/${notebookId}/sessions`, controller.signal);
            const chosen = sessionId ? sessions.find(item => item.id === sessionId) : sessions[0];
            if (chosen) {
              const value = { notebookId, sessionId: chosen.id };
              const history = await readHistory(value, controller.signal);
              if (!active()) return;
              target.current = value;
              setMessages(history.filter(message => message.role === "user" || message.role === "assistant"));
            }
          } catch (cause) {
            if (!(cause instanceof RequestError && cause.status === 404 && !context.notebookId)) throw cause;
            try { localStorage.removeItem(`guguta.companion.chat.${auth.actor_id}`); } catch { /* Optional preference. */ }
          }
        }
        if (active()) setAuthState("ready");
      } catch (cause) {
        if (token !== generation.current) return;
        if (cause instanceof RequestError && cause.status === 401) setAuthState("guest");
        else { setAuthState("error"); setError(controller.signal.aborted ? "Conexiunea durează prea mult. Încearcă din nou." : (cause as Error).message); }
      } finally { window.clearTimeout(timeout); }
    })();
    return () => { ++generation.current; controller.abort(); operation.current?.abort(); };
  // A context switch cancels and isolates the previous conversation, including its pending reply.
  }, [scope, retry, request, readHistory]);

  useEffect(() => {
    if (authState === "ready" && !sending) textarea.current?.focus({ preventScroll: true });
  }, [authState, sending]);
  useEffect(() => {
    onStateChange?.(sending || dictation.transcribing ? "running" : dictation.recording ? "waiting" : error || dictation.error ? "failed" : "idle");
  }, [sending, dictation.transcribing, dictation.recording, error, dictation.error, onStateChange]);
  useEffect(() => { if (messageBox.current) messageBox.current.scrollTop = messageBox.current.scrollHeight; }, [messages, streaming, sending]);

  async function ensureTarget(auth: Auth, signal: AbortSignal): Promise<{ value: Target; history?: Message[] }> {
    if (target.current) return { value: target.current };
    let notebookId = context.notebookId;
    if (!notebookId) {
      const key = `guguta.companion.chat.${auth.actor_id}`;
      try { notebookId = localStorage.getItem(key) || undefined; } catch { /* Optional preference. */ }
      if (notebookId && UUID.test(notebookId)) {
        try { await request<Notebook>(`/notebooks/${notebookId}`, signal); }
        catch (cause) { if (cause instanceof RequestError && cause.status === 404) notebookId = undefined; else throw cause; }
      } else notebookId = undefined;
      if (!notebookId) {
        let page = 1;
        while (!notebookId) {
          const listed = await request<{ items: Notebook[]; has_next: boolean }>(`/notebooks?page=${page}&page_size=100&status=active`, signal);
          notebookId = listed.items.find(item => item.title === GENERAL_TITLE && item.description === GENERAL_DESCRIPTION && item.origin !== "school")?.id;
          if (!listed.has_next) break;
          page += 1;
        }
      }
      if (!notebookId) notebookId = (await request<Notebook>("/notebooks", signal, "POST", { title: GENERAL_TITLE, description: GENERAL_DESCRIPTION }, auth.csrf)).id;
      try { localStorage.setItem(key, notebookId); } catch { /* Optional preference. */ }
    }
    if (!UUID.test(notebookId)) throw new Error("Carnetul conversației nu este disponibil.");
    const sessions = await request<{ id: string }[]>(`/notebooks/${notebookId}/sessions`, signal);
    let chosen = sessionId ? sessions.find(item => item.id === sessionId) : sessions[0];
    if (sessionId && !chosen) throw new Error("Conversația selectată nu mai este disponibilă. Redeschide carnetul.");
    if (!chosen) chosen = await request<{ id: string }>(`/notebooks/${notebookId}/sessions`, signal, "POST", { title: "Conversație cu Guguță" }, auth.csrf);
    const value = { notebookId, sessionId: chosen.id };
    const history = await readHistory(value, signal);
    return { value, history: history.filter(message => message.role === "user" || message.role === "assistant") };
  }

  async function send() {
    const text = draft.trim();
    if (!text || sendingRef.current || authState !== "ready" || dictation.recording || dictation.transcribing || dictation.requesting) return;
    const token = generation.current;
    const snapshot = JSON.parse(contextJson) as GugutaContext;
    const controller = new AbortController();
    operation.current = controller;
    const active = () => token === generation.current && !controller.signal.aborted;
    const optimisticId = `local-${crypto.randomUUID()}`;
    const optimistic = { id: optimisticId, role: "user", content: text };
    sendingRef.current = true;
    setSending(true); setError(""); setStreaming("");
    setMessages(previous => [...previous, optimistic]);
    setDraft("");
    const timeout = window.setTimeout(() => controller.abort(), 150000);
    let answer = "";
    let requestStarted = false;
    try {
      const auth = await request<Auth>("/auth/csrf", controller.signal);
      if (auth.actor_id !== actor.current) throw new Error("Contul s-a schimbat. Redeschide conversația.");
      const { value, history } = await ensureTarget(auth, controller.signal);
      if (!active()) return;
      target.current = value;
      if (history) setMessages([...history, optimistic]);
      const education = [snapshot.subjectLabel, snapshot.grade ? `clasa ${snapshot.grade}` : "", snapshot.lessonTitle].filter(Boolean).join(" · ").replace(/\s+/g, " ").trim();
      const content = education ? `Context educațional: ${education}.\n\n${text}` : text;
      requestStarted = true;
      const response = await fetch(`${apiBase}/api/v1/notebooks/${value.notebookId}/sessions/${value.sessionId}/messages/stream`, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-Guguta-CSRF": auth.csrf },
        body: JSON.stringify({ content, attachment_ids: [] }),
      });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        throw new RequestError(response.status, errorText(data.message ?? data.detail, "Răspunsul nu a putut fi generat."));
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let complete = false;
      const consume = (frame: string) => {
        const payload = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!payload) return;
        const event = JSON.parse(payload) as { event: string; text?: string; message?: string; user_message_id?: string };
        if (event.event === "error") throw new Error(event.message || "Asistentul nu a putut răspunde. Încearcă din nou.");
        if (!active()) return;
        if (event.event === "token" && event.text) { answer += event.text; setStreaming(answer); }
        if (event.event === "done") complete = true;
        if (event.event === "user_saved" && event.user_message_id) {
          const id = event.user_message_id;
          setMessages(previous => previous.map(message => message.id === optimisticId ? { ...message, id } : message));
        }
      };
      try {
        while (!complete) {
          const part = await reader.read();
          buffer += decoder.decode(part.value, { stream: !part.done });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) { consume(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); }
          if (part.done) { if (buffer.trim()) consume(buffer); break; }
        }
      } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
      if (!complete) throw new Error("Conexiunea s-a întrerupt înainte de încheierea răspunsului. Poți încerca din nou.");
      if (!active()) return;
      const completedAnswer = answer.trim();
      setMessages(previous => [...previous, { id: `answer-${crypto.randomUUID()}`, role: "assistant", content: completedAnswer }]);
      setStreaming(""); answer = "";
    } catch (cause) {
      if (token !== generation.current) return;
      if (cause instanceof RequestError && cause.status === 401) setAuthState("guest");
      if (answer.trim()) setMessages(previous => [...previous, { id: `partial-${crypto.randomUUID()}`, role: "assistant", content: `${answer.trim()}\n\n(Răspuns întrerupt.)` }]);
      setError(controller.signal.aborted ? "Generarea a fost oprită. Poți trimite un mesaj nou." : (cause as Error).message);
      if (!requestStarted) {
        setMessages(previous => previous.filter(message => message.id !== optimisticId));
        setDraft(text);
      }
    } finally {
      window.clearTimeout(timeout);
      if (token === generation.current) { sendingRef.current = false; setSending(false); setStreaming(""); }
    }
  }

  const recentMessages = messages.slice(sending ? -3 : -4);
  const dictationStatus = dictation.requesting ? "Permite accesul la microfon…" : dictation.recording ? "Se înregistrează…" : dictation.transcribing ? "Se transcrie…" : "";
  const dictationLabel = dictation.requesting ? "Anulează pornirea microfonului" : dictation.recording ? "Oprește dictarea" : dictation.transcribing ? "Se transcrie înregistrarea" : "Dictează mesajul";
  return <section className="companion-chat" aria-label="Chat cu Guguță" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
    <div className="companion-chat__messages" ref={messageBox} role="log" aria-label="Mesajele conversației" aria-live="polite" aria-busy={sending}>
      {recentMessages.map(message => <div key={message.id} className={`companion-chat__message companion-chat__message--${message.role}`} aria-label={message.role === "user" ? "Tu" : "Guguță"}><span className="companion-chat__author">{message.role === "user" ? "Tu" : "Guguță"}</span><p>{message.role === "user" ? message.content.replace(/^Context educațional: [^\n]*\.\n\n/, "") : message.content}</p></div>)}
      {streaming && <div className="companion-chat__message companion-chat__message--assistant" aria-label="Guguță"><span className="companion-chat__author">Guguță</span><p>{streaming}</p></div>}
      {sending && !streaming && <div className="companion-chat__message companion-chat__message--assistant"><span className="companion-chat__author">Guguță</span><div className="companion-chat__waiting" role="status"><span>{waitingMessage}</span><div className="companion-chat__typing" aria-hidden="true"><span /><span /><span /></div></div></div>}
      {authState === "guest" && <p className="companion-chat__hint"><a href={loginHref}>Autentifică-te</a> pentru a vorbi cu Guguță.</p>}
    </div>
    {(error || dictation.error) && <p className="companion-chat__error" role="alert">{error || dictation.error}{authState === "error" && <> <button type="button" onClick={() => setRetry(value => value + 1)}>Reîncearcă</button></>}</p>}
    {(authState === "ready" || authState === "loading") && !sending && <form className="companion-chat__composer" aria-busy={authState === "loading"} onSubmit={event => { event.preventDefault(); void send(); }}>
      <label htmlFor={`${titleId}-message`}>Mesajul tău</label>
      <div className="companion-chat__input-row">
        <textarea ref={textarea} id={`${titleId}-message`} value={draft} onChange={event => setDraft(event.target.value)} maxLength={18000} rows={2} placeholder="Scrie…" disabled={authState !== "ready"} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
        <button type="button" className="companion-chat__dictation" aria-label={dictationLabel} title={dictationLabel} aria-pressed={dictation.recording || dictation.requesting} aria-busy={dictation.requesting || dictation.transcribing} aria-describedby={dictationStatus ? `${titleId}-dictation-status` : undefined} disabled={authState !== "ready" || dictation.transcribing} onClick={() => { if (authState === "ready") void dictation.toggle(); }}>
          {dictation.transcribing ? <svg className="companion-chat__dictation-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="8" strokeDasharray="36 15" /></svg> : dictation.recording || dictation.requesting ? <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" /></svg> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></svg>}
        </button>
      </div>
      {dictationStatus && <p id={`${titleId}-dictation-status`} className="companion-chat__dictation-status" role="status">{dictationStatus}</p>}
    </form>}
  </section>;
}
