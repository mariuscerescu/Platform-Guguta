export type GugutaState = 'idle' | 'running-right' | 'running-left' | 'waving' | 'jumping' | 'failed' | 'waiting' | 'running' | 'review' | 'voice-speaking' | 'voice-listening' | 'voice-thinking';
export interface GugutaContext {
  source?: string;
  subjectId?: string;
  subjectLabel?: string;
  grade?: number | string;
  notebookId?: string;
  quizId?: string;
  lessonId?: string;
  lessonTitle?: string;
  locale?: string;
  /** Host-side learning context; authorized and resolved by the voice backend. */
  selectedSourceIds?: string[];
  activeCard?: { question: string };
  activeQuestion?: { prompt: string; options?: string[]; questionType?: string };
}
export interface GugutaActionDetail {
  readonly name: string;
  readonly collapsed: boolean;
  readonly context: Readonly<GugutaContext>;
}
export interface GugutaVoiceDetail extends GugutaActionDetail {
  readonly mode: 'conversation';
}
export interface GugutaCompanionElement extends HTMLElement {
  src: string;
  name: string;
  activity: string;
  status: string;
  state: GugutaState;
  collapsed: boolean;
  followPointer: boolean;
  reducedMotion: boolean;
  context: GugutaContext | null;
  setContext(context: GugutaContext | null): this;
  setStatus(update: { activity?: string; status?: string; state?: GugutaState }): this;
  setState(state: GugutaState): this;
}
declare global {
  interface HTMLElementTagNameMap { 'guguta-companion': GugutaCompanionElement; }
  interface HTMLElementEventMap {
    'guguta-compose': CustomEvent<GugutaActionDetail>;
    'guguta-voice': CustomEvent<GugutaVoiceDetail>;
    'guguta-collapse': CustomEvent<GugutaActionDetail>;
    'guguta-contextchange': CustomEvent<{readonly name: string; readonly context: Readonly<GugutaContext>}>;
  }
}
