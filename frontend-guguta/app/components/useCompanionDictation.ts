"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Phase = "idle" | "requesting" | "recording" | "transcribing";
interface Options {
  apiBase: string;
  scope: string;
  onTranscript: (text: string) => void;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as { message?: unknown; detail?: unknown };
  const value = data.message ?? data.detail;
  return typeof value === "string" && value.trim() ? value : fallback;
}

/** Records only on an explicit start/toggle call; transcription remains editable text. */
export function useCompanionDictation({ apiBase, scope, onTranscript }: Options) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const mounted = useRef(true);
  const generation = useRef(0);
  const scopeRef = useRef(scope);
  const baseRef = useRef(apiBase);
  const transcriptRef = useRef(onTranscript);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const uploadRef = useRef<AbortController | null>(null);
  scopeRef.current = scope;
  baseRef.current = apiBase;
  transcriptRef.current = onTranscript;

  const changePhase = useCallback((value: Phase) => {
    phaseRef.current = value;
    if (mounted.current) setPhase(value);
  }, []);

  const dispose = useCallback(() => {
    generation.current += 1;
    uploadRef.current?.abort();
    uploadRef.current = null;
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") {
        try { recorder.stop(); } catch { /* Tracks still close below. */ }
      }
    }
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
    phaseRef.current = "idle";
  }, []);

  const cancel = useCallback(() => {
    dispose();
    if (mounted.current) { setPhase("idle"); setError(null); }
  }, [dispose]);

  const previousScope = useRef({ scope, apiBase });
  useEffect(() => {
    mounted.current = true;
    if (previousScope.current.scope !== scope || previousScope.current.apiBase !== apiBase) {
      setPhase("idle");
      setError(null);
      previousScope.current = { scope, apiBase };
    }
    return () => { mounted.current = false; dispose(); };
  }, [scope, apiBase, dispose]);

  const start = useCallback(async () => {
    if (phaseRef.current !== "idle" || !mounted.current) return;
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Browserul tău nu permite înregistrarea audio.");
      return;
    }
    const token = ++generation.current;
    const requestScope = scopeRef.current;
    const requestBase = baseRef.current.replace(/\/$/, "");
    const current = () => mounted.current && generation.current === token
      && scopeRef.current === requestScope && baseRef.current.replace(/\/$/, "") === requestBase;
    changePhase("requesting");

    const transcribe = async (blob: Blob, mimeType: string) => {
      if (!current()) return;
      if (!blob.size) { setError("Nu s-a înregistrat sunet. Încearcă din nou."); changePhase("idle"); return; }
      changePhase("transcribing");
      const controller = new AbortController();
      uploadRef.current = controller;
      try {
        const auth = await fetch(`${requestBase}/api/v1/auth/csrf`, {
          credentials: "same-origin", signal: controller.signal,
        });
        const authData = await auth.json().catch(() => ({})) as { csrf?: string };
        if (!auth.ok || !authData.csrf) {
          throw new Error(auth.status === 401 || auth.status === 403
            ? "Autentifică-te pentru a folosi dictarea."
            : errorMessage(authData, "Nu am putut pregăti dictarea. Încearcă din nou."));
        }
        if (!current()) return;
        const form = new FormData();
        const extension = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "m4a" : "webm";
        form.append("file", blob, `inregistrare.${extension}`);
        const response = await fetch(`${requestBase}/api/v1/speech/transcriptions`, {
          method: "POST", credentials: "same-origin", signal: controller.signal,
          headers: { "X-Guguta-CSRF": authData.csrf }, body: form,
        });
        const payload = await response.json().catch(() => ({})) as { text?: unknown };
        if (!response.ok) throw new Error(errorMessage(payload, "Nu am putut transcrie înregistrarea."));
        if (!current()) return;
        const text = typeof payload.text === "string" ? payload.text.trim() : "";
        if (text) transcriptRef.current(text);
        else setError("Nu am recunoscut cuvinte în înregistrare. Încearcă din nou.");
      } catch (cause) {
        if (current() && !controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Nu am putut transcrie înregistrarea.");
        }
      } finally {
        if (uploadRef.current === controller) uploadRef.current = null;
        if (current()) changePhase("idle");
      }
    };

    try {
      // Keep this call before any await so a caller can invoke start in the original click.
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!current()) { stream.getTracks().forEach(track => track.stop()); return; }
      streamRef.current = stream;
      const preferred = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
      const mimeType = preferred.find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = event => { if (current() && event.data.size) chunks.push(event.data); };
      recorder.onerror = () => {
        if (!current()) return;
        dispose();
        setPhase("idle");
        setError("Înregistrarea s-a întrerupt. Încearcă din nou.");
      };
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        if (recorderRef.current === recorder) recorderRef.current = null;
        if (!current()) return;
        const actualType = recorder.mimeType || mimeType || "audio/webm";
        void transcribe(new Blob(chunks, { type: actualType }), actualType);
      };
      recorder.start(250);
      changePhase("recording");
    } catch (cause) {
      if (!current()) return;
      dispose();
      setPhase("idle");
      const name = cause instanceof DOMException ? cause.name : "";
      setError(name === "NotAllowedError" ? "Permite accesul la microfon pentru a dicta întrebarea."
        : name === "NotFoundError" ? "Nu am găsit un microfon disponibil."
        : "Microfonul nu a putut fi pornit.");
    }
  }, [changePhase, dispose]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder?.state === "recording" || recorder?.state === "paused") {
      recorder.stop();
      streamRef.current?.getTracks().forEach(track => track.stop());
    }
  }, []);

  const toggle = useCallback(async () => {
    if (phaseRef.current === "recording") stop();
    else if (phaseRef.current === "requesting") cancel();
    else if (phaseRef.current === "idle") await start();
  }, [cancel, start, stop]);

  return { recording: phase === "recording", requesting: phase === "requesting",
    transcribing: phase === "transcribing", error, start, stop, toggle, cancel };
}
