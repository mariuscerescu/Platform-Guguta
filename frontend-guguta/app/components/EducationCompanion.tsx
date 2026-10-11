"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import { useCompanionPosition } from "./useCompanionPosition";
import CompanionChat from "./CompanionChat";
import CompanionVoice from "./CompanionVoice";
import { useCompanionVoice } from "./useCompanionVoice";
import type { GugutaCompanionElement, GugutaContext } from "./guguta-companion";
export type { GugutaContext } from "./guguta-companion";

const CHARACTER_KEY = "guguta.companion.character";
const COLLAPSED_KEY = "guguta.companion.collapsed";
const subjects = ["Limba română", "Matematică", "Științe", "Limba engleză", "Istorie", "Geografie", "Biologie", "Fizică", "Chimie", "Informatică", "Educație civică", "Dezvoltare personală"];
const scripts = new Map<string, Promise<void>>();

function loadWidget(assetBase: string): Promise<void> {
  if (customElements.get("guguta-companion")) return Promise.resolve();
  const url = `${assetBase}/guguta-companion.js?v=direct-voice-composer-mic-20261010`;
  const existing = scripts.get(url);
  if (existing) return existing;
  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.onload = () => {
      if (customElements.get("guguta-companion")) resolve();
      else { scripts.delete(url); script.remove(); reject(new Error("Componenta nu s-a încărcat.")); }
    };
    script.onerror = () => { scripts.delete(url); script.remove(); reject(new Error("Componenta nu s-a încărcat.")); };
    document.head.appendChild(script);
  });
  scripts.set(url, promise);
  return promise;
}

interface Props {
  assetBase: string;
  context: GugutaContext;
  activity?: string;
  idleStatus?: string;
  onCompose?: () => void;
  compact?: boolean;
  sessionId?: string;
  positionKey?: string;
  followPointer?: boolean;
  result?: { correct: number; total: number; percent?: number };
}

