"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { GugutaContext } from "./guguta-companion";
import type { VoiceMessage, VoicePhase } from "./useElevenLabsVoice";
import { liveContextChunks, liveTranscriptMessages, type LiveTranscriptFragment } from "./openai-live-events";

interface Options { apiBase: string; context: GugutaContext; scope: string }
interface SessionAnswer { session: { id: string }; transport: { type: "webrtc"; sdp: string } }
class VoiceRequestError extends Error { constructor(public status: number, message: string) { super(message); } }
interface LiveConnection {
  apiBase: string; scope: string; contextJson: string; actor: string | null;
  peer: RTCPeerConnection; channel: RTCDataChannel; audio: HTMLAudioElement;
  microphone: MediaStream | null; output: MediaStream | null; audioContext: AudioContext | null;
  source: MediaStreamAudioSourceNode | null; analyser: AnalyserNode | null;
  abort: AbortController; started: boolean; closed: boolean; stopping: boolean; disposed: boolean;
  startedPromise: Promise<void>; resolveStarted: () => void; rejectStarted: (error: Error) => void;
  closedPromise: Promise<void>; resolveClosed: () => void;
  requests: Set<AbortController>; events: Set<string>; delegations: Set<string>;
  fragments: LiveTranscriptFragment[]; messages: VoiceMessage[]; userRevision: number;
  volume: number; lastSound: number; work: number; muted: boolean;
  sampling?: number; reconnectTimer?: number;
}

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no; });
  // An early disconnect can reject this before startup reaches its final await.
  void promise.catch(() => undefined);
  return { promise, resolve, reject };
}

function release(connection: LiveConnection) {
  if (connection.disposed) return;
  connection.disposed = true;
  connection.abort.abort();
  connection.requests.forEach(controller => controller.abort());
  window.clearInterval(connection.sampling);
  window.clearTimeout(connection.reconnectTimer);
  connection.peer.ontrack = null;
  connection.peer.onconnectionstatechange = null;
  connection.channel.onmessage = null;
  connection.channel.onclose = null;
  connection.channel.onerror = null;
  connection.microphone?.getTracks().forEach(track => { track.onended = null; track.stop(); });
  connection.output?.getTracks().forEach(track => track.stop());
  connection.source?.disconnect();
  connection.analyser?.disconnect();
  if (connection.audioContext) void connection.audioContext.close().catch(() => undefined);
  connection.audio.pause();
  connection.audio.srcObject = null;
  connection.audio.remove();
  connection.channel.close();
  connection.peer.close();
  connection.volume = 0;
}

async function request<T>(connection: LiveConnection, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  connection.requests.add(controller);
  connection.abort.signal.addEventListener("abort", abort, { once: true });
  signal?.addEventListener("abort", abort, { once: true });
  if (connection.abort.signal.aborted || signal?.aborted) controller.abort();
  const timeout = window.setTimeout(abort, path === "session" ? 65000 : 25000);
  try {
    const authResponse = await fetch(connection.apiBase + "/api/v1/auth/csrf", {
      credentials: "same-origin", cache: "no-store", signal: controller.signal,
    });
    const auth = await authResponse.json().catch(() => ({}));
    if (!authResponse.ok || typeof auth.csrf !== "string" || typeof auth.actor_id !== "string") {
      throw new VoiceRequestError(authResponse.status, authResponse.status === 401
        ? "Autentifică-te pentru a începe conversația vocală." : "Conexiunea la platformă nu este disponibilă.");
    }
    if (connection.actor && connection.actor !== auth.actor_id) throw new VoiceRequestError(401, "Contul s-a schimbat. Pornește o conversație nouă.");
    connection.actor = auth.actor_id;
    const response = await fetch(connection.apiBase + "/api/v1/voice/openai/" + path, {
      method: "POST", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Guguta-CSRF": auth.csrf },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new VoiceRequestError(response.status,
      typeof data.message === "string" ? data.message : typeof data.detail === "string" ? data.detail : "Serviciul vocal OpenAI nu este disponibil momentan.");
    return data as T;
  } finally {
    window.clearTimeout(timeout);
    connection.requests.delete(controller);
    connection.abort.signal.removeEventListener("abort", abort);
    signal?.removeEventListener("abort", abort);
  }
}

function waitForIce(connection: LiveConnection): Promise<void> {
  if (connection.peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const finish = (error?: Error) => {
      window.clearTimeout(timer);
      connection.peer.removeEventListener("icegatheringstatechange", check);
      connection.abort.signal.removeEventListener("abort", abort);
      if (error) reject(error); else resolve();
    };
    const check = () => { if (connection.peer.iceGatheringState === "complete") finish(); };
    const abort = () => finish(new DOMException("Conversație oprită", "AbortError"));
    const timer = window.setTimeout(() => finish(new Error("Conexiunea audio durează prea mult.")), 10000);
    connection.peer.addEventListener("icegatheringstatechange", check);
    connection.abort.signal.addEventListener("abort", abort, { once: true });
    if (connection.abort.signal.aborted) abort(); else check();
  });
}

