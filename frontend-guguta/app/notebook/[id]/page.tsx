"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError, getCsrf, Note, Notebook, Source } from "../../../lib/api";
import {
  SHOW_ANSWER_REFERENCES,
  withoutReferenceMarkers,
} from "../../../lib/features";
import SourceUploader from "../../components/SourceUploader";
import {
  AudioIcon,
  CardsIcon,
  ChatIcon,
  MaterialsIcon,
  PencilIcon,
  PanelToggleIcon,
  PlusIcon,
  QuizIcon,
  ShareIcon,
  StudioIcon,
  TrashIcon,
} from "../../components/UiIcons";
import { withBase, API_BASE } from "../../../lib/paths";

interface ChatMessage {
  id: string;
  seq: number;
  role: string;
  content: string;
  context_revision: number;
}

interface Citation {
  display_name: string;
  locator: Record<string, unknown>;
  source_removed: boolean;
}

const CHAT_STREAM_TIMEOUT_MS = 310_000;

interface ChatSession {
  id: string;
  title?: string | null;
  created_revision: number;
}

interface AudioOverview {
  id: string;
  notebook_id: string;
  format: "brief" | "deep_dive";
  selected_source_ids: string[];
  status: "queued" | "generating_script" | "synthesizing" | "ready" | "failed";
  title?: string | null;
  duration_seconds?: number | null;
  error_detail?: string | null;
  job_id?: string | null;
}

interface FlashcardEvidence {
  source_id: string;
  chunk_id: string;
  source_name: string;
  locator: Record<string, unknown>;
}

interface Flashcard {
  id: string;
  front: string;
  back: string;
  concept?: string | null;
  evidence: FlashcardEvidence[];
}

interface StudySession {
  id: string;
  mode: "all" | "same" | "missed";
  card_order: string[];
  current_index: number;
  results: Record<string, "got_it" | "missed">;
  completed_at?: string | null;
}

interface FlashcardDeck {
  id: string;
  quantity: "fewer" | "standard" | "more";
  difficulty: "easy" | "medium" | "hard";
  selected_source_ids: string[];
  status: "queued" | "generating" | "ready" | "failed";
  title?: string | null;
  error_detail?: string | null;
  card_count: number;
  cards?: Flashcard[];
  active_session?: StudySession | null;
}

type QuizQuestionType = "multiple_choice" | "multiple_select" | "fill_in_blank" | "short_answer";
interface QuizQuestion { id:string; position:number; question_type:QuizQuestionType; prompt:string; hint:string; concepts:string[]; options:{id:string;text:string}[]; version:number; }
interface QuizAttempt { id:string; current_index:number; question_order:string[]; answers:Record<string,{response:string|string[];status:"correct"|"partial"|"incorrect";feedback:string;correct_answer:string|string[];hint_used:boolean}>; completed_at?:string|null; }
interface QuizArtifact { id:string; quantity:"fewer"|"standard"|"more"; difficulty:"easy"|"medium"|"hard"; question_types:QuizQuestionType[]; selected_source_ids:string[]; instructions?:string|null; status:"queued"|"generating"|"ready"|"failed"; title?:string|null; error_detail?:string|null; question_count:number; questions?:QuizQuestion[]; active_attempt?:QuizAttempt|null; }
interface ShareItem { id:string; title:string; status:"active"|"revoked"|"expired"; material_count:number; created_at:string; expires_at?:string|null; }
interface CreatedShare { share_id:string; token:string; code:string; material_count:number; expires_at?:string|null; }
type MobilePanel = "materials" | "chat" | "studio";

/**
 * Răspunsul asistentului așa cum se afișează. Când referințele sunt oprite
 * (`lib/features.ts`), marcajele `[1]` se scot doar de aici — conținutul salvat
 * în bază rămâne neatins, iar întrebarea utilizatorului nu se atinge niciodată.
 */
function answerText(text: string): string {
  return SHOW_ANSWER_REFERENCES ? text : withoutReferenceMarkers(text);
}

