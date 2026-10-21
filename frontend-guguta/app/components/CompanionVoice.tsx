"use client";

import React, { useEffect, useRef } from "react";
import type { VoiceMessage, VoicePhase } from "./useCompanionVoice";

interface Props {
  phase: VoicePhase; connected: boolean; active: boolean; muted: boolean; error: string;
  loginRequired: boolean; loginHref: string; messages: VoiceMessage[];
  playbackBlocked?: boolean; onResumePlayback?: () => void;
  onStart: () => void; onStop: () => void; onMute: () => void; onClose: () => void;
}
export default function CompanionVoice({ phase, connected, active, muted, error, loginRequired, loginHref, messages, playbackBlocked = false, onResumePlayback, onStart, onStop, onMute, onClose }: Props) {
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages]);
  const status = phase === "connecting" ? "Se conectează…" : phase === "stopping" ? "Se încheie conversația…" : phase === "speaking" ? "Guguță îți răspunde" : phase === "thinking" ? "Guguță se gândește…" : connected ? muted ? "Microfon oprit" : "Te ascult…" : phase === "idle" && !active && messages.length > 0 && !error ? "Conversația s-a încheiat." : "Conversație vocală";
  return <section className="companion-chat companion-voice" aria-label="Conversație vocală cu Guguță">
    <div className="companion-voice__header"><p role="status">{status}</p><button type="button" onClick={onClose} aria-label="Închide conversația vocală">×</button></div>
    <p className="companion-voice__disclosure">Voce generată cu AI</p>
    {messages.length > 0 && <div ref={log} className="companion-chat__messages" role="log" aria-label="Transcrierea conversației vocale" aria-live="polite">
      {messages.map(message => <div key={message.id} className={`companion-chat__message companion-chat__message--${message.role}`}><strong className="companion-chat__author">{message.role === "user" ? "Tu" : "Guguță"}</strong><p>{message.content}</p></div>)}
    </div>}
    {error && <p className="companion-chat__error" role="alert">{error}</p>}
    {loginRequired ? <p className="companion-chat__hint"><a href={loginHref}>Autentifică-te</a> pentru a începe conversația vocală.</p> : <div className="companion-voice__controls">
      {connected && playbackBlocked && <button type="button" onClick={onResumePlayback}>Pornește sunetul</button>}
      {connected && <button type="button" onClick={onMute} aria-pressed={muted}>{muted ? "Pornește microfonul" : "Oprește microfonul"}</button>}
      {active ? <button type="button" onClick={onStop} disabled={phase === "stopping"}>Încheie conversația</button> : <button type="button" onClick={onStart}>Începe conversația</button>}
    </div>}
  </section>;
}
