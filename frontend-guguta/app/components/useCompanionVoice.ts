"use client";

import type { GugutaContext } from "./guguta-companion";
import { useElevenLabsVoice } from "./useElevenLabsVoice";
import { useOpenAILiveVoice } from "./useOpenAILiveVoice";

export type { VoiceMessage, VoicePhase } from "./useElevenLabsVoice";
export type VoiceProvider = "elevenlabs" | "openai";
interface Options { apiBase: string; context: GugutaContext; scope: string; provider?: VoiceProvider }

export function useCompanionVoice({ provider = "elevenlabs", ...options }: Options) {
  // Only an explicit start acquires a microphone. Scope changes cancel old calls.
  const scoped = { ...options, scope: `${options.scope}:${provider}` };
  const elevenlabs = useElevenLabsVoice(scoped);
  const openai = useOpenAILiveVoice(scoped);
  return provider === "openai" ? openai : { ...elevenlabs, playbackBlocked: false, resumePlayback: undefined };
}