export default function NotebookPage() {
  const params = useParams<{ id: string }>();
  const nbId = params.id;

  const [nb, setNb] = useState<Notebook | null>(null);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [audioOverviews, setAudioOverviews] = useState<AudioOverview[] | null>(null);
  const [flashcardDecks, setFlashcardDecks] = useState<FlashcardDeck[] | null>(null);
  const [quizzes, setQuizzes] = useState<QuizArtifact[] | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<string, Citation[]>>({});
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [srcCollapsed, setSrcCollapsed] = useState(false);
  const [studioCollapsed, setStudioCollapsed] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [elapsed, setElapsed] = useState(0);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [audioModalOpen, setAudioModalOpen] = useState(false);
  const [audioFormat, setAudioFormat] = useState<"brief" | "deep_dive">("brief");
  const [audioSourceIds, setAudioSourceIds] = useState<string[]>([]);
  const [audioSubmitting, setAudioSubmitting] = useState(false);
  const [deletingAudioId, setDeletingAudioId] = useState<string | null>(null);
  const [flashcardModalOpen, setFlashcardModalOpen] = useState(false);
  const [flashcardQuantity, setFlashcardQuantity] = useState<"fewer" | "standard" | "more">("standard");
  const [flashcardDifficulty, setFlashcardDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [flashcardSourceIds, setFlashcardSourceIds] = useState<string[]>([]);
  const [flashcardInstructions, setFlashcardInstructions] = useState("");
  const [flashcardSubmitting, setFlashcardSubmitting] = useState(false);
  const [deletingDeckId, setDeletingDeckId] = useState<string | null>(null);
  const [activeDeck, setActiveDeck] = useState<FlashcardDeck | null>(null);
  const [studySession, setStudySession] = useState<StudySession | null>(null);
  const [cardFlipped, setCardFlipped] = useState(false);
  const [cardExplanation, setCardExplanation] = useState<string | null>(null);
  const [explainingCard, setExplainingCard] = useState(false);
  const [quizModalOpen,setQuizModalOpen]=useState(false);
  const [quizQuantity,setQuizQuantity]=useState<"fewer"|"standard"|"more">("standard");
  const [quizDifficulty,setQuizDifficulty]=useState<"easy"|"medium"|"hard">("medium");
  const [quizTypes,setQuizTypes]=useState<QuizQuestionType[]>(["fill_in_blank","multiple_choice","multiple_select","short_answer"]);
  const [quizSourceIds,setQuizSourceIds]=useState<string[]>([]);
  const [quizInstructions,setQuizInstructions]=useState("");
  const [quizSubmitting,setQuizSubmitting]=useState(false);
  const [activeQuiz,setActiveQuiz]=useState<QuizArtifact|null>(null);
  const [quizAttempt,setQuizAttempt]=useState<QuizAttempt|null>(null);
  const [quizResponse,setQuizResponse]=useState<string|string[]>("");
  const [quizHint,setQuizHint]=useState(false);
  const [quizExplanation,setQuizExplanation]=useState<string|null>(null);
  const [quizBusy,setQuizBusy]=useState(false);
  const [renamingTitle,setRenamingTitle]=useState(false);
  const [titleDraft,setTitleDraft]=useState("");
  const [titleSaving,setTitleSaving]=useState(false);
  const [shareModalOpen,setShareModalOpen]=useState(false);
  const [shareSourceIds,setShareSourceIds]=useState<string[]>([]);
  const [shareTitle,setShareTitle]=useState("");
  const [shareDescription,setShareDescription]=useState("");
  const [shareExpiry,setShareExpiry]=useState<"1"|"7"|"30"|"90"|"never">("30");
  const [shareSubmitting,setShareSubmitting]=useState(false);
  const [createdShare,setCreatedShare]=useState<CreatedShare|null>(null);
  const [shares,setShares]=useState<ShareItem[]>([]);
  const [copiedShare,setCopiedShare]=useState<"link"|"code"|null>(null);
  useEffect(() => {
    if (!sending) {
      setElapsed(0);
      return;
    }
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [sending]);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Oprește a doua creare de sesiune dacă efectul de încărcare rulează de două
  // ori (remontare în dezvoltare): un carnet nou primește o singură conversație.
  const sessionCreationRef = useRef(false);
  // mirror for loadMessages without adding `citations` to its deps —
  // otherwise setCitations recreates loadMessages → infinite re-render loop
  const citationsRef = useRef<Record<string, Citation[]>>({});
  useEffect(() => {
    citationsRef.current = citations;
  }, [citations]);

  const loadAll = useCallback(async () => {
    try {
      const nbData = await api<Notebook>("GET", `/api/v1/notebooks/${nbId}`);
      setNb(nbData);
      const srcs = await api<Source[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sources`,
      );
      setSources(srcs);
      const nts = await api<Note[]>(`GET`, `/api/v1/notebooks/${nbId}/notes`);
      setNotes(nts);
      const overviews = await api<AudioOverview[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/audio-overviews`,
      );
      setAudioOverviews(overviews);
      const decks = await api<FlashcardDeck[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/flashcard-decks`,
      );
      setFlashcardDecks(decks);
      setQuizzes(await api<QuizArtifact[]>("GET", `/api/v1/notebooks/${nbId}/quizzes`));
      const sess = await api<ChatSession[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sessions`,
      );
      setSessions(sess);
      if (sess.length > 0) {
        if (sessionId === null) setSessionId(sess[0].id);
      } else if (!sessionCreationRef.current) {
        // Conversația există întotdeauna: un carnet nou primește automat una,
        // ca panoul din centru să nu rămână gol până apasă cineva un buton.
        sessionCreationRef.current = true;
        const created = await api<ChatSession>(
          "POST",
          `/api/v1/notebooks/${nbId}/sessions`,
          {},
        );
        setSessions([created]);
        setSessionId(created.id);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("Carnetul nu există sau nu îți aparține.");
      } else {
        setError((err as Error).message);
      }
    }
  }, [nbId, sessionId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // Materialul tocmai urcat intră în listă imediat, în același render în care
  // linia lui temporară dispare — fără dubluri și fără clipire între ele.
  const addUploadedSource = useCallback((source: Source) => {
    setSources((prev) => (prev ? [...prev, source] : [source]));
  }, []);

  const loadMessages = useCallback(async () => {
    if (sessionId === null) return;
    try {
      const msgs = await api<ChatMessage[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages`,
      );
      setMessages(msgs);
      // Referințele oprite: citările rămân în bază, dar nu le mai cerem de N
      // ori la fiecare încărcare. Codul de mai jos e intact pentru reluare.
      if (!SHOW_ANSWER_REFERENCES) return;
      const known = citationsRef.current;
      for (const m of msgs) {
        if (m.role !== "assistant" || known[m.id]) continue;
        try {
          const cites = await api<Citation[]>(
            "GET",
            `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages/${m.id}/citations`,
          );
          setCitations((prev) => ({ ...prev, [m.id]: cites }));
        } catch {
          setCitations((prev) => ({ ...prev, [m.id]: [] }));
        }
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [nbId, sessionId]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  // Materialele în procesare se reîmprospătează singure: cercul de lângă
  // fișier se oprește fără intervenția utilizatorului când workerul termină.
  const hasProcessing =
    (sources?.some((s) => s.status === "processing") ?? false) ||
    (audioOverviews?.some((item) =>
      ["queued", "generating_script", "synthesizing"].includes(item.status)
    ) ?? false) ||
    (flashcardDecks?.some((item) => ["queued", "generating"].includes(item.status)) ?? false) ||
    (quizzes?.some((item) => ["queued", "generating"].includes(item.status)) ?? false);
  useEffect(() => {
    if (!hasProcessing) return;
    const t = setInterval(() => {
      void loadAll();
    }, 2000);
    return () => clearInterval(t);
  }, [hasProcessing, loadAll]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send() {
    if (sending) return;
    const content = draft.trim();
    if (!content || sessionId === null) return;
    setSending(true);
    setError(null);
    // optimist: mesajul utilizatorului apare instant; serverul îl salvează
    // oricum în faza 1, deci rămâne vizibil și pe eșec (A26)
    setMessages((prev) => [
      ...prev,
      {
        id: `tmp-u-${crypto.randomUUID()}`,
        seq: 0,
        role: "user",
        content,
        context_revision: 0,
      },
    ]);
    setDraft("");
    // assistant live: textul se construiește token cu token (SSE)
    setStreaming("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), CHAT_STREAM_TIMEOUT_MS);
    try {
      const csrf = getCsrf();
      const res = await fetch(
        `${API_BASE}/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages/stream`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            ...(csrf ? { "X-Guguta-CSRF": csrf } : {}),
          },
          body: JSON.stringify({ content }),
          signal: controller.signal,
        },
      );
      if (!res.ok || !res.body) {
        const d = (await res.json().catch(() => ({}))) as {
          code?: string;
          message?: string;
        };
        throw new ApiError(
          res.status,
          d.code ?? "error",
          d.message ?? "Generarea a eșuat.",
        );
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let done = false;
      while (!done) {
        const { value, done: rDone } = await reader.read();
        if (rDone) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            const ev = JSON.parse(line.slice(6)) as {
              event: string;
              text?: string;
              message?: string;
            };
            if (ev.event === "token" && ev.text) {
              setStreaming((prev) => (prev ?? "") + ev.text);
            } else if (ev.event === "done") {
              done = true;
            } else if (ev.event === "error") {
              throw new ApiError(502, "provider", ev.message ?? "Eroare AI.");
            }
            // „ping" și „user_saved" sunt ignorate (optimist deja afișat)
          } catch (e) {
            if (e instanceof ApiError) throw e;
            // JSON parțial între chunkuri — ignorat, bufferul continuă
          }
        }
      }
      await loadMessages();
    } catch (err) {
      const message =
        err instanceof DOMException && err.name === "AbortError"
          ? "Generarea durează prea mult. Reîncearcă peste câteva momente."
          : (err as Error).message;
      setError(message);
      await loadMessages().catch(() => undefined);
    } finally {
      window.clearTimeout(timeout);
      setStreaming(null);
      setSending(false);
    }
  }

  async function newSession() {
    try {
      const s = await api<ChatSession>(
        "POST",
        `/api/v1/notebooks/${nbId}/sessions`,
        {},
      );
      setSessions((prev) => [s, ...prev]);
      setSessionId(s.id);
      setMessages([]);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  // Adăugarea materialelor (file manager → upload → procesare) este izolată
  // în SourceUploader; pagina doar reîncarcă lista când ceva s-a schimbat.

  // Redenumirea, arhivarea și ștergerea carnetului se fac din meniul cardului
  // (app/components/NotebookMenu.tsx), în lista de carnete.

  async function openShareModal() {
    const ready = (sources ?? []).filter((s) => s.status === "ready");
    if (!ready.length) { setError("Niciun material gata pentru partajare."); return; }
    setShareSourceIds(ready.map((s)=>s.id)); setShareTitle(nb?.title??""); setShareDescription("");
    setShareExpiry("30"); setCreatedShare(null); setCopiedShare(null); setShareModalOpen(true);
    try { setShares(await api<ShareItem[]>("GET",`/api/v1/notebooks/${nbId}/shares`)); } catch(err){setError((err as Error).message);}
  }

  async function createShare() {
    if (!shareSourceIds.length || shareSubmitting) return;
    setShareSubmitting(true); setError(null);
    try {
      const share = await api<CreatedShare>(
        "POST",
        `/api/v1/notebooks/${nbId}/shares`,
        { source_ids: shareSourceIds, title: shareTitle.trim()||nb?.title,
          description:shareDescription.trim()||null,
          expires_in_days:shareExpiry==="never"?null:Number(shareExpiry) },
      );
      setCreatedShare(share);
      setShares(await api<ShareItem[]>("GET",`/api/v1/notebooks/${nbId}/shares`));
    } catch (err) {
      setError((err as Error).message);
    } finally { setShareSubmitting(false); }
  }

  async function copyShare(value:string,kind:"link"|"code") {
    await navigator.clipboard.writeText(value); setCopiedShare(kind);
    window.setTimeout(()=>setCopiedShare(null),1800);
  }

  async function revokeShare(shareId:string) {
    if(!window.confirm("Revoci acest cod? Copiile deja importate vor rămâne disponibile.")) return;
    try { await api("POST",`/api/v1/notebooks/${nbId}/shares/${shareId}/revoke`,{}); setShares(v=>v.map(s=>s.id===shareId?{...s,status:"revoked"}:s)); } catch(err){setError((err as Error).message);}
  }

  async function removeSource(id: string) {
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}/sources/${id}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function retrySource(id: string) {
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/sources/${id}/retry`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  // Notițele nu se mai adaugă din Studio (decizie de produs); cele existente
  // rămân vizibile și pot fi șterse. Ruta POST /notes din API rămâne intactă.
  async function removeNote(id: string) {
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}/notes/${id}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function openAudioModal() {
    const readyIds = (sources ?? [])
      .filter((source) => source.status === "ready")
      .map((source) => source.id);
    setAudioSourceIds(readyIds);
    setAudioFormat("brief");
    setAudioModalOpen(true);
  }

  function toggleAudioSource(sourceId: string) {
    setAudioSourceIds((current) =>
      current.includes(sourceId)
        ? current.filter((id) => id !== sourceId)
        : [...current, sourceId],
    );
  }

  async function createAudioOverview() {
    if (audioSubmitting || audioSourceIds.length === 0) return;
    setAudioSubmitting(true);
    setError(null);
    try {
      const created = await api<AudioOverview>(
        "POST",
        `/api/v1/notebooks/${nbId}/audio-overviews`,
        { format: audioFormat, source_ids: audioSourceIds },
      );
      setAudioOverviews((current) => [created, ...(current ?? [])]);
      setAudioModalOpen(false);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAudioSubmitting(false);
    }
  }

  async function retryAudioOverview(overviewId: string) {
    try {
      await api(
        "POST",
        `/api/v1/notebooks/${nbId}/audio-overviews/${overviewId}/retry`,
      );
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function removeAudioOverview(overview: AudioOverview) {
    if (
      deletingAudioId !== null ||
      !window.confirm(
        `Ștergi „${overview.title || "Rezumat audio"}”? Fișierul audio nu va mai putea fi recuperat.`,
      )
    ) {
      return;
    }
    setDeletingAudioId(overview.id);
    setError(null);
    try {
      await api(
        "DELETE",
        `/api/v1/notebooks/${nbId}/audio-overviews/${overview.id}`,
      );
      setAudioOverviews((current) =>
        current?.filter((item) => item.id !== overview.id) ?? [],
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingAudioId(null);
    }
  }

  function openFlashcardModal() {
    setFlashcardSourceIds((sources ?? []).filter((source) => source.status === "ready").map((source) => source.id));
    setFlashcardQuantity("standard");
    setFlashcardDifficulty("medium");
    setFlashcardInstructions("");
    setFlashcardModalOpen(true);
  }

  function toggleFlashcardSource(sourceId: string) {
    setFlashcardSourceIds((current) => current.includes(sourceId)
      ? current.filter((id) => id !== sourceId)
      : [...current, sourceId]);
  }

  async function createFlashcardDeck() {
    if (flashcardSubmitting || flashcardSourceIds.length === 0) return;
    setFlashcardSubmitting(true);
    setError(null);
    try {
      const created = await api<FlashcardDeck>("POST", `/api/v1/notebooks/${nbId}/flashcard-decks`, {
        source_ids: flashcardSourceIds,
        quantity: flashcardQuantity,
        difficulty: flashcardDifficulty,
        instructions: flashcardInstructions.trim() || null,
      });
      setFlashcardDecks((current) => [created, ...(current ?? [])]);
      setFlashcardModalOpen(false);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setFlashcardSubmitting(false);
    }
  }

  async function removeFlashcardDeck(deck: FlashcardDeck) {
    if (deletingDeckId || !window.confirm(`Ștergi „${deck.title || "Flashcards"}”? Progresul de studiu va fi șters.`)) return;
    setDeletingDeckId(deck.id);
    try {
      await api("DELETE", `/api/v1/notebooks/${nbId}/flashcard-decks/${deck.id}`);
      setFlashcardDecks((current) => current?.filter((item) => item.id !== deck.id) ?? []);
      if (activeDeck?.id === deck.id) setActiveDeck(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeletingDeckId(null);
    }
  }

  async function retryFlashcardDeck(deckId: string) {
    try {
      await api("POST", `/api/v1/notebooks/${nbId}/flashcard-decks/${deckId}/retry`, {});
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function openDeck(deckId: string, mode: "all" | "same" | "missed" = "all") {
    try {
      const deck = await api<FlashcardDeck>("GET", `/api/v1/notebooks/${nbId}/flashcard-decks/${deckId}`);
      let session = mode === "all" ? deck.active_session ?? null : null;
      if (!session) {
        session = await api<StudySession>("POST", `/api/v1/notebooks/${nbId}/flashcard-decks/${deckId}/sessions`, { mode });
      }
      setActiveDeck(deck);
      setStudySession(session);
      setCardFlipped(false);
      setCardExplanation(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function persistStudy(next: StudySession, completed = false) {
    if (!activeDeck) return;
    const saved = await api<StudySession>(
      "PATCH",
      `/api/v1/notebooks/${nbId}/flashcard-decks/${activeDeck.id}/sessions/${next.id}`,
      { current_index: next.current_index, results: next.results, card_order: next.card_order, completed },
    );
    setStudySession(saved);
  }

  async function assessCard(result: "got_it" | "missed") {
    if (!studySession) return;
    const cardId = studySession.card_order[studySession.current_index];
    const isLast = studySession.current_index >= studySession.card_order.length - 1;
    const next = { ...studySession, results: { ...studySession.results, [cardId]: result },
      current_index: isLast ? studySession.current_index : studySession.current_index + 1 };
    setCardFlipped(false);
    setCardExplanation(null);
    await persistStudy(next, isLast);
  }

  async function shuffleStudy() {
    if (!studySession) return;
    const order = [...studySession.card_order];
    for (let i = order.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    setCardFlipped(false);
    setCardExplanation(null);
    await persistStudy({ ...studySession, card_order: order, current_index: 0 });
  }

  async function explainCard(cardId: string) {
    if (!activeDeck || explainingCard) return;
    setExplainingCard(true);
    try {
      const result = await api<{ explanation: string }>(
        "POST",
        `/api/v1/notebooks/${nbId}/flashcard-decks/${activeDeck.id}/cards/${cardId}/explain`,
        {},
      );
      setCardExplanation(result.explanation);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExplainingCard(false);
    }
  }

  async function removeFlashcard(cardId: string) {
    if (!activeDeck || !window.confirm("Ștergi acest cartonaș?")) return;
    await api("DELETE", `/api/v1/notebooks/${nbId}/flashcard-decks/${activeDeck.id}/cards/${cardId}`);
    const deck = await api<FlashcardDeck>("GET", `/api/v1/notebooks/${nbId}/flashcard-decks/${activeDeck.id}`);
    setActiveDeck(deck);
    if (studySession) {
      const order = studySession.card_order.filter((id) => id !== cardId);
      await persistStudy({ ...studySession, card_order: order, current_index: Math.min(studySession.current_index, Math.max(0, order.length - 1)) });
    }
  }

  function openQuizModal() {
    setQuizSourceIds((sources ?? []).filter((source) => source.status === "ready").map((source) => source.id));
    setQuizQuantity("standard"); setQuizDifficulty("medium");
    setQuizTypes(["fill_in_blank","multiple_choice","multiple_select","short_answer"]);
    setQuizInstructions(""); setQuizModalOpen(true);
  }
  async function createQuiz() {
    if (quizSubmitting || !quizSourceIds.length || !quizTypes.length) return;
    setQuizSubmitting(true);
    try {
      const created=await api<QuizArtifact>("POST",`/api/v1/notebooks/${nbId}/quizzes`,{source_ids:quizSourceIds,quantity:quizQuantity,difficulty:quizDifficulty,question_types:quizTypes,instructions:quizInstructions.trim()||null});
      setQuizzes((current)=>[created,...(current??[])]); setQuizModalOpen(false); await loadAll();
    } catch(err) { setError((err as Error).message); } finally { setQuizSubmitting(false); }
  }
  async function removeQuiz(quiz: QuizArtifact) {
    if (!window.confirm(`Ștergi „${quiz.title || "Quiz"}”? Încercările vor fi șterse.`)) return;
    try { await api("DELETE",`/api/v1/notebooks/${nbId}/quizzes/${quiz.id}`); setQuizzes((v)=>v?.filter((x)=>x.id!==quiz.id)??[]); if(activeQuiz?.id===quiz.id){setActiveQuiz(null);setQuizAttempt(null);} } catch(err){setError((err as Error).message);}
  }
  async function retryQuiz(id:string) { try { await api("POST",`/api/v1/notebooks/${nbId}/quizzes/${id}/retry`,{}); await loadAll(); } catch(err){setError((err as Error).message);} }
  async function openQuiz(id:string, retake=false) {
    try {
      const quiz=await api<QuizArtifact>("GET",`/api/v1/notebooks/${nbId}/quizzes/${id}`);
      const attempt=!retake&&quiz.active_attempt?quiz.active_attempt:await api<QuizAttempt>("POST",`/api/v1/notebooks/${nbId}/quizzes/${id}/attempts`,{});
      setActiveQuiz(quiz);setQuizAttempt(attempt);setQuizResponse("");setQuizHint(false);setQuizExplanation(null);
    } catch(err){setError((err as Error).message);}
  }
  async function submitQuizAnswer() {
    if(!activeQuiz||!quizAttempt||quizBusy) return;
    const question=activeQuiz.questions?.find((q)=>q.id===quizAttempt.question_order[quizAttempt.current_index]);
    if(!question||(typeof quizResponse==="string"?!quizResponse.trim():!quizResponse.length)) return;
    setQuizBusy(true);
    try {
      const data=await api<{attempt:QuizAttempt}>("POST",`/api/v1/notebooks/${nbId}/quizzes/${activeQuiz.id}/attempts/${quizAttempt.id}/answers`,{question_id:question.id,response:quizResponse,hint_used:quizHint});
      setQuizAttempt(data.attempt);
    } catch(err){setError((err as Error).message);} finally {setQuizBusy(false);}
  }
  function moveQuiz(delta:number) {
    if(!quizAttempt) return; const index=Math.max(0,Math.min(quizAttempt.question_order.length-1,quizAttempt.current_index+delta));
    setQuizAttempt({...quizAttempt,current_index:index});setQuizResponse("");setQuizHint(false);setQuizExplanation(null);
  }
  async function explainQuizQuestion() {
    if(!activeQuiz||!quizAttempt||quizBusy) return; const q=activeQuiz.questions?.find((v)=>v.id===quizAttempt.question_order[quizAttempt.current_index]); if(!q)return;
    setQuizBusy(true);try{const value=await api<{explanation:string}>("POST",`/api/v1/notebooks/${nbId}/quizzes/${activeQuiz.id}/questions/${q.id}/explain`,{response:quizAttempt.answers[q.id]?.response??quizResponse});setQuizExplanation(value.explanation);}catch(err){setError((err as Error).message);}finally{setQuizBusy(false);}
  }

  useEffect(() => {
    if (!activeDeck || !studySession || studySession.completed_at) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === " ") { event.preventDefault(); setCardFlipped((value) => !value); }
      if (event.key === "ArrowLeft") { setCardFlipped(false); setStudySession((value) => value ? { ...value, current_index: Math.max(0, value.current_index - 1) } : value); }
      if (event.key === "ArrowRight") { setCardFlipped(false); setStudySession((value) => value ? { ...value, current_index: Math.min(value.card_order.length - 1, value.current_index + 1) } : value); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeDeck, studySession]);

  const currentStudyCard = activeDeck?.cards?.find(
    (card) => card.id === studySession?.card_order[studySession.current_index],
  );
  const gotItCount = Object.values(studySession?.results ?? {}).filter((value) => value === "got_it").length;
  const missedCount = Object.values(studySession?.results ?? {}).filter((value) => value === "missed").length;
  const currentQuizQuestion=activeQuiz?.questions?.find((q)=>q.id===quizAttempt?.question_order[quizAttempt.current_index]);
  const currentQuizAnswer=currentQuizQuestion&&quizAttempt?.answers[currentQuizQuestion.id];

  function startTitleRename() {
    setTitleDraft(nb?.title ?? "");
    setRenamingTitle(true);
  }

  async function saveNotebookTitle() {
    const nextTitle = titleDraft.trim();
    if (!nb || !nextTitle || titleSaving) return;
    if (nextTitle === nb.title) {
      setRenamingTitle(false);
      return;
    }
    setTitleSaving(true);
    setError(null);
    try {
      const updated = await api<Notebook>("PATCH", `/api/v1/notebooks/${nbId}`, { title: nextTitle });
      setNb((current) => current ? { ...current, title: updated.title ?? nextTitle } : current);
      setRenamingTitle(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTitleSaving(false);
    }
  }

  if (error && nb === null) {
    return (
      <>
        <p className="error-text">{error}</p>
        <a href={withBase("/app")}>← Înapoi la carnetele mele</a>
      </>
    );
  }


  return (
    <div className="nb-shell">
      <header className="nb-header">
        <a href={withBase("/app")} className="nb-brand wordmark" aria-label="Guguță — Carnetele mele">
          <span>Guguță</span>
        </a>
        <span className="nb-brand-divider" aria-hidden="true" />
        <div className="nb-title-area">
          {renamingTitle ? (
            <form className="nb-title-form" onSubmit={(event) => { event.preventDefault(); void saveNotebookTitle(); }}>
              <input
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setRenamingTitle(false);
                }}
                aria-label="Denumirea carnetului"
                maxLength={500}
                autoFocus
              />
              <button type="submit" className="nb-title-save" disabled={!titleDraft.trim() || titleSaving}>
                {titleSaving ? "Se salvează…" : "Salvează"}
              </button>
              <button type="button" className="nb-title-cancel" onClick={() => setRenamingTitle(false)} disabled={titleSaving} aria-label="Anulează redenumirea">×</button>
            </form>
          ) : (
            <>
              <h1>{nb?.title ?? "Carnet"}</h1>
              <button type="button" className="nb-title-edit" onClick={startTitleRename} disabled={!nb} aria-label="Redenumește carnetul" title="Redenumește carnetul">
                <PencilIcon />
              </button>
            </>
          )}
        </div>
        <div className="nb-actions">
          <button
            className="pill share-btn"
            onClick={() => void openShareModal()}
            disabled={!sources?.some((s) => s.status === "ready")}
            title="Creează un pachet de partajare"
          >
            <ShareIcon />
            <span>Partajează</span>
          </button>
        </div>
      </header>
      {error && <p className="error-text nb-error">{error}</p>}

      <nav className="mobile-workspace-nav" aria-label="Panourile carnetului">
        <button
          type="button"
          className={mobilePanel === "materials" ? "active" : ""}
          aria-pressed={mobilePanel === "materials"}
          onClick={() => setMobilePanel("materials")}
        >
          <MaterialsIcon />
          <span>Materiale</span>
        </button>
        <button
          type="button"
          className={mobilePanel === "chat" ? "active" : ""}
          aria-pressed={mobilePanel === "chat"}
          onClick={() => setMobilePanel("chat")}
        >
          <ChatIcon />
          <span>Conversație</span>
        </button>
        <button
          type="button"
          className={mobilePanel === "studio" ? "active" : ""}
          aria-pressed={mobilePanel === "studio"}
          onClick={() => setMobilePanel("studio")}
        >
          <StudioIcon />
          <span>Studio</span>
        </button>
      </nav>

      <div
        className={[
          "nb-grid",
          srcCollapsed ? "src-collapsed" : "",
          studioCollapsed ? "studio-collapsed" : "",
        ].join(" ")}
      >
        {/* -------- Surse (stânga, colapsabil) -------- */}
        <section
          className={`panel src ${srcCollapsed ? "collapsed" : ""} ${mobilePanel === "materials" ? "mobile-active" : ""}`}
          aria-label="Materiale"
        >
          <div className="panel-head">
            <span className="panel-title">Materiale</span>
            <button
              type="button"
              className="icon-btn"
              onClick={() => setSrcCollapsed((v) => !v)}
              aria-label={srcCollapsed ? "Desfă panoul Materiale" : "Strânge panoul Materiale"}
              title={srcCollapsed ? "Desfă" : "Strânge"}
            >
              <PanelToggleIcon side="left" />
            </button>
          </div>
          <div className="panel-rail source-panel-rail" aria-hidden={!srcCollapsed}>
            <button
              type="button"
              className="rail-action rail-add-source"
              onClick={() => document.getElementById("src-file-input")?.click()}
              tabIndex={srcCollapsed ? 0 : -1}
              aria-label="Adaugă sursă"
              title="Adaugă sursă"
            >
              <PlusIcon />
            </button>
            <div className="rail-source-list" aria-label="Materialele carnetului">
              {sources?.map((source) => (
                <span
                  key={source.id}
                  className={`rail-source ${source.selected_for_chat ? "selected" : ""} ${source.status}`}
                  title={source.local_name}
                >
                  <MaterialsIcon />
                  {source.status === "processing" && <span className="rail-status-dot" />}
                </span>
              ))}
            </div>
          </div>
          <div className="panel-body">
            <SourceUploader
              notebookId={nbId}
              onUploaded={addUploadedSource}
              onChanged={loadAll}
            />

            {sources === null ? (
              <p className="muted">Se încarcă…</p>
            ) : (
              sources.map((s) => (
                <div className="src-card" key={s.id}>
                  <label className="src-sel" title="Folosește la răspuns">
                    <input
                      type="checkbox"
                      checked={s.selected_for_chat}
                      onChange={() =>
                        api(
                          "PATCH",
                          `/api/v1/notebooks/${nbId}/sources/${s.id}`,
                          { selected_for_chat: !s.selected_for_chat },
                        ).then(loadAll)
                      }
                    />
                  </label>
                  <span className="src-doc">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                      <path d="M7 3h7l4 4v14H7z" strokeLinejoin="round" />
                      <path d="M14 3v4h4" strokeLinejoin="round" />
                    </svg>
                  </span>
                  <span className="src-name" title={s.local_name}>{s.local_name}</span>
                  {/* Cât timp workerul procesează, fișierul primește doar
                      cercul animat; când e gata, nu se scrie nimic pe el. */}
                  {s.status === "error" ? (
                    <span
                      className="badge error"
                      title={s.status_detail ?? undefined}
                      role="status"
                    >
                      Eroare
                    </span>
                  ) : s.status === "ready" ? null : (
                    <span
                      className="badge processing"
                      title="Se procesează"
                      role="status"
                      aria-label="Se procesează"
                    >
                      <span className="spinner tiny" aria-hidden="true" />
                    </span>
                  )}
                  {s.status === "error" && (
                    <button className="src-act" onClick={() => retrySource(s.id)} title="Reîncearcă">↻</button>
                  )}
                  <button
                    className="src-act"
                    onClick={() => removeSource(s.id)}
                    title="Elimină"
                  >
                    ×
                  </button>
                </div>
              ))
            )}
            {sources?.some((s) => s.status === "error" && s.status_detail) && (
              <p className="error-text">
                {sources.find((s) => s.status === "error")?.status_detail}
              </p>
            )}
          </div>
        </section>

        {/* -------- Conversație (centru) -------- */}
        <section className={`panel chat ${mobilePanel === "chat" ? "mobile-active" : ""}`} aria-label="Conversație">
          <div className="panel-head">
            <div className="panel-heading-copy">
              <span className="panel-title">Conversație</span>
              <span className="panel-subtitle">Întreabă și explorează materialele selectate.</span>
            </div>
            <button
              className="icon-btn reset-chat-btn"
              onClick={newSession}
              aria-label="Resetează conversația"
              title="Resetează conversația"
            >
              <img src={withBase("/assets/broom.png")} alt="" />
            </button>
          </div>
          <div className="panel-body chat-body">
            {/*
              Conversația există întotdeauna: carnetul primește automat o
              sesiune la deschidere (vezi loadAll), iar caseta de scriere e
              randată necondiționat. Panoul nu are stare goală.
            */}
            <div className="msgs">
              {sessionId === null ? (
                <p className="muted chat-hint"><ChatIcon />Se pregătește conversația…</p>
              ) : (
                messages.length === 0 && (
                  <p className="muted chat-hint">
                    <ChatIcon />
                    Întreabă ceva despre materialele selectate ale carnetului.
                  </p>
                )
              )}
              {messages.map((m) => (
                <div key={m.id} className={`msg ${m.role}`}>
                  {m.role === "assistant" ? answerText(m.content) : m.content}
                  {SHOW_ANSWER_REFERENCES &&
                    (citations[m.id] ?? []).map((c, i) => (
                      <span className="citation" key={i}>
                        [{i + 1}]{" "}
                        {c.source_removed ? "Sursă eliminată" : c.display_name}
                        {Object.keys(c.locator).length > 0 &&
                          ` · ${JSON.stringify(c.locator)}`}
                      </span>
                    ))}
                </div>
              ))}
              {streaming !== null && (
                <div className="msg assistant streaming">
                  {answerText(streaming)}
                  {streaming === "" && (
                    <span className="muted">
                      {elapsed < 15 ? "Se generează…" : `Se generează… ${elapsed}s`}
                    </span>
                  )}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            <div className="composer">
              <textarea
                id="draft"
                placeholder={
                  sessionId === null
                    ? "Se pregătește conversația…"
                    : "Pune o întrebare despre materiale…"
                }
                value={draft}
                disabled={sessionId === null}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                className="send-btn"
                onClick={() => void send()}
                disabled={sending || sessionId === null || !draft.trim()}
                aria-label="Trimite"
                title={sending ? `Se generează… ${elapsed}s` : "Trimite"}
              >
                {sending ? (
                  <span style={{ fontSize: 11, fontWeight: 600 }}>{elapsed}s</span>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 12h13M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </section>

        {/* -------- Studio (dreapta, colapsabil) -------- */}
        <section
          className={`panel studio ${studioCollapsed ? "collapsed" : ""} ${mobilePanel === "studio" ? "mobile-active" : ""}`}
          aria-label="Studio"
        >
          <div className="panel-head">
            <span className="panel-title">Studio</span>
            <button
              type="button"
              className="icon-btn"
              onClick={() => setStudioCollapsed((v) => !v)}
              aria-label={studioCollapsed ? "Desfă panoul Studio" : "Strânge panoul Studio"}
              title={studioCollapsed ? "Desfă" : "Strânge"}
            >
              <PanelToggleIcon side="right" />
            </button>
          </div>
          <div className="panel-rail studio-panel-rail" aria-hidden={!studioCollapsed}>
            <button
              type="button"
              className="rail-action rail-tool rail-flashcards"
              onClick={openFlashcardModal}
              disabled={!sources?.some((source) => source.status === "ready")}
              tabIndex={studioCollapsed ? 0 : -1}
              aria-label="Creează Flashcards"
              title="Flashcards"
            >
              <CardsIcon />
            </button>
            <button
              type="button"
              className="rail-action rail-tool rail-quiz"
              onClick={openQuizModal}
              disabled={!sources?.some((source) => source.status === "ready")}
              tabIndex={studioCollapsed ? 0 : -1}
              aria-label="Creează Quiz"
              title="Quiz"
            >
              <QuizIcon />
            </button>
            <button
              type="button"
              className="rail-action rail-tool rail-audio"
              onClick={openAudioModal}
              disabled={!sources?.some((source) => source.status === "ready")}
              tabIndex={studioCollapsed ? 0 : -1}
              aria-label="Creează Audio Overview"
              title="Audio Overview"
            >
              <AudioIcon />
            </button>
          </div>
          <div className="panel-body studio-body">
            <section
              className="studio-section studio-tools-section"
              aria-labelledby="studio-tools-title"
            >
              <h2 id="studio-tools-title">Instrumente</h2>
              <div className="future-tools">
                <button
                  type="button"
                  className="future-tool audio-tool"
                  onClick={openFlashcardModal}
                  disabled={!sources?.some((source) => source.status === "ready")}
                >
                  <span className="studio-tool-icon"><CardsIcon /></span>
                  <span className="studio-tool-copy"><strong>Flashcards</strong><span>Cartonașe de recapitulare</span></span>
                </button>
                <button type="button" className="future-tool audio-tool" onClick={openQuizModal} disabled={!sources?.some((source)=>source.status==="ready")}>
                  <span className="studio-tool-icon"><QuizIcon /></span>
                  <span className="studio-tool-copy"><strong>Quiz</strong><span>Testează înțelegerea</span></span>
                </button>
                <button
                  type="button"
                  className="future-tool audio-tool"
                  onClick={openAudioModal}
                  disabled={!sources?.some((source) => source.status === "ready")}
                >
                  <span className="studio-tool-icon"><AudioIcon /></span>
                  <span className="studio-tool-copy"><strong>Audio Overview</strong><span>Rezumat audio în română</span></span>
                </button>
              </div>
            </section>

            <section
              className="studio-section studio-results"
              aria-labelledby="studio-results-title"
            >
              <div className="studio-section-heading">
                <h2 id="studio-results-title">Materiale create</h2>
                {notes !== null && audioOverviews !== null && flashcardDecks !== null && quizzes !== null ? (
                  <span>{notes.length + audioOverviews.length + flashcardDecks.length + quizzes.length}</span>
                ) : null}
              </div>

              {notes === null || audioOverviews === null || flashcardDecks === null || quizzes === null ? (
                <p className="muted">Se încarcă…</p>
              ) : notes.length === 0 && audioOverviews.length === 0 && flashcardDecks.length === 0 && quizzes.length === 0 ? (
                <div className="studio-empty">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="34" height="34">
                    <path d="M12 2l1.8 5.6L19 9l-5.2 1.4L12 16l-1.8-5.6L5 9l5.2-1.4L12 2zm7 12l.9 2.6L22.5 18l-2.6.9L19 21.5l-.9-2.6-2.6-.9 2.6-.9L19 14z" />
                  </svg>
                  <p className="studio-strong">Materialele create vor apărea aici.</p>
                </div>
              ) : null}

              {flashcardDecks?.map((deck) => (
                <article className="flashcard-deck-card" key={deck.id}>
                  <button
                    type="button"
                    className="flashcard-deck-open"
                    onClick={() => deck.status === "ready" && void openDeck(deck.id)}
                    disabled={deck.status !== "ready"}
                  >
                    <span className="flashcard-deck-icon" aria-hidden="true">▣</span>
                    <span>
                      <strong>{deck.title || "Flashcards"}</strong>
                      <small>
                        {deck.status === "ready"
                          ? `${deck.card_count} cartonașe · ${deck.difficulty === "easy" ? "Ușor" : deck.difficulty === "hard" ? "Dificil" : "Mediu"}`
                          : deck.status === "failed" ? "Generarea a eșuat" : "Se generează în fundal…"}
                      </small>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="audio-overview-delete"
                    onClick={() => void removeFlashcardDeck(deck)}
                    disabled={deletingDeckId !== null}
                    aria-label={`Șterge ${deck.title || "setul de flashcards"}`}
                    title="Șterge setul"
                  >
                    {deletingDeckId === deck.id ? <span className="spinner tiny" /> : <TrashIcon />}
                  </button>
                  {deck.status === "failed" && (
                    <div className="flashcard-deck-error">
                      <p className="error-text">{deck.error_detail || "Generarea a eșuat."}</p>
                      <button className="pill small" onClick={() => void retryFlashcardDeck(deck.id)}>Reîncearcă</button>
                    </div>
                  )}
                </article>
              ))}

              {quizzes?.map((quiz)=>(
                <article className="flashcard-deck-card" key={quiz.id}>
                  <button type="button" className="flashcard-deck-open" disabled={quiz.status!=="ready"} onClick={()=>quiz.status==="ready"&&void openQuiz(quiz.id)}>
                    <span className="flashcard-deck-icon" aria-hidden="true">?</span><span><strong>{quiz.title||"Quiz"}</strong><small>{quiz.status==="ready"?`${quiz.question_count} întrebări · ${quiz.difficulty==="easy"?"Ușor":quiz.difficulty==="hard"?"Dificil":"Mediu"}`:quiz.status==="failed"?"Generarea a eșuat":"Se generează în fundal…"}</small></span>
                  </button>
                  <button type="button" className="audio-overview-delete" onClick={()=>void removeQuiz(quiz)} aria-label="Șterge quiz-ul"><TrashIcon /></button>
                  {quiz.status==="failed"&&<div className="flashcard-deck-error"><p className="error-text">{quiz.error_detail||"Generarea a eșuat."}</p><button className="pill small" onClick={()=>void retryQuiz(quiz.id)}>Reîncearcă</button></div>}
                </article>
              ))}

              {audioOverviews?.map((overview) => (
                <article className="audio-overview-card" key={overview.id}>
                  <div className="audio-overview-head">
                    <span className="audio-overview-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M5 9v6M9 6v12M13 4v16M17 7v10M21 10v4" strokeLinecap="round" />
                      </svg>
                    </span>
                    <div className="audio-overview-title">
                      <strong>{overview.title || "Rezumat audio"}</strong>
                      <span>
                        {overview.format === "brief" ? "Brief" : "Deep Dive"}
                        {overview.duration_seconds
                          ? ` · ${Math.max(1, Math.round(overview.duration_seconds / 60))} min`
                          : ""}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="audio-overview-delete"
                      onClick={() => void removeAudioOverview(overview)}
                      disabled={deletingAudioId !== null}
                      aria-label={`Șterge ${overview.title || "rezumatul audio"}`}
                      title="Șterge Audio Overview"
                    >
                      {deletingAudioId === overview.id ? (
                        <span className="spinner tiny" aria-hidden="true" />
                      ) : (
                        <TrashIcon />
                      )}
                    </button>
                  </div>
                  {overview.status === "ready" ? (
                    <audio
                      controls
                      preload="metadata"
                      src={`${API_BASE}/api/v1/notebooks/${nbId}/audio-overviews/${overview.id}/audio`}
                    >
                      Browserul tău nu poate reda acest fișier audio.
                    </audio>
                  ) : overview.status === "failed" ? (
                    <div className="audio-overview-error">
                      <p>{overview.error_detail || "Generarea audio a eșuat."}</p>
                      <button className="pill small" onClick={() => retryAudioOverview(overview.id)}>
                        Reîncearcă
                      </button>
                    </div>
                  ) : (
                    <p className="audio-overview-progress" role="status">
                      <span className="spinner tiny" aria-hidden="true" />
                      {overview.status === "synthesizing"
                        ? "Se generează vocea local…"
                        : overview.status === "generating_script"
                          ? "Se pregătește scenariul…"
                          : "În așteptare…"}
                    </p>
                  )}
                </article>
              ))}

              {notes?.map((n) => (
                <div className="card" key={n.id}>
                  <h3>{n.title}</h3>
                  <p>{n.content}</p>
                  <button className="pill small" onClick={() => removeNote(n.id)}>
                    Șterge notița
                  </button>
                </div>
              ))}
            </section>
          </div>
        </section>
      </div>

      {shareModalOpen&&(
        <div className="modal-overlay" role="presentation" onClick={()=>!shareSubmitting&&setShareModalOpen(false)}><div className="modal share-modal" role="dialog" aria-modal="true" aria-labelledby="share-title" onClick={e=>e.stopPropagation()}>
          <div className="audio-modal-heading"><div><h2 id="share-title">Partajează carnetul</h2><p className="muted">Se creează o copie numai din materialele selectate. Chatul, notițele și progresul rămân private.</p></div><button className="icon-btn" onClick={()=>setShareModalOpen(false)}>×</button></div>
          {createdShare? <div className="share-created">
            <div className="share-success">✓ Codul este gata</div>
            <p className="muted">Codul și linkul sunt afișate numai acum. Le poți revoca ulterior.</p>
            <label><span>Cod de import</span><div className="share-copy-row"><code>{createdShare.code.slice(0,4)}-{createdShare.code.slice(4)}</code><button className="chip" onClick={()=>void copyShare(createdShare.code,"code")}>{copiedShare==="code"?"Copiat":"Copiază codul"}</button></div></label>
            <label><span>Link direct</span><div className="share-copy-row"><input readOnly value={`${window.location.origin}${withBase("/import")}#token=${createdShare.token}`}/><button className="chip" onClick={()=>void copyShare(`${window.location.origin}${withBase("/import")}#token=${createdShare.token}`,"link")}>{copiedShare==="link"?"Copiat":"Copiază linkul"}</button></div></label>
            <div className="modal-actions share-modal-actions"><button className="create-btn" onClick={()=>setCreatedShare(null)}>Creează alt cod</button><button className="chip" onClick={()=>setShareModalOpen(false)}>Închide</button></div>
          </div>:<>
            <label className="flashcard-instructions"><span>Titlul copiei</span><input value={shareTitle} onChange={e=>setShareTitle(e.target.value)} maxLength={500}/></label>
            <label className="flashcard-instructions"><span>Mesaj pentru destinatar (opțional)</span><textarea value={shareDescription} onChange={e=>setShareDescription(e.target.value)} maxLength={5000} placeholder="Descrie pe scurt conținutul carnetului…"/></label>
            <fieldset className="audio-source-options"><div className="audio-source-legend"><span className="fieldset-label">Materiale incluse</span><button type="button" onClick={()=>setShareSourceIds((sources??[]).filter(s=>s.status==="ready").map(s=>s.id))}>Selectează toate</button></div><div className="audio-source-list">{(sources??[]).filter(s=>s.status==="ready").map(s=><label key={s.id}><input type="checkbox" checked={shareSourceIds.includes(s.id)} onChange={()=>setShareSourceIds(v=>v.includes(s.id)?v.filter(x=>x!==s.id):[...v,s.id])}/><span>{s.local_name}</span></label>)}</div></fieldset>
            <label className="share-expiry"><span>Cod valabil</span><select value={shareExpiry} onChange={e=>setShareExpiry(e.target.value as typeof shareExpiry)}><option value="1">24 de ore</option><option value="7">7 zile</option><option value="30">30 de zile</option><option value="90">90 de zile</option><option value="never">Fără expirare</option></select></label>
            <div className="modal-actions share-modal-actions"><button className="chip" onClick={()=>setShareModalOpen(false)}>Anulează</button><button className="create-btn" disabled={shareSubmitting||!shareSourceIds.length||!shareTitle.trim()} onClick={()=>void createShare()}>{shareSubmitting?"Se creează…":"Creează codul"}</button></div>
          </>}
          {shares.length>0&&<section className="share-history"><h3>Coduri create</h3>{shares.map(item=><div className="share-history-item" key={item.id}><div><strong>{item.title}</strong><small>{item.material_count} materiale · {item.status==="active"?"Activ":item.status==="expired"?"Expirat":"Revocat"}</small></div>{item.status==="active"&&<button className="chip danger" onClick={()=>void revokeShare(item.id)}>Revocă</button>}</div>)}</section>}
        </div></div>
      )}

      {quizModalOpen&&(
        <div className="modal-overlay" role="presentation" onClick={()=>!quizSubmitting&&setQuizModalOpen(false)}><div className="modal flashcard-config-modal" role="dialog" aria-modal="true" onClick={(e)=>e.stopPropagation()}>
          <div className="audio-modal-heading"><div><h2>Creează Quiz</h2><p className="muted">Întrebări și evaluare grounded în materialele alese.</p></div><button className="icon-btn" onClick={()=>setQuizModalOpen(false)}>×</button></div>
          <div className="flashcard-config-grid">
            <fieldset className="flashcard-presets"><legend>Număr de întrebări</legend><div>{(["fewer","standard","more"] as const).map(v=><button type="button" key={v} className={quizQuantity===v?"selected":""} onClick={()=>setQuizQuantity(v)}>{v==="fewer"?"Mai puține":v==="more"?"Mai multe":"Standard"}</button>)}</div></fieldset>
            <fieldset className="flashcard-presets"><legend>Dificultate</legend><div>{(["easy","medium","hard"] as const).map(v=><button type="button" key={v} className={quizDifficulty===v?"selected":""} onClick={()=>setQuizDifficulty(v)}>{v==="easy"?"Ușor":v==="hard"?"Dificil":"Mediu"}</button>)}</div></fieldset>
          </div>
          <fieldset className="quiz-types"><legend>Tipuri de întrebări</legend><div>{(["fill_in_blank","multiple_choice","multiple_select","short_answer"] as QuizQuestionType[]).map(v=><button type="button" key={v} className={quizTypes.includes(v)?"selected":""} onClick={()=>setQuizTypes(c=>c.includes(v)?c.filter(x=>x!==v):[...c,v])}>✓ {v==="fill_in_blank"?"Completează spațiul":v==="multiple_choice"?"Alegere unică":v==="multiple_select"?"Alegere multiplă":"Răspuns scurt"}</button>)}</div></fieldset>
          <fieldset className="audio-source-options"><div className="audio-source-legend"><span className="fieldset-label">Materiale</span><button type="button" onClick={()=>setQuizSourceIds((sources??[]).filter(s=>s.status==="ready").map(s=>s.id))}>Selectează toate</button></div><div className="audio-source-list">{(sources??[]).filter(s=>s.status==="ready").map(s=><label key={s.id}><input type="checkbox" checked={quizSourceIds.includes(s.id)} onChange={()=>setQuizSourceIds(c=>c.includes(s.id)?c.filter(x=>x!==s.id):[...c,s.id])}/><span>{s.local_name}</span></label>)}</div></fieldset>
          <label className="flashcard-instructions"><span>Pe ce să se concentreze?</span><textarea value={quizInstructions} onChange={e=>setQuizInstructions(e.target.value)} maxLength={4000} placeholder="Opțional: concepte, comparații, aplicații…"/></label>
          <div className="modal-actions"><button className="chip" onClick={()=>setQuizModalOpen(false)}>Anulează</button><button className="create-btn" disabled={quizSubmitting||!quizSourceIds.length||!quizTypes.length} onClick={()=>void createQuiz()}>{quizSubmitting?"Se adaugă…":"Generează acum"}</button></div>
        </div></div>
      )}

      {activeQuiz&&quizAttempt&&(
        <div className="modal-overlay flashcard-study-overlay" role="presentation"><div className="flashcard-study quiz-study" role="dialog" aria-modal="true">
          <div className="flashcard-study-scroll">
          <header><div><h2>{activeQuiz.title||"Quiz"}</h2><p>Întrebări din materialele selectate</p></div><div className="flashcard-study-actions"><button className="icon-btn" onClick={()=>{setActiveQuiz(null);setQuizAttempt(null)}} aria-label="Închide">×</button></div></header>
          {quizAttempt.completed_at?(
            <div className="flashcard-complete"><span>✓</span><h3>Quiz încheiat</h3><p><strong>{Object.values(quizAttempt.answers).filter(v=>v.status==="correct").length}</strong> din <strong>{quizAttempt.question_order.length}</strong> răspunsuri corecte</p><div className="modal-actions"><button className="chip" onClick={()=>{setQuizAttempt({...quizAttempt,completed_at:null,current_index:0});}}>Revizuiește</button><button className="create-btn" onClick={()=>void openQuiz(activeQuiz.id,true)}>Reia quiz-ul</button></div></div>
          ):currentQuizQuestion? <>
            <div className="flashcard-toolbar"><span>{quizAttempt.current_index+1} / {quizAttempt.question_order.length}</span><span>{currentQuizQuestion.question_type==="multiple_choice"?"Alegere unică":currentQuizQuestion.question_type==="multiple_select"?"Alegere multiplă":currentQuizQuestion.question_type==="fill_in_blank"?"Completează":"Răspuns scurt"}</span></div>
            <section className="quiz-question"><h3>{currentQuizQuestion.prompt}</h3>
              {currentQuizQuestion.options.length>0?<div className="quiz-options">{currentQuizQuestion.options.map(o=>{const selected=Array.isArray(quizResponse)?quizResponse.includes(o.id):quizResponse===o.id;return <button type="button" key={o.id} className={selected?"selected":""} disabled={!!currentQuizAnswer} onClick={()=>setQuizResponse(currentQuizQuestion.question_type==="multiple_select"?(Array.isArray(quizResponse)&&quizResponse.includes(o.id)?quizResponse.filter(v=>v!==o.id):[...(Array.isArray(quizResponse)?quizResponse:[]),o.id]):o.id)}>{currentQuizQuestion.question_type==="multiple_select"?(selected?"☑":"☐"):selected?"●":"○"} {o.text}</button>})}</div>:currentQuizQuestion.question_type==="short_answer"?<textarea className="quiz-answer-input" value={typeof quizResponse==="string"?quizResponse:""} disabled={!!currentQuizAnswer} onChange={e=>setQuizResponse(e.target.value)} placeholder="Scrie răspunsul tău…"/>:<input className="quiz-answer-input" value={typeof quizResponse==="string"?quizResponse:""} disabled={!!currentQuizAnswer} onChange={e=>setQuizResponse(e.target.value)} placeholder="Completează răspunsul…"/>}
              {quizHint&&<p className="quiz-hint"><strong>Indiciu:</strong> {currentQuizQuestion.hint}</p>}
              {currentQuizAnswer&&<div className={`quiz-feedback ${currentQuizAnswer.status}`}><strong>{currentQuizAnswer.status==="correct"?"Răspuns corect":currentQuizAnswer.status==="partial"?"Parțial corect":"Mai încearcă"}</strong><p>{currentQuizAnswer.feedback}</p>{quizExplanation?<p>{quizExplanation}</p>:<button className="chip" onClick={()=>void explainQuizQuestion()} disabled={quizBusy}>Explică mai mult</button>}</div>}
            </section>
            <div className="flashcard-navigation"><button className="chip" disabled={quizAttempt.current_index===0} onClick={()=>moveQuiz(-1)}>← Anterior</button>{!currentQuizAnswer?<div><button className="chip" onClick={()=>setQuizHint(v=>!v)}>Indiciu</button><button className="create-btn" disabled={quizBusy||(typeof quizResponse==="string"?!quizResponse.trim():!quizResponse.length)} onClick={()=>void submitQuizAnswer()}>Verifică</button></div>:<span/>}<button className="chip" disabled={quizAttempt.current_index===quizAttempt.question_order.length-1} onClick={()=>moveQuiz(1)}>Următor →</button></div>
          </>:<p className="error-text">Întrebarea nu mai există.</p>}
          </div>
        </div></div>
      )}

      {flashcardModalOpen && (
        <div className="modal-overlay" role="presentation" onClick={() => !flashcardSubmitting && setFlashcardModalOpen(false)}>
          <div className="modal flashcard-config-modal" role="dialog" aria-modal="true" aria-labelledby="flashcard-config-title" onClick={(event) => event.stopPropagation()}>
            <div className="audio-modal-heading">
              <div>
                <h2 id="flashcard-config-title">Creează Flashcards</h2>
                <p className="muted">Cartonașe grounded exclusiv în materialele alese.</p>
              </div>
              <button type="button" className="icon-btn" aria-label="Închide" onClick={() => setFlashcardModalOpen(false)}>×</button>
            </div>
            <div className="flashcard-config-grid">
              <fieldset className="flashcard-presets">
                <legend>Număr de cartonașe</legend>
                <div>{(["fewer", "standard", "more"] as const).map((value) => (
                  <button type="button" key={value} className={flashcardQuantity === value ? "selected" : ""} onClick={() => setFlashcardQuantity(value)}>
                    {value === "fewer" ? "Mai puține" : value === "more" ? "Mai multe" : "Standard"}
                  </button>
                ))}</div>
              </fieldset>
              <fieldset className="flashcard-presets">
                <legend>Dificultate</legend>
                <div>{(["easy", "medium", "hard"] as const).map((value) => (
                  <button type="button" key={value} className={flashcardDifficulty === value ? "selected" : ""} onClick={() => setFlashcardDifficulty(value)}>
                    {value === "easy" ? "Ușor" : value === "hard" ? "Dificil" : "Mediu"}
                  </button>
                ))}</div>
              </fieldset>
            </div>
            <fieldset className="audio-source-options">
              <div className="audio-source-legend"><span className="fieldset-label">Materiale</span><button type="button" onClick={() => setFlashcardSourceIds((sources ?? []).filter((source) => source.status === "ready").map((source) => source.id))}>Selectează toate</button></div>
              <div className="audio-source-list">{(sources ?? []).filter((source) => source.status === "ready").map((source) => (
                <label key={source.id}><input type="checkbox" checked={flashcardSourceIds.includes(source.id)} onChange={() => toggleFlashcardSource(source.id)} /><span>{source.local_name}</span></label>
              ))}</div>
            </fieldset>
            <label className="flashcard-instructions">
              <span>Pe ce să se concentreze?</span>
              <textarea value={flashcardInstructions} onChange={(event) => setFlashcardInstructions(event.target.value)} maxLength={4000} placeholder="Opțional: formule, concepte-cheie, diferențe între metode…" />
            </label>
            <div className="modal-actions">
              <button type="button" className="chip" onClick={() => setFlashcardModalOpen(false)} disabled={flashcardSubmitting}>Anulează</button>
              <button type="button" className="create-btn" onClick={() => void createFlashcardDeck()} disabled={flashcardSubmitting || flashcardSourceIds.length === 0}>{flashcardSubmitting ? "Se adaugă…" : "Generează acum"}</button>
            </div>
          </div>
        </div>
      )}

      {activeDeck && studySession && (
        <div className="modal-overlay flashcard-study-overlay" role="presentation">
          <div className="flashcard-study" role="dialog" aria-modal="true" aria-labelledby="flashcard-study-title">
            <div className="flashcard-study-scroll">
            <header>
              <div><h2 id="flashcard-study-title">{activeDeck.title || "Flashcards"}</h2><p>{studySession.card_order.length} cartonașe · Space pentru întoarcere</p></div>
              <div className="flashcard-study-actions">
                <button type="button" className="icon-btn" aria-label="Închide" onClick={() => { setActiveDeck(null); setStudySession(null); }}>×</button>
              </div>
            </header>
            {studySession.completed_at ? (
              <div className="flashcard-complete">
                <span aria-hidden="true">✓</span>
                <h3>Sesiune încheiată</h3>
                <p><strong>{gotItCount}</strong> știute · <strong>{missedCount}</strong> ratate</p>
                <div className="modal-actions">
                  <button className="chip" onClick={() => void openDeck(activeDeck.id, "same")}>Aceleași cartonașe</button>
                  <button className="chip" onClick={() => void openDeck(activeDeck.id, "all")}>Toate</button>
                  <button className="create-btn" disabled={missedCount === 0} onClick={() => void openDeck(activeDeck.id, "missed")}>Doar cele ratate</button>
                </div>
              </div>
            ) : currentStudyCard ? (
              <>
                <div className="flashcard-toolbar">
                  <span>{studySession.current_index + 1} / {studySession.card_order.length}</span>
                  <button className="chip" onClick={() => void shuffleStudy()}>Amestecă</button>
                  <button className="chip danger" onClick={() => void removeFlashcard(currentStudyCard.id)}>Șterge cardul</button>
                </div>
                <button type="button" className={`study-card ${cardFlipped ? "flipped" : ""}`} onClick={() => setCardFlipped((value) => !value)}>
                  <span className="study-card-label">{cardFlipped ? "Răspuns" : "Întrebare"}</span>
                  <strong>{cardFlipped ? currentStudyCard.back : currentStudyCard.front}</strong>
                  {!cardFlipped && <small>Apasă pentru a vedea răspunsul</small>}
                  {cardFlipped && currentStudyCard.evidence.length > 0 && <small>Surse: {[...new Set(currentStudyCard.evidence.map((ref) => ref.source_name))].join(", ")}</small>}
                </button>
                {cardFlipped && (
                  <div className="flashcard-explanation">
                    {cardExplanation ? <p>{cardExplanation}</p> : (
                      <button className="chip" disabled={explainingCard} onClick={() => void explainCard(currentStudyCard.id)}>
                        {explainingCard ? "Se explică…" : "Explică mai mult"}
                      </button>
                    )}
                  </div>
                )}
                <div className="flashcard-navigation">
                  <button className="chip" disabled={studySession.current_index === 0} onClick={() => { setCardFlipped(false); setCardExplanation(null); setStudySession({ ...studySession, current_index: studySession.current_index - 1 }); }}>← Anterior</button>
                  {cardFlipped ? <div><button className="missed-btn" onClick={() => void assessCard("missed")}>Am ratat</button><button className="got-it-btn" onClick={() => void assessCard("got_it")}>Știu</button></div> : <button className="create-btn" onClick={() => setCardFlipped(true)}>Vezi răspunsul</button>}
                  <button className="chip" disabled={studySession.current_index === studySession.card_order.length - 1} onClick={() => { setCardFlipped(false); setCardExplanation(null); setStudySession({ ...studySession, current_index: studySession.current_index + 1 }); }}>Următor →</button>
                </div>
              </>
            ) : <p className="error-text">Cartonașul nu mai există.</p>}
            </div>
          </div>
        </div>
      )}

      {audioModalOpen && (
        <div
          className="modal-overlay"
          role="presentation"
          onClick={() => !audioSubmitting && setAudioModalOpen(false)}
        >
          <div
            className="modal audio-overview-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="audio-overview-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="audio-modal-heading">
              <div>
                <h2 id="audio-overview-title">Creează un Audio Overview</h2>
                <p className="muted">O singură voce explică materialele în limba română.</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                aria-label="Închide"
                onClick={() => setAudioModalOpen(false)}
                disabled={audioSubmitting}
              >
                ×
              </button>
            </div>

            <fieldset className="audio-format-options">
              <legend>Format</legend>
              <label className={audioFormat === "brief" ? "selected" : ""}>
                <input
                  type="radio"
                  name="audio-format"
                  value="brief"
                  checked={audioFormat === "brief"}
                  onChange={() => setAudioFormat("brief")}
                />
                <span>
                  <strong>Brief</strong>
                  <small>Ideile esențiale într-un rezumat de aproximativ 2 minute.</small>
                </span>
              </label>
              <label className={audioFormat === "deep_dive" ? "selected" : ""}>
                <input
                  type="radio"
                  name="audio-format"
                  value="deep_dive"
                  checked={audioFormat === "deep_dive"}
                  onChange={() => setAudioFormat("deep_dive")}
                />
                <span>
                  <strong>Deep Dive</strong>
                  <small>Explicație aprofundată, cu legături, exemple și recapitulare.</small>
                </span>
              </label>
            </fieldset>

            <fieldset className="audio-source-options">
              <div className="audio-source-legend">
                <span className="fieldset-label">Materiale</span>
                <button
                  type="button"
                  onClick={() =>
                    setAudioSourceIds(
                      (sources ?? [])
                        .filter((source) => source.status === "ready")
                        .map((source) => source.id),
                    )
                  }
                >
                  Selectează toate
                </button>
              </div>
              <div className="audio-source-list">
                {(sources ?? [])
                  .filter((source) => source.status === "ready")
                  .map((source) => (
                    <label key={source.id}>
                      <input
                        type="checkbox"
                        checked={audioSourceIds.includes(source.id)}
                        onChange={() => toggleAudioSource(source.id)}
                      />
                      <span title={source.local_name}>{source.local_name}</span>
                    </label>
                  ))}
              </div>
            </fieldset>

            <p className="audio-local-note">
              Vocea este generată local cu MOSS-TTS. Procesarea continuă în fundal;
              poți închide această fereastră.
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="chip"
                onClick={() => setAudioModalOpen(false)}
                disabled={audioSubmitting}
              >
                Anulează
              </button>
              <button
                type="button"
                className="create-btn"
                onClick={() => void createAudioOverview()}
                disabled={audioSubmitting || audioSourceIds.length === 0}
              >
                {audioSubmitting ? "Se adaugă…" : "Generează audio"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
