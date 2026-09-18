"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError, getCsrf, Note, Notebook, Source } from "../../../lib/api";
import {
  SHOW_ANSWER_REFERENCES,
  withoutReferenceMarkers,
} from "../../../lib/features";
import SourceUploader from "../../components/SourceUploader";
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
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [citations, setCitations] = useState<Record<string, Citation[]>>({});
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [srcCollapsed, setSrcCollapsed] = useState(false);
  const [studioCollapsed, setStudioCollapsed] = useState(false);
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
    (flashcardDecks?.some((item) => ["queued", "generating"].includes(item.status)) ?? false);
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

  async function createShare() {
    if (!sources?.length) return;
    const ready = sources.filter((s) => s.status === "ready");
    if (!ready.length) { setError("Niciun material gata pentru partajare."); return; }
    try {
      const share = await api<{ share_id: string; token: string; code: string }>(
        "POST",
        `/api/v1/notebooks/${nbId}/shares`,
        { source_ids: ready.map((s) => s.id), title: nb?.title },
      );
      const link = `${window.location.origin}${withBase("/import")}#token=${share.token}`;
      await navigator.clipboard.writeText(link);
      alert(`Link copiat:\n${link}\n\nCod: ${share.code}`);
      await loadAll();
    } catch (err) {
      setError((err as Error).message);
    }
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
        <a href={withBase("/app")} className="nb-back" aria-label="Înapoi la carnetele mele">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m14 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
        <h1>{nb?.title ?? "Carnet"}</h1>
        <div className="nb-actions">
          {/*
            Redenumirea, fixarea sus și ștergerea se fac din meniul cardului,
            în lista de carnete (app/components/NotebookMenu.tsx) — aici rămâne
            doar partajarea, care ține de conținutul carnetului deschis.
          */}
          <button
            className="pill"
            onClick={createShare}
            disabled={!sources?.some((s) => s.status === "ready")}
            title="Creează un pachet de partajare"
          >
            Partajează
          </button>
        </div>
      </header>
      {error && <p className="error-text nb-error">{error}</p>}

      <div
        className={[
          "nb-grid",
          srcCollapsed ? "src-collapsed" : "",
          studioCollapsed ? "studio-collapsed" : "",
        ].join(" ")}
      >
        {/* -------- Surse (stânga, colapsabil) -------- */}
        <section
          className={`panel src ${srcCollapsed ? "collapsed" : ""}`}
          aria-label="Materiale"
        >
          <div className="panel-head">
            <span className="panel-title">Materiale</span>
            <button
              className="icon-btn"
              onClick={() => setSrcCollapsed((v) => !v)}
              aria-label={srcCollapsed ? "Desfă panoul Materiale" : "Strânge panoul Materiale"}
              title={srcCollapsed ? "Desfă" : "Strânge"}
            >
              {srcCollapsed ? "»" : "«"}
            </button>
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
        <section className="panel chat" aria-label="Conversație">
          <div className="panel-head">
            <span className="panel-title">Conversație</span>
            <button className="pill small" onClick={newSession}>Conversație nouă</button>
          </div>
          <div className="panel-body chat-body">
            {/*
              Conversația există întotdeauna: carnetul primește automat o
              sesiune la deschidere (vezi loadAll), iar caseta de scriere e
              randată necondiționat. Panoul nu are stare goală.
            */}
            <div className="msgs">
              {sessionId === null ? (
                <p className="muted chat-hint">Se pregătește conversația…</p>
              ) : (
                messages.length === 0 && (
                  <p className="muted chat-hint">
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
          className={`panel studio ${studioCollapsed ? "collapsed" : ""}`}
          aria-label="Studio"
        >
          <div className="panel-head">
            <span className="panel-title">Studio</span>
            <button
              className="icon-btn"
              onClick={() => setStudioCollapsed((v) => !v)}
              aria-label={studioCollapsed ? "Desfă panoul Studio" : "Strânge panoul Studio"}
              title={studioCollapsed ? "Desfă" : "Strânge"}
            >
              {studioCollapsed ? "«" : "»"}
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
                  <strong>Flashcards</strong>
                  <span>Generează cartonașe de recapitulare din materiale.</span>
                </button>
                <div className="future-tool">
                  <strong>Quiz</strong>
                  <span>Va crea întrebări pentru verificarea cunoștințelor.</span>
                </div>
                <button
                  type="button"
                  className="future-tool audio-tool"
                  onClick={openAudioModal}
                  disabled={!sources?.some((source) => source.status === "ready")}
                >
                  <strong>Audio Overview</strong>
                  <span>Transformă materialele selectate într-un rezumat audio.</span>
                </button>
              </div>
            </section>

            <section
              className="studio-section studio-results"
              aria-labelledby="studio-results-title"
            >
              <div className="studio-section-heading">
                <h2 id="studio-results-title">Materiale create</h2>
                {notes !== null && audioOverviews !== null && flashcardDecks !== null ? (
                  <span>{notes.length + audioOverviews.length + flashcardDecks.length}</span>
                ) : null}
              </div>

              {notes === null || audioOverviews === null || flashcardDecks === null ? (
                <p className="muted">Se încarcă…</p>
              ) : notes.length === 0 && audioOverviews.length === 0 && flashcardDecks.length === 0 ? (
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
                    {deletingDeckId === deck.id ? <span className="spinner tiny" /> : "×"}
                  </button>
                  {deck.status === "failed" && <p className="error-text">{deck.error_detail || "Încearcă să generezi un set nou."}</p>}
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
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                          <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5M14 11v5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
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
            <header>
              <div><h2 id="flashcard-study-title">{activeDeck.title || "Flashcards"}</h2><p>{studySession.card_order.length} cartonașe · Space pentru întoarcere</p></div>
              <div className="flashcard-study-actions">
                <a className="chip" href={`${API_BASE}/api/v1/notebooks/${nbId}/flashcard-decks/${activeDeck.id}/export.csv`}>CSV</a>
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