function append(connection: LiveConnection, type: "session.thinking.append" | "session.commentary.append" | "session.instructions.append", text: string, delegationId: string | null = null) {
  if (!connection.started || connection.stopping || connection.channel.readyState !== "open") throw new Error("Conversația nu este conectată.");
  for (const content of liveContextChunks(text)) {
    if (connection.channel.bufferedAmount > 128000) throw new Error("Conexiunea audio este ocupată.");
    connection.channel.send(JSON.stringify({ type, event_id: "guguta-" + crypto.randomUUID(), delegation_id: delegationId, content }));
  }
}

/** GPT-Live WebRTC, deliberately separate from the legacy Realtime protocol. */
export function useOpenAILiveVoice({ apiBase, context, scope }: Options) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [connected, setConnected] = useState(false);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const [playbackBlocked, setPlaybackBlocked] = useState(false);
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const mounted = useRef(false);
  const generation = useRef(0);
  const phaseRef = useRef<VoicePhase>("idle");
  const current = useRef<LiveConnection | null>(null);
  const ending = useRef<Promise<void> | null>(null);
  const latest = useRef({ apiBase, context, scope });
  latest.current = { apiBase, context, scope };
  const contextJson = JSON.stringify(context);
  const changePhase = useCallback((value: VoicePhase) => {
    if (phaseRef.current === value) return;
    phaseRef.current = value;
    if (mounted.current) setPhase(value);
  }, []);

  const stop = useCallback((): Promise<void> => {
    if (ending.current) return ending.current;
    const token = ++generation.current;
    const connection = current.current;
    if (mounted.current) { setConnected(false); setMuted(false); setPlaybackBlocked(false); }
    if (!connection) { changePhase("idle"); return Promise.resolve(); }
    connection.stopping = true;
    connection.abort.abort();
    connection.rejectStarted(new DOMException("Conversație oprită", "AbortError"));
    connection.microphone?.getAudioTracks().forEach(track => { track.enabled = false; });
    connection.audio.muted = true;
    changePhase("stopping");
    const task = (async () => {
      if (connection.started && !connection.closed && connection.channel.readyState === "open") {
        let timeout: number | undefined;
        try {
          connection.channel.send(JSON.stringify({ type: "session.close", event_id: "guguta-close-" + crypto.randomUUID() }));
          // Keep the transport alive for finalization, but silence input/output immediately.
          await Promise.race([connection.closedPromise, new Promise<void>(resolve => { timeout = window.setTimeout(resolve, 3000); })]);
        } catch { /* A failed transport still needs local cleanup. */ }
        finally { window.clearTimeout(timeout); }
      }
      release(connection);
      if (current.current === connection) current.current = null;
    })();
    ending.current = task;
    void task.finally(() => {
      if (ending.current === task) ending.current = null;
      if (generation.current === token) changePhase("idle");
    });
    return task;
  }, [changePhase]);

  const start = useCallback(async () => {
    if (!mounted.current || current.current || ending.current || !["idle", "error"].includes(phaseRef.current)) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
      setError("Browserul nu permite conversații vocale. Folosește HTTPS și un browser actualizat."); changePhase("error"); return;
    }
    const token = ++generation.current;
    const initial = latest.current;
    const active = () => mounted.current && generation.current === token && latest.current.scope === initial.scope;
    setError(""); setLoginRequired(false); setPlaybackBlocked(false); setMessages([]); setMuted(false);
    changePhase("connecting");
    let connection: LiveConnection | null = null;
    try {
      const peer = new RTCPeerConnection();
      const audio = new Audio();
      audio.autoplay = true; audio.volume = 1; audio.muted = false; audio.setAttribute("playsinline", "");
      const started = deferred();
      const closed = deferred();
      const channel = peer.createDataChannel("oai-events");
      connection = {
        apiBase: initial.apiBase, scope: initial.scope, contextJson: JSON.stringify(initial.context), actor: null,
        peer, channel, audio, microphone: null, output: null, audioContext: null, source: null, analyser: null,
        abort: new AbortController(), started: false, closed: false, stopping: false, disposed: false,
        startedPromise: started.promise, resolveStarted: started.resolve, rejectStarted: started.reject,
        closedPromise: closed.promise, resolveClosed: closed.resolve, requests: new Set(), events: new Set(), delegations: new Set(),
        fragments: [], messages: [], userRevision: 0, volume: 0, lastSound: 0, work: 0, muted: false,
      };
      const live = connection;
      current.current = live;
      // Both permission and audio-context activation originate in the user's click.
      const microphone = navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }).then(stream => {
        if (!active() || live.disposed) {
          stream.getTracks().forEach(track => track.stop());
          throw new DOMException("Conversație oprită", "AbortError");
        }
        live.microphone = stream;
        return stream;
      });
      void microphone.catch(() => undefined);
      try {
        const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (AudioContextClass) { live.audioContext = new AudioContextClass(); void live.audioContext.resume().catch(() => undefined); }
      } catch { /* Audio playback still works without the optional motion analyser. */ }
      const fail = (message: string) => { if (active()) { setError(message); void stop(); } };
      peer.ontrack = event => {
        if (!active() || live.disposed) return;
        live.output = event.streams[0] || new MediaStream([event.track]);
        audio.srcObject = live.output;
        void audio.play().then(() => { if (active()) setPlaybackBlocked(false); }).catch(() => { if (active()) setPlaybackBlocked(true); });
        if (live.audioContext) try {
          live.source?.disconnect();
          live.analyser?.disconnect();
          live.source = live.audioContext.createMediaStreamSource(live.output);
          live.analyser = live.audioContext.createAnalyser();
          live.analyser.fftSize = 512;
          live.source.connect(live.analyser);
          const silent = live.audioContext.createGain();
          silent.gain.value = 0;
          live.analyser.connect(silent); silent.connect(live.audioContext.destination);
        } catch { /* Playback remains independent from the optional animation analyser. */ }
      };
      peer.onconnectionstatechange = () => {
        window.clearTimeout(live.reconnectTimer);
        if (!active() || live.stopping) return;
        if (peer.connectionState === "failed") fail("Conexiunea vocală s-a întrerupt. Încearcă din nou.");
        else if (peer.connectionState === "disconnected") live.reconnectTimer = window.setTimeout(() => {
          if (peer.connectionState === "disconnected") fail("Conexiunea vocală s-a întrerupt. Încearcă din nou.");
        }, 5000);
      };
      const serveDelegation = async (id: string) => {
        live.work += 1;
        try {
          for (let attempt = 0; attempt < 2; attempt++) {
            const captured = JSON.stringify(latest.current.context);
            const revision = live.userRevision;
            const query = live.messages.slice(-4).map(message => (message.role === "user" ? "Elev: " : "Guguță: ") + message.content).join("\n").slice(-1000);
            const result = await request<{ contextText: string }>(live, "context", { context: JSON.parse(captured), ...(query ? { query } : {}) });
            if (!active() || live.stopping) return;
            if (captured !== JSON.stringify(latest.current.context)) {
              append(live, "session.thinking.append", "Elevul a schimbat materialul. Rezultatul căutării anterioare a fost abandonat; folosește noul context al paginii.", id);
              return;
            }
            if (revision !== live.userRevision) {
              if (attempt === 0) continue;
              append(live, "session.instructions.append", "Întrebarea a fost completată în timpul căutării. Cere elevului să precizeze ce dorește să afle înainte de a continua.", id);
              return;
            }
            append(live, "session.thinking.append", result.contextText, id);
            append(live, "session.instructions.append", "Răspunde folosind dovezile verificate primite. Spune dacă informația lipsește. La exerciții, cere întâi încercarea elevului și ghidează-l pas cu pas.", id);
            return;
          }
        } catch (cause) {
          if (!active() || live.stopping) return;
          if (cause instanceof VoiceRequestError && (cause.status === 401 || cause.status === 404)) {
            setLoginRequired(cause.status === 401); fail(cause.message); return;
          }
          try {
            append(live, "session.instructions.append", "Consultarea materialelor a eșuat. Nu inventa conținutul lor și nu pretinde că ai verificat informația.", id);
            append(live, "session.commentary.append", "Nu am reușit să consult materialele acum. Putem încerca din nou.", id);
          }
          catch { fail("Nu am putut continua conversația. Încearcă din nou."); }
        } finally { live.work = Math.max(0, live.work - 1); }
      };
      channel.onmessage = ({ data }) => {
        let event: Record<string, any>;
        try { event = JSON.parse(data); } catch { return; }
        if (!event || typeof event !== "object") return;
        if (event.type === "session.closed") {
          live.closed = true; live.resolveClosed();
          if (active()) void stop();
          return;
        }
        if (!active() || live.stopping || live.disposed) return;
        if (typeof event.event_id === "string") {
          if (live.events.has(event.event_id)) return;
          live.events.add(event.event_id);
          if (live.events.size > 2000) live.events.delete(live.events.values().next().value!);
        }
        if (event.type === "session.started") {
          live.started = true; live.resolveStarted(); setConnected(true); changePhase("listening");
        } else if (event.type === "error") {
          fail("OpenAI nu a putut continua conversația vocală. Încearcă din nou.");
        } else if (event.type === "session.input_transcript.delta" || event.type === "session.output_transcript.delta") {
          if (typeof event.delta !== "string" || !Number.isFinite(event.start_ms) || !Number.isFinite(event.end_ms)) return;
          const role = event.type === "session.input_transcript.delta" ? "user" : "assistant";
          if (role === "user") live.userRevision += 1;
          live.fragments.push({ id: event.event_id || crypto.randomUUID(), role, delta: event.delta,
            startMs: event.start_ms, endMs: event.end_ms, order: live.fragments.length });
          live.fragments = live.fragments.slice(-800);
          live.messages = liveTranscriptMessages(live.fragments);
          setMessages(live.messages);
        } else if (event.type === "session.delegation.created" && event.delegation?.target === "client" && typeof event.delegation.id === "string") {
          const id = event.delegation.id;
          if (!live.delegations.has(id)) { live.delegations.add(id); void serveDelegation(id); }
        }
      };
      channel.onclose = () => {
        live.resolveClosed();
        if (active()) fail("Conexiunea vocală s-a întrerupt. Încearcă din nou.");
      };
      channel.onerror = () => fail("Conexiunea vocală nu este disponibilă.");
      const stream = await microphone;
      if (!active() || live.disposed) { stream.getTracks().forEach(track => track.stop()); return; }
      live.microphone = stream;
      for (const track of stream.getAudioTracks()) {
        track.onended = () => { if (active() && !live.stopping) fail("Microfonul a fost deconectat."); };
        peer.addTrack(track, stream);
      }
      await peer.setLocalDescription(await peer.createOffer());
      await waitForIce(live);
      if (!active()) return;
      const sdp = peer.localDescription?.sdp;
      if (!sdp) throw new Error("Nu am putut pregăti conexiunea audio.");
      const answer = await request<SessionAnswer>(live, "session", { context: JSON.parse(live.contextJson), sdp });
      if (!active()) return;
      if (answer.transport?.type !== "webrtc" || !answer.transport.sdp || typeof answer.session?.id !== "string") throw new Error("Răspuns vocal invalid.");
      await peer.setRemoteDescription({ type: "answer", sdp: answer.transport.sdp });
      const startupTimeout = window.setTimeout(() => live.rejectStarted(new Error("Conexiunea audio durează prea mult.")), 20000);
      try { await live.startedPromise; } finally { window.clearTimeout(startupTimeout); }
      if (!active()) return;
      const samples = new Uint8Array(512);
      live.sampling = window.setInterval(() => {
        if (!active() || !live.started || live.stopping) return;
        let rms = 0;
        if (live.analyser && !audio.paused && !audio.muted) {
          live.analyser.getByteTimeDomainData(samples);
          for (const sample of samples) rms += ((sample - 128) / 128) ** 2;
          rms = Math.sqrt(rms / samples.length);
        }
        live.volume = Math.min(1, rms * 4);
        if (rms > 0.008) live.lastSound = performance.now();
        changePhase(performance.now() - live.lastSound < 250 ? "speaking" : live.work > 0 ? "thinking" : "listening");
      }, 100);
    } catch (cause) {
      if (!active()) return;
      if (cause instanceof VoiceRequestError) { setError(cause.message); setLoginRequired(cause.status === 401); }
      else if (cause instanceof DOMException && ["NotAllowedError", "SecurityError"].includes(cause.name)) setError("Permite accesul la microfon pentru a vorbi cu Guguță.");
      else if (cause instanceof DOMException && cause.name === "NotFoundError") setError("Nu am găsit un microfon disponibil.");
      else setError("Conversația OpenAI nu a putut porni. Verifică microfonul și conexiunea, apoi încearcă din nou.");
      await stop();
      if (mounted.current && generation.current === token + 1) changePhase("error");
    }
  }, [changePhase, stop]);

  useEffect(() => {
    mounted.current = true;
    const end = () => { void stop(); };
    const visibility = () => { if (document.hidden) end(); };
    const storage = (event: StorageEvent) => { if (event.key === "guguta.logout") end(); };
    window.addEventListener("pagehide", end); window.addEventListener("guguta:logout", end);
    window.addEventListener("storage", storage); document.addEventListener("visibilitychange", visibility);
    return () => {
      mounted.current = false;
      window.removeEventListener("pagehide", end); window.removeEventListener("guguta:logout", end);
      window.removeEventListener("storage", storage); document.removeEventListener("visibilitychange", visibility);
      void stop();
    };
  }, [scope, apiBase, stop]);

  useEffect(() => {
    const connection = current.current;
    if (!connected || !connection?.started || connection.contextJson === contextJson) return;
    const controller = new AbortController();
    const token = generation.current;
    const timer = window.setTimeout(() => {
      connection.work += 1;
      void request<{ contextText: string }>(connection, "context", { context: JSON.parse(contextJson) }, controller.signal).then(result => {
        if (controller.signal.aborted || generation.current !== token || current.current !== connection) return;
        append(connection, "session.thinking.append", "Context nou al paginii; înlocuiește selecția anterioară cu următoarea:\n" + result.contextText);
        connection.contextJson = contextJson;
      }).catch(cause => {
        if (controller.signal.aborted || generation.current !== token) return;
        setError(cause instanceof VoiceRequestError ? cause.message : "Nu am putut actualiza materialul conversației. Pornește din nou conversația.");
        if (cause instanceof VoiceRequestError && cause.status === 401) setLoginRequired(true);
        void stop();
      }).finally(() => { connection.work = Math.max(0, connection.work - 1); });
    }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [contextJson, connected, stop]);

  const toggleMuted = useCallback(() => {
    const connection = current.current;
    if (!connection?.started || connection.stopping) return;
    connection.muted = !connection.muted;
    connection.microphone?.getAudioTracks().forEach(track => { track.enabled = !connection.muted; });
    setMuted(connection.muted);
  }, []);
  const getOutputVolume = useCallback(() => current.current?.volume ?? 0, []);
  const resumePlayback = useCallback(async () => {
    const connection = current.current;
    if (!connection || connection.stopping) return;
    try {
      await Promise.all([connection.audio.play(), connection.audioContext?.resume()]);
      if (mounted.current && current.current === connection) setPlaybackBlocked(false);
    } catch { if (mounted.current && current.current === connection) setPlaybackBlocked(true); }
  }, []);
  return { phase, connected, active: !["idle", "error"].includes(phase), muted, error, loginRequired, messages, start, stop, toggleMuted, getOutputVolume, playbackBlocked, resumePlayback };
}