/** Companion controls with an attached chat; voice capture starts only on request. */
export default function EducationCompanion({ assetBase, context, activity = "Învățăm împreună", idleStatus = "Alături de tine", onCompose, compact = false, sessionId, positionKey, followPointer = false, result }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const pet = useRef<GugutaCompanionElement | null>(null);
  const settingsButton = useRef<HTMLButtonElement | null>(null);
  const settingsPanel = useRef<HTMLDivElement | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [chatState, setChatState] = useState<"idle" | "running" | "waiting" | "failed">("idle");
  const [chatContainer, setChatContainer] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    const container = document.createElement("div");
    setChatContainer(container);
    return () => container.remove();
  }, []);
  const attachChat = useCallback((node: HTMLDivElement | null) => {
    // Retain the same portal target while dragging moves the mascot to document.body.
    // Drafts, streaming responses and microphone state survive that DOM relocation.
    if (node && chatContainer) node.replaceChildren(chatContainer);
  }, [chatContainer]);
  const platformBase = assetBase.replace(/\/(?:playquiz\/)?guguta-companion\/?$/, "");
  const placement = useCompanionPosition(positionKey ?? `${context.source ?? ""}:${context.notebookId ?? context.quizId ?? context.lessonId ?? "library"}`);
  const attachHost = useCallback((node: HTMLDivElement | null) => {
    host.current = node;
    // A portal transition remounts the host, while the custom element keeps its context and listeners.
    if (node && pet.current) node.replaceChildren(pet.current);
  }, []);
  const compose = useRef(onCompose);
  compose.current = onCompose;
  const [character, setCharacter] = useState("guguta");
  const [collapsed, setCollapsed] = useState(false);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState("");
  const scope = `${context.source ?? ""}:${context.notebookId ?? context.quizId ?? context.lessonId ?? "library"}`;
  const hasResult = result && Number.isFinite(result.correct) && Number.isFinite(result.total) && result.total > 0 && result.correct >= 0 && result.correct <= result.total;
  const resultPercent = hasResult ? Math.round(Math.max(0, Math.min(100,
    Number.isFinite(result.percent) ? result.percent! : result.correct / result.total * 100))) : 0;
  const resultKey = hasResult ? `${scope}:${result.correct}:${result.total}:${resultPercent}` : null;
  const resultActivity = hasResult ? `${result.correct}/${result.total} răspunsuri corecte (${resultPercent}%)` : activity;
  const resultStatus = hasResult ? (resultPercent >= 80 ? "Bravo! Foarte bine!" : resultPercent >= 50 ? "Bine! Continuăm să exersăm." : "Mai exersăm împreună.") : idleStatus;
  const [reactionKey, setReactionKey] = useState<string | null>(null);
  useEffect(() => {
    setReactionKey(resultKey);
    if (!resultKey) return;
    const timer = window.setTimeout(() => setReactionKey(null), 6000);
    return () => window.clearTimeout(timer);
  }, [resultKey]);
  const [manual, setManual] = useState({ scope: "", subjectLabel: "", grade: "" });
  const effectiveContext = {
    ...context,
    ...(!context.subjectLabel && manual.scope === scope && manual.subjectLabel ? { subjectLabel: manual.subjectLabel } : {}),
    ...(!context.grade && manual.scope === scope && manual.grade ? { grade: manual.grade } : {}),
  };
  const contextJson = JSON.stringify(effectiveContext);
  const voice = useCompanionVoice({ apiBase: `${platformBase}/guguta-api`, context: effectiveContext, scope: `${positionKey ?? scope}:${scope}` });
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const controlAction = useRef(0);
  const selectorId = useId();

  useEffect(() => {
    const syncPreferences = () => {
      try {
        setCharacter(localStorage.getItem(CHARACTER_KEY) === "guguta-ai" ? "guguta-ai" : "guguta");
        setCollapsed(localStorage.getItem(COLLAPSED_KEY) === "true");
      } catch { /* Storage can be disabled; the defaults still work. */ }
    };
    syncPreferences();
    window.addEventListener("storage", syncPreferences);
    return () => window.removeEventListener("storage", syncPreferences);
  }, []);

  useEffect(() => { ++controlAction.current; setNotice(""); setSettingsOpen(false); setChatOpen(false); setVoiceOpen(false); setChatState("idle"); }, [scope]);
  useEffect(() => { if (!chatOpen) setChatState("idle"); }, [chatOpen]);
  useEffect(() => {
    if (collapsed) { ++controlAction.current; setSettingsOpen(false); setChatOpen(false); setVoiceOpen(false); setChatState("idle"); void voice.stop(); }
  }, [collapsed, voice.stop]);
  useEffect(() => {
    settingsButton.current?.setAttribute("aria-expanded", String(settingsOpen));
    if (!settingsOpen) return;
    settingsPanel.current?.querySelector("select")?.focus();
    const outside = (event: globalThis.PointerEvent) => {
      const path = event.composedPath();
      if (!path.includes(settingsButton.current as EventTarget) && !path.includes(settingsPanel.current as EventTarget)) setSettingsOpen(false);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setSettingsOpen(false); settingsButton.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("keydown", escape); };
  }, [settingsOpen]);

  useEffect(() => {
    let cancelled = false;
    let element: GugutaCompanionElement | null = null;
    let gear: HTMLButtonElement | null = null;
    setReady(false);
    setLoadError(false);
    const onWrite = () => {
      const action = ++controlAction.current;
      const currentScope = scopeRef.current;
      setVoiceOpen(false); setNotice(""); setSettingsOpen(false);
      // Do not expose the dictation microphone until the voice SDK has released it.
      void voiceRef.current.stop().then(() => {
        if (cancelled || action !== controlAction.current || scopeRef.current !== currentScope) return;
        setChatOpen(open => !open);
        compose.current?.();
      });
    };
    const onVoice = () => {
      ++controlAction.current;
      setSettingsOpen(false);
      if (voiceRef.current.active) {
        void voiceRef.current.stop();
      } else {
        // Unmount dictation before the SDK can acquire the microphone.
        flushSync(() => { setChatOpen(false); setVoiceOpen(true); setNotice(""); });
        void voiceRef.current.start();
      }
    };
    const onCollapse = () => {
      if (!element) return;
      setCollapsed(element.collapsed);
      setNotice("");
      try { localStorage.setItem(COLLAPSED_KEY, String(element.collapsed)); } catch { /* Optional preference. */ }
    };
    const onSettings = () => {
      setSettingsOpen(previous => !previous);
    };
    void loadWidget(assetBase).then(() => {
      if (cancelled || !host.current) return;
      element = document.createElement("guguta-companion");
      element.followPointer = false;
      element.addEventListener("guguta-compose", onWrite);
      element.addEventListener("guguta-voice", onVoice);
      element.addEventListener("guguta-collapse", onCollapse);
      const toolbar = element.shadowRoot?.querySelector(".toolbar");
      if (toolbar) {
        const separator = document.createElement("span");
        separator.className = "separator";
        separator.setAttribute("aria-hidden", "true");
        gear = document.createElement("button");
        gear.type = "button";
        gear.className = "tool settings";
        gear.setAttribute("part", "settings-button");
        gear.setAttribute("aria-label", "Setările personajului");
        gear.setAttribute("aria-expanded", "false");
        gear.setAttribute("aria-haspopup", "dialog");
        gear.title = "Alege Guguță sau GugutaAI";
        gear.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9.5 3-.7 2.1-2 .9-2-.5-2 3.5 1.5 1.6v2.8L2.8 15l2 3.5 2-.5 2 .9.7 2.1h5l.7-2.1 2-.9 2 .5 2-3.5-1.5-1.6v-2.8l1.5-1.6-2-3.5-2 .5-2-.9-.7-2.1z"/><circle cx="12" cy="12" r="3"/></svg>';
        gear.addEventListener("click", onSettings);
        toolbar.append(separator, gear);
        settingsButton.current = gear;
      }
      pet.current = element;
      host.current.replaceChildren(element);
      setReady(true);
    }).catch(() => { if (!cancelled) setLoadError(true); });
    return () => {
      cancelled = true;
      element?.removeEventListener("guguta-compose", onWrite);
      element?.removeEventListener("guguta-voice", onVoice);
      element?.removeEventListener("guguta-collapse", onCollapse);
      gear?.removeEventListener("click", onSettings);
      settingsButton.current = null;
      element?.remove();
      pet.current = null;
    };
  }, [assetBase, retry]);

  useEffect(() => {
    if (!ready || !pet.current) return;
    pet.current.name = character === "guguta-ai" ? "GugutaAI" : "Guguță";
    pet.current.src = `${assetBase}/assets/${character}.webp`;
  }, [ready, character, assetBase]);
  useEffect(() => { if (ready && pet.current) pet.current.collapsed = collapsed; }, [ready, collapsed]);
  useEffect(() => {
    if (!ready || !pet.current) return;
    pet.current.setContext(JSON.parse(contextJson) as GugutaContext);
    const voiceState = voice.phase === "speaking" ? "voice-speaking" : voice.phase === "listening" || voice.phase === "connecting" ? "voice-listening" : voice.phase === "thinking" ? "voice-thinking" : voice.phase === "error" ? "failed" : "idle";
    const voiceStatus = voice.phase === "connecting" ? "Se conectează…" : voice.phase === "stopping" ? "Se încheie conversația…" : voice.phase === "speaking" ? "Îți răspund…" : voice.phase === "thinking" ? "Mă gândesc…" : voice.phase === "listening" ? voice.muted ? "Microfon oprit" : "Te ascult…" : voice.error ? "Încearcă din nou" : resultStatus;
    const status = voiceOpen ? voiceStatus : chatState === "running" ? "Mă gândesc…" : chatState === "waiting" ? "Te ascult…" : chatState === "failed" ? "Încearcă din nou" : resultStatus;
    const reaction = resultKey && reactionKey === resultKey ? (resultPercent >= 80 ? "jumping" : resultPercent >= 50 ? "waving" : "waiting") : "idle";
    pet.current.setStatus({ activity: resultActivity, status, state: placement.dragDirection ?? (voiceOpen && (voice.active || voice.error) ? voiceState : chatState === "idle" ? reaction : chatState) });
    const voiceButton = pet.current.shadowRoot?.querySelector<HTMLButtonElement>('[part="voice-button"]');
    if (voiceButton) {
      const label = voice.active ? "Încheie conversația vocală" : "Începe conversația vocală";
      voiceButton.setAttribute("aria-label", label);
      voiceButton.setAttribute("aria-pressed", String(voice.active));
      voiceButton.title = label;
    }
  }, [ready, contextJson, resultActivity, resultStatus, resultKey, resultPercent, reactionKey, chatState, placement.dragDirection, voiceOpen, voice.phase, voice.muted, voice.active, voice.error]);
  useEffect(() => {
    if (!ready || !pet.current) return;
    // Tracking is page-specific; task and quiz-result animations take priority.
    pet.current.followPointer = followPointer && !placement.dragging && chatState === "idle" && !reactionKey && !voice.active;
  }, [ready, followPointer, placement.dragging, chatState, reactionKey, voice.active]);

  useEffect(() => {
    const element = pet.current;
    if (!ready || !element || !voiceOpen || voice.phase !== "speaking" || collapsed || placement.dragging) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let lastSample = 0;
    let level = 0;
    const reset = () => {
      element.removeAttribute("data-voice-motion");
      element.style.removeProperty("--guguta-voice-lift");
      element.style.removeProperty("--guguta-voice-scale");
      level = 0;
      lastSample = 0;
    };
    const allowed = () => !motion.matches && !element.reducedMotion && !element.collapsed && !document.hidden;
    const tick = (now: number) => {
      frame = 0;
      if (!allowed()) { reset(); return; }
      if (!lastSample || now - lastSample >= 1000 / 15) {
        lastSample = now;
        const target = Math.max(0, Math.min(1, (voice.getOutputVolume() - 0.012) * 4));
        level += (target - level) * 0.35;
        if (level < 0.001) level = 0;
        element.setAttribute("data-voice-motion", "true");
        element.style.setProperty("--guguta-voice-lift", `${(-1.5 * level).toFixed(3)}px`);
        element.style.setProperty("--guguta-voice-scale", (1 + 0.006 * level).toFixed(5));
      }
      frame = requestAnimationFrame(tick);
    };
    const sync = () => {
      if (!allowed()) { cancelAnimationFrame(frame); frame = 0; reset(); }
      else if (!frame) frame = requestAnimationFrame(tick);
    };
    const observer = new MutationObserver(sync);
    observer.observe(element, { attributes: true, attributeFilter: ["reduced-motion", "collapsed"] });
    motion.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    sync();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
      reset();
    };
  }, [ready, voiceOpen, voice.phase, voice.getOutputVolume, collapsed, placement.dragging]);

  function chooseCharacter(value: string) {
    setCharacter(value);
    try { localStorage.setItem(CHARACTER_KEY, value); } catch { /* Optional preference. */ }
  }

  const content = (
    <aside ref={placement.setContainer} style={placement.style} onPointerDown={placement.onPointerDown} className={`education-companion${compact ? " education-companion--compact" : ""}${placement.floating ? " education-companion--floating" : ""}${placement.dragging ? " education-companion--dragging" : ""}`} data-collapsed={collapsed} data-chat-open={chatOpen || voiceOpen} aria-label="Companionul tău">
      <div className="education-companion__avatar">
      <div className="education-companion__widget" ref={attachHost} />
      {settingsOpen && !collapsed && <div ref={settingsPanel} className="education-companion__settings" role="dialog" aria-label="Setările personajului">
        <label htmlFor={selectorId}>Personaj</label>
        <select id={selectorId} value={character} onChange={event => { chooseCharacter(event.target.value); setSettingsOpen(false); settingsButton.current?.focus(); }}>
          <option value="guguta">Guguță</option>
          <option value="guguta-ai">GugutaAI</option>
        </select>
        <button type="button" onClick={() => { setSettingsOpen(false); settingsButton.current?.focus(); }} aria-label="Închide setările">×</button>
      </div>}
      </div>
      <div className="education-companion__chat-anchor" ref={attachChat} hidden={!chatOpen && !voiceOpen} />
      {!ready && <p className="education-companion__notice" role="status">
        {loadError ? <>Personajul nu s-a încărcat. <button type="button" onClick={() => setRetry(value => value + 1)}>Reîncearcă</button></> : "Se încarcă Guguță…"}
      </p>}
      {!collapsed && !context.subjectLabel && (context.notebookId || context.quizId) && <details className="education-companion__context" key={scope}>
        <summary>Disciplina și clasa</summary>
        <label>Disciplina
          <select value={manual.scope === scope ? manual.subjectLabel : ""} onChange={event => setManual(previous => ({ scope, grade: previous.scope === scope ? previous.grade : "", subjectLabel: event.target.value }))}>
            <option value="">Alege disciplina</option>
            {subjects.map(subject => <option key={subject}>{subject}</option>)}
          </select>
        </label>
        <label>Clasa
          <select value={manual.scope === scope ? manual.grade : ""} onChange={event => setManual(previous => ({ scope, subjectLabel: previous.scope === scope ? previous.subjectLabel : "", grade: event.target.value }))}>
            <option value="">Alege clasa</option>
            {Array.from({ length: 12 }, (_, index) => String(index + 1)).map(grade => <option key={grade}>{grade}</option>)}
          </select>
        </label>
      </details>}
      {notice && <div className="education-companion__notice" role="status">
        <span>{notice}</span>
        <button type="button" onClick={() => setNotice("")} aria-label="Închide mesajul">×</button>
      </div>}
    </aside>
  );
  return <>
    {placement.floating ? createPortal(content, document.body) : content}
    {voiceOpen && chatContainer && createPortal(<CompanionVoice
      {...voice}
      loginHref={`${platformBase}/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}
      onStart={() => { void voice.start(); }}
      onStop={() => { void voice.stop(); }}
      onMute={voice.toggleMuted}
      onClose={() => { void voice.stop(); setVoiceOpen(false); pet.current?.shadowRoot?.querySelector<HTMLButtonElement>('[part="voice-button"]')?.focus(); }}
    />, chatContainer)}
    {chatOpen && chatContainer && createPortal(<CompanionChat
      key={scope}
      context={effectiveContext}
      sessionId={sessionId}
      apiBase={`${platformBase}/guguta-api`}
      loginHref={`${platformBase}/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}
      onStateChange={setChatState}
      onClose={() => {
        setChatOpen(false); setChatState("idle");
        pet.current?.shadowRoot?.querySelector<HTMLButtonElement>('[part="compose-button"]')?.focus();
      }}
    />, chatContainer)}
  </>;
}
