"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Conversation } from "@elevenlabs/client";
import type { GugutaContext } from "./guguta-companion";

export type VoicePhase = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "stopping" | "error";
export interface VoiceMessage { id: string; role: "user" | "assistant"; content: string }
interface Options { apiBase: string; context: GugutaContext; scope: string }
interface Session { conversationToken: string; contextText: string; dynamicVariables: Record<string, string | number | boolean> }
interface Auth { csrf: string; actor_id: string }
class VoiceRequestError extends Error { constructor(public status: number, message: string) { super(message); } }

export function useElevenLabsVoice({ apiBase, context, scope }: Options) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const mounted = useRef(false);
  const generation = useRef(0);
  const phaseRef = useRef<VoicePhase>("idle");
  const session = useRef<Conversation | null>(null);
  const pending = useRef<Promise<Conversation> | null>(null);
  const ending = useRef<Promise<void> | null>(null);
  const requests = useRef(new Set<AbortController>());
  const actor = useRef<string | null>(null);
  const latest = useRef({ apiBase, context, scope });
  latest.current = { apiBase, context, scope };
  const contextJson = JSON.stringify(context);
  const connectedContext = useRef("");

  const changePhase = useCallback((value: VoicePhase) => {
    phaseRef.current = value;
    if (mounted.current) setPhase(value);
  }, []);

  const stop = useCallback((): Promise<void> => {
    if (ending.current) return ending.current;
    const stoppedGeneration = ++generation.current;
    requests.current.forEach(controller => controller.abort());
    requests.current.clear();
    actor.current = null;
    connectedContext.current = "";
    const live = session.current;
    const starting = pending.current;
    session.current = null;
    pending.current = null;
    if (mounted.current) { setMuted(false); setConnected(false); }
    if (!live && !starting) { changePhase("idle"); return Promise.resolve(); }
    changePhase("stopping");
    // endSession detaches playback and closes the SDK-owned microphone tracks.
    // Do not zero the output: LiveKit recycles audio elements between sessions
    // and preserves their volume, which would silence the next conversation.
    try { live?.setMicMuted(true); } catch { /* Already disconnected. */ }
    const task = (async () => {
      if (live) await live.endSession().catch(() => undefined);
      if (starting) {
        // SDK startup has no AbortSignal. A late session is closed before it can become active here.
        const late = await starting.catch(() => null);
        if (late && late !== live) {
          try { late.setMicMuted(true); } catch { /* Already disconnected. */ }
          await late.endSession().catch(() => undefined);
        }
      }
    })();
    ending.current = task;
    void task.finally(() => {
      if (ending.current === task) {
        ending.current = null;
        if (generation.current === stoppedGeneration) changePhase("idle");
      }
    });
    return task;
  }, [changePhase]);

  const request = useCallback(async <T,>(path: string, body: unknown | undefined, expectedActor?: string): Promise<T> => {
    const controller = new AbortController();
    requests.current.add(controller);
    const timeout = window.setTimeout(() => controller.abort(), path === "session" ? 45000 : 25000);
    const base = latest.current.apiBase;
    try {
      const authResponse = await fetch(`${base}/api/v1/auth/csrf`, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      const authData = await authResponse.json().catch(() => ({})) as Auth;
      if (!authResponse.ok || !authData.csrf) throw new VoiceRequestError(authResponse.status, authResponse.status === 401 ? "Autentifică-te pentru a începe conversația vocală." : "Conexiunea la platformă nu este disponibilă. Încearcă din nou.");
      if (expectedActor && authData.actor_id !== expectedActor) throw new VoiceRequestError(401, "Contul s-a schimbat. Pornește o conversație nouă.");
      const response = await fetch(`${base}/api/v1/voice/elevenlabs/${path}`, {
        method: "POST", credentials: "same-origin", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-Guguta-CSRF": authData.csrf }, body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new VoiceRequestError(response.status, typeof data.message === "string" ? data.message : typeof data.detail === "string" ? data.detail : "Conversația vocală nu este disponibilă momentan.");
      if (path === "session") actor.current = authData.actor_id;
      return data as T;
    } finally { window.clearTimeout(timeout); requests.current.delete(controller); }
  }, []);

  const start = useCallback(async () => {
    if (!mounted.current || ending.current || pending.current || session.current || !["idle", "error"].includes(phaseRef.current)) return;
    if (!navigator.mediaDevices?.getUserMedia) { setError("Browserul nu permite accesul la microfon. Folosește o conexiune HTTPS și un browser actualizat."); changePhase("error"); return; }
    const token = ++generation.current;
    const initialScope = latest.current.scope;
    const active = () => mounted.current && generation.current === token && latest.current.scope === initialScope;
    setError(""); setLoginRequired(false); setMessages([]); setMuted(false);
    changePhase("connecting");
    try {
      // Authorization and context resolution happen before requesting the microphone.
      const snapshot = JSON.parse(JSON.stringify(latest.current.context)) as GugutaContext;
      const configuration = await request<Session>("session", { context: snapshot });
      if (!active()) return;
      const { Conversation: ClientConversation } = await import("@elevenlabs/client");
      if (!active()) return;
      const promise = ClientConversation.startSession({
        conversationToken: configuration.conversationToken,
        connectionType: "webrtc", textOnly: false,
        webRtc: { singlePeerConnection: false },
        dynamicVariables: configuration.dynamicVariables,
        onConversationCreated: conversation => {
          if (!active()) {
            conversation.setMicMuted(true);
            void conversation.endSession().catch(() => undefined);
          } else {
            session.current = conversation;
            conversation.setVolume({ volume: 1 });
            conversation.setMicMuted(false);
          }
        },
        onDebug: event => {
          // Tracks can attach after onConversationCreated. Restore the volume
          // after attachment too, including recycled elements from an older call.
          if (active() && event?.type === "audio_element_ready") session.current?.setVolume({ volume: 1 });
        },
        onConnect: () => { if (active()) { setConnected(true); changePhase("listening"); } },
        onModeChange: ({ mode }) => { if (active()) changePhase(mode === "speaking" ? "speaking" : "listening"); },
        onMessage: message => {
          if (!active() || !message.message.trim()) return;
          const role = message.role === "user" ? "user" : "assistant";
          const id = `${role}:${message.event_id}`;
          const entry: VoiceMessage = { id, role, content: message.message };
          setMessages(previous => [...previous.filter(item => item.id !== id), entry].slice(-40));
          if (role === "user") changePhase("thinking");
        },
        onInterruption: () => { if (active()) changePhase("listening"); },
        onAgentToolRequest: () => { if (active()) changePhase("thinking"); },
        onError: () => {
          if (!active()) return;
          setError("Conversația vocală s-a întrerupt. Poți încerca din nou.");
          void stop();
        },
        onDisconnect: details => {
          if (!active()) return;
          if (details.reason === "error") setError("Conexiunea vocală s-a întrerupt. Pornește din nou conversația.");
          void stop();
        },
        clientTools: {
          search_notebook_materials: async (parameters: { query?: unknown }) => {
            if (!active()) return "Conversația s-a încheiat.";
            const query = typeof parameters?.query === "string" ? parameters.query.trim().slice(0, 1000) : "";
            if (!query) return "Indică întrebarea sau fragmentul căutat în materialele selectate.";
            const captured = JSON.stringify(latest.current.context);
            try {
              const result = await request<{ contextText: string }>("context", { context: JSON.parse(captured), query }, actor.current ?? undefined);
              if (!active() || captured !== JSON.stringify(latest.current.context)) return "Contextul elevului s-a schimbat. Reia căutarea pentru materialul curent.";
              return result.contextText;
            } catch (cause) {
              if (cause instanceof VoiceRequestError && cause.status === 401 && active()) { setLoginRequired(true); void stop(); }
              return "Materialele nu au putut fi consultate momentan. Nu inventa conținutul lor; cere elevului să reformuleze sau să încerce din nou.";
            }
          },
        },
      });
      pending.current = promise;
      const conversation = await promise;
      if (pending.current === promise) pending.current = null;
      if (!active()) { await conversation.endSession().catch(() => undefined); return; }
      session.current = conversation;
      connectedContext.current = JSON.stringify(snapshot);
      conversation.sendContextualUpdate(configuration.contextText, { contextId: "guguta-current-learning-context" });
      setConnected(true);
    } catch (cause) {
      if (!active()) return;
      pending.current = null;
      setConnected(false);
      if (cause instanceof VoiceRequestError) { setError(cause.message); setLoginRequired(cause.status === 401); }
      else if (cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name)) setError("Permite accesul la microfon pentru a vorbi cu Guguță.");
      else if (cause instanceof DOMException && cause.name === "NotFoundError") setError("Nu am găsit un microfon disponibil.");
      else setError("Conversația vocală nu a putut porni. Verifică microfonul și conexiunea, apoi încearcă din nou.");
      if (session.current) await stop();
      if (mounted.current) changePhase("error");
    }
  }, [changePhase, request, stop]);

  useEffect(() => {
    mounted.current = true;
    const end = () => { void stop(); };
    const visibility = () => { if (document.hidden) end(); };
    const storage = (event: StorageEvent) => { if (event.key === "guguta.logout") end(); };
    window.addEventListener("pagehide", end);
    window.addEventListener("guguta:logout", end);
    window.addEventListener("storage", storage);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", end); window.removeEventListener("guguta:logout", end); window.removeEventListener("storage", storage);
      document.removeEventListener("visibilitychange", visibility); void stop();
    };
  }, [scope, apiBase, stop]);

  useEffect(() => {
    if (!connected || !session.current || contextJson === connectedContext.current) return;
    let cancelled = false;
    const token = generation.current;
    const timer = window.setTimeout(() => {
      void request<{ contextText: string }>("context", { context: JSON.parse(contextJson) }, actor.current ?? undefined).then(result => {
        if (cancelled || token !== generation.current || !session.current) return;
        session.current.sendContextualUpdate(result.contextText, { contextId: "guguta-current-learning-context" });
        connectedContext.current = contextJson;
      }).catch(cause => {
        if (cancelled || token !== generation.current) return;
        setError(cause instanceof VoiceRequestError ? cause.message : "Nu am putut actualiza materialul conversației. Pornește din nou conversația.");
        if (cause instanceof VoiceRequestError && cause.status === 401) setLoginRequired(true);
        // Never keep a voice agent speaking about a stale card or unauthorized context.
        void stop();
      });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [contextJson, connected, request, stop]);

  const toggleMuted = useCallback(() => {
    if (!session.current || !connected) return;
    setMuted(previous => { const next = !previous; session.current?.setMicMuted(next); return next; });
  }, [connected]);

  // Read the SDK's existing output analyser without opening another audio stream.
  // A stable accessor lets the mascot animate without React renders per sample.
  const getOutputVolume = useCallback(() => {
    const current = session.current;
    if (!current || current.type !== "voice" || phaseRef.current !== "speaking") return 0;
    try {
      const volume = current.getOutputVolume();
      return Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0;
    } catch { return 0; }
  }, []);

  return { phase, connected, active: !["idle", "error"].includes(phase), muted, error, loginRequired, messages, start, stop, toggleMuted, getOutputVolume };
}
