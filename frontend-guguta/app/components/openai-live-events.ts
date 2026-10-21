import type { VoiceMessage } from "./useElevenLabsVoice";

export interface LiveTranscriptFragment {
  id: string;
  role: VoiceMessage["role"];
  delta: string;
  startMs: number;
  endMs: number;
  order: number;
}

/** GPT-Live has simultaneous speaker streams, not completed conversational turns. */
export function liveTranscriptMessages(fragments: LiveTranscriptFragment[]): VoiceMessage[] {
  const groups: Array<VoiceMessage & { start: number; end: number }> = [];
  for (const role of ["user", "assistant"] as const) {
    let current: typeof groups[number] | undefined;
    const ordered = fragments.filter(fragment => fragment.role === role)
      .sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs || a.order - b.order);
    for (const fragment of ordered) {
      if (!current || fragment.startMs - current.end > 1500) {
        current = { id: `${role}:${fragment.id}`, role, content: "", start: fragment.startMs, end: fragment.endMs };
        groups.push(current);
      }
      // Do not insert spaces, remove repeated words, or trim individual deltas.
      current.content += fragment.delta;
      current.end = Math.max(current.end, fragment.endMs);
    }
  }
  return groups.sort((a, b) => a.start - b.start).slice(-40)
    .map(({ id, role, content }) => ({ id, role, content }));
}

/** Under 450 UTF-8 bytes also stays below the API's 500-token append limit. */
export function liveContextChunks(text: string): string[] {
  const encoder = new TextEncoder();
  const chunks: string[] = [];
  let chunk = "";
  let bytes = 0;
  for (const character of text) {
    const size = encoder.encode(character).byteLength;
    if (bytes + size > 450) { chunks.push(chunk); chunk = ""; bytes = 0; }
    chunk += character;
    bytes += size;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}
