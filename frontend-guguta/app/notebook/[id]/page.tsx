"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, ApiError, getCsrf, me, Note, Notebook, Source, CatalogTemplate } from "../../../lib/api";
import EducationCompanion from "../../components/EducationCompanion";
import {
  SHOW_ANSWER_REFERENCES,
  withoutReferenceMarkers,
} from "../../../lib/features";
import ChatAttachments, { AttachmentCards, type ChatAttachment } from "../../components/ChatAttachments";
import PrivateImagePreview from "../../components/PrivateImagePreview";
import LogoutButton from "../../components/LogoutButton";
import ThemeToggle from "../../components/ThemeToggle";
import SourceUploader from "../../components/SourceUploader";
import MarkdownContent from "../../components/MarkdownContent";
import {
  AudioIcon,
  BookIcon,
  CardsIcon,
  ChatIcon,
  MaterialsIcon,
  MicrophoneIcon,
  PencilIcon,
  PanelToggleIcon,
  PlusIcon,
  QuizIcon,
  ShareIcon,
  StudioIcon,
  TrashIcon,
  VideoIcon,
} from "../../components/UiIcons";
import { withBase, API_BASE } from "../../../lib/paths";

interface ChatMessage {
  id: string;
  seq: number;
  role: string;
  content: string;
  context_revision: number;
  // Keep the optimistic message and its files together while the server saves it.
  clientId?: string;
  attachments?: ChatAttachment[];
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
  instructions?: string | null;
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
/** Starea exportului către PlayQuiz extern (ADR-023), GET …/quizzes/{id}/playquiz. */
interface PlayQuizStatus { enabled:boolean; consent_given:boolean; exportable:boolean; reason?:string|null; exported:boolean; play_url?:string|null; }
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

type SourceIconType = "book" | "quiz" | "audio" | "video" | "document";

function sourceIconType(source: Source): SourceIconType {
  const mime = (source.mime_type ?? "").toLowerCase();
  const name = source.local_name.toLowerCase();
  const original = (source.original_name ?? "").toLowerCase();
  if (mime.startsWith("audio/") || /\.(mp3|wav|m4a|ogg)$/.test(original) || /^(audio|înregistrare audio)\b/.test(name)) return "audio";
  if (mime.startsWith("video/") || /\.(mp4|webm|mov)$/.test(original) || /^(lecție video|video)\b/.test(name)) return "video";
  if (/(?:test|quiz|evaluare|exerciți|exerciti|fișă de lucru|fisa de lucru)/.test(name)) return "quiz";
  if (mime === "application/pdf" || original.endsWith(".pdf") || /^(manual|carte)\b/.test(name)) return "book";
  return "document";
}

function SourceTypeIcon({ source }: { source: Source }) {
  switch (sourceIconType(source)) {
    case "book": return <BookIcon />;
    case "quiz": return <QuizIcon />;
    case "audio": return <AudioIcon />;
    case "video": return <VideoIcon />;
    default: return <MaterialsIcon />;
  }
}

export default function NotebookPage() {
  const params = useParams<{ id: string }>();
  return <NotebookWorkspace key={params.id} nbId={params.id} />;
}

function NotebookWorkspace({ nbId }: { nbId: string }) {
  const [nb, setNb] = useState<Notebook | null>(null);
  const [companionTemplate, setCompanionTemplate] = useState<CatalogTemplate | null>(null);
  useEffect(() => {
    let cancelled = false;
    setCompanionTemplate(null);
    if (nb?.current_template_version_id) {
      void api<CatalogTemplate[]>("GET", "/api/v1/catalog/templates").then(templates => {
        if (!cancelled) setCompanionTemplate(templates.find(template => template.current_version_id === nb.current_template_version_id) ?? null);
      }).catch(() => { /* Optional metadata must not block the notebook. */ });
    }
    return () => { cancelled = true; };
  }, [nb?.current_template_version_id]);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [audioOverviews, setAudioOverviews] = useState<AudioOverview[] | null>(null);
  const [flashcardDecks, setFlashcardDecks] = useState<FlashcardDeck[] | null>(null);
  const [quizzes, setQuizzes] = useState<QuizArtifact[] | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatAttachments, setChatAttachments] = useState<ChatAttachment[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [resettingChat, setResettingChat] = useState(false);
  const [attachmentRefresh, setAttachmentRefresh] = useState(0);
  const [imagePreview, setImagePreview] = useState<Source | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const submittedAttachmentIds = new Set(messages.flatMap((message) =>
    message.attachments?.map((file) => file.id) ?? []
  ));
  const pendingAttachments = chatAttachments.filter((file) =>
    !file.chat_message_id && !submittedAttachmentIds.has(file.id)
  );
  const attachmentsReady = pendingAttachments.every((file) => file.status === "ready");
  const [citations, setCitations] = useState<Record<string, Citation[]>>({});
  const [draft, setDraft] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speechMessage, setSpeechMessage] = useState<string | null>(null);
  const [chatMessage, setChatMessage] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [srcCollapsed, setSrcCollapsed] = useState(false);
  const [studioCollapsed, setStudioCollapsed] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("chat");
  const [conversationMode, setConversationMode] = useState<"companion" | "chat" | null>(null);
  const draftInputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    let mode: "companion" | "chat" = "companion";
    try {
      if (localStorage.getItem(`guguta_notebook_mode_v1:${nbId}`) === "chat") mode = "chat";
    } catch { /* The control also works without persistent storage. */ }
    setConversationMode(mode);
  }, [nbId]);
  useEffect(() => {
    if (conversationMode === "chat" && sessionId !== null) {
      draftInputRef.current?.focus({ preventScroll: true });
    }
  }, [conversationMode, sessionId]);

  function toggleConversationMode() {
    const next = conversationMode === "chat" ? "companion" : "chat";
    setConversationMode(next);
    setMobilePanel("chat");
    try { localStorage.setItem(`guguta_notebook_mode_v1:${nbId}`, next); } catch { /* Optional preference. */ }
  }

  const [elapsed, setElapsed] = useState(0);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [audioModalOpen, setAudioModalOpen] = useState(false);
  const [audioFormat, setAudioFormat] = useState<"brief" | "deep_dive">("brief");
  const [audioSourceIds, setAudioSourceIds] = useState<string[]>([]);
  const [audioInstructions, setAudioInstructions] = useState("");
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
  // „Deschide în PlayQuiz”: capabilitatea vine din /auth/me, starea din API; acordul se cere o dată.
  const [playquizEnabled,setPlayquizEnabled]=useState(false);
  const [playquizStatus,setPlayquizStatus]=useState<PlayQuizStatus|null>(null);
  const [playquizBusy,setPlayquizBusy]=useState(false);
  const [playquizConsentOpen,setPlayquizConsentOpen]=useState(false);
  const [playquizMessage,setPlayquizMessage]=useState<string|null>(null);
  useEffect(()=>{ void me().then((user)=>setPlayquizEnabled(!!user?.capabilities?.playquiz)); },[]);
  useEffect(()=>{
    let cancelled=false;
    setPlayquizStatus(null);setPlayquizMessage(null);setPlayquizConsentOpen(false);
    if(!playquizEnabled||!activeQuiz) return;
    void api<PlayQuizStatus>("GET",`/api/v1/notebooks/${nbId}/quizzes/${activeQuiz.id}/playquiz`)
      .then((status)=>{ if(!cancelled) setPlayquizStatus(status); })
      .catch(()=>{ /* Butonul lipsește dacă starea nu se poate citi; quizul rămâne jucabil aici. */ });
    return ()=>{ cancelled=true; };
  },[playquizEnabled,activeQuiz,nbId]);
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
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const componentAliveRef = useRef(true);

  useEffect(() => {
    componentAliveRef.current = true;
    return () => {
      componentAliveRef.current = false;
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  useEffect(() => {
    if (!speechMessage) return;
    const timeout = window.setTimeout(() => setSpeechMessage(null), 4500);
    return () => window.clearTimeout(timeout);
  }, [speechMessage]);
  useEffect(() => {
    if (!chatMessage) return;
    const timeout = window.setTimeout(() => setChatMessage(null), 6500);
    return () => window.clearTimeout(timeout);
  }, [chatMessage]);
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

  const notebookLoadRef = useRef<{
    notebookId: string;
    promise: Promise<void>;
    repeat: boolean;
  } | null>(null);
  const currentNotebookIdRef = useRef(nbId);
  currentNotebookIdRef.current = nbId;
  const currentSessionIdRef = useRef(sessionId);
  currentSessionIdRef.current = sessionId;

  // Each panel becomes usable as soon as its request finishes. Initial load
  // and polling share the same batch; a mutation queues one fresh batch if
  // a request started before that mutation is still in flight.
  const loadAll = useCallback((refreshAfterPending = true): Promise<void> => {
    const pending = notebookLoadRef.current;
    if (pending?.notebookId === nbId) {
      if (refreshAfterPending) pending.repeat = true;
      return pending.promise;
    }
    const task = { notebookId: nbId, promise: Promise.resolve(), repeat: false };
    notebookLoadRef.current = task;
    const isCurrent = () => componentAliveRef.current &&
      currentNotebookIdRef.current === nbId && notebookLoadRef.current === task;
    const loadSection = async <T,>(path: string, update: (value: T) => void) => {
      const value = await api<T>("GET", `/api/v1/notebooks/${nbId}${path}`);
      if (isCurrent()) update(value);
    };
    const loadSessions = async () => {
      const sess = await api<ChatSession[]>("GET", `/api/v1/notebooks/${nbId}/sessions`);
      if (!isCurrent()) return;
      setSessions(sess);
      if (sess.length > 0) {
        setSessionId((current) => current ?? sess[0].id);
      } else if (!sessionCreationRef.current) {
        sessionCreationRef.current = true;
        try {
          const created = await api<ChatSession>("POST", `/api/v1/notebooks/${nbId}/sessions`, {});
          if (isCurrent()) {
            setSessions([created]);
            setSessionId((current) => current ?? created.id);
          }
        } catch (err) {
          if (isCurrent()) sessionCreationRef.current = false;
          throw err;
        }
      }
    };
    task.promise = (async () => {
      try {
        do {
          task.repeat = false;
          const results = await Promise.allSettled([
            loadSection<Notebook>("", setNb),
            loadSection<Source[]>("/sources", setSources),
            loadSection<Note[]>("/notes", setNotes),
            loadSection<AudioOverview[]>("/audio-overviews", setAudioOverviews),
            loadSection<FlashcardDeck[]>("/flashcard-decks", setFlashcardDecks),
            loadSection<QuizArtifact[]>("/quizzes", setQuizzes),
            loadSessions(),
          ]);
          if (!isCurrent()) return;
          const failed = results.find((result) => result.status === "rejected");
          if (failed?.status === "rejected") {
            const err = failed.reason;
            setError(err instanceof ApiError && err.status === 404
              ? "Carnetul nu există sau nu îți aparține."
              : (err as Error).message);
          }
        } while (task.repeat && isCurrent());
      } finally {
        if (notebookLoadRef.current === task) notebookLoadRef.current = null;
      }
    })();
    return task.promise;
  }, [nbId]);

  useEffect(() => {
    setNb(null);
    setSources(null);
    setNotes(null);
    setAudioOverviews(null);
    setFlashcardDecks(null);
    setQuizzes(null);
    setSessions([]);
    setSessionId(null);
    setMessages([]);
    setChatAttachments([]);
    setCitations({});
    setError(null);
    sessionCreationRef.current = false;
    void loadAll(false);
  }, [loadAll]);

  // Materialul tocmai urcat intră în listă imediat, în același render în care
  // linia lui temporară dispare — fără dubluri și fără clipire între ele.
  const addUploadedSource = useCallback((source: Source) => {
    setSources((prev) => (prev ? [...prev, source] : [source]));
  }, []);

  const loadMessages = useCallback(async () => {
    if (sessionId === null) return;
    const isCurrent = () => componentAliveRef.current &&
      currentNotebookIdRef.current === nbId && currentSessionIdRef.current === sessionId;
    if (!isCurrent()) return;
    try {
      const msgs = await api<ChatMessage[]>(
        "GET",
        `/api/v1/notebooks/${nbId}/sessions/${sessionId}/messages`,
      );
      if (!isCurrent()) return;
      setMessages((previous) => {
        const localMessages = new Map(previous.map((message) => [message.id, message]));
        return msgs.map((message) => {
          const local = localMessages.get(message.id);
          return local?.clientId
            ? { ...message, clientId: local.clientId, attachments: local.attachments }
            : message;
        });
      });
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
          if (!isCurrent()) return;
          setCitations((prev) => ({ ...prev, [m.id]: cites }));
        } catch {
          if (!isCurrent()) return;
          setCitations((prev) => ({ ...prev, [m.id]: [] }));
        }
      }
    } catch (err) {
      if (isCurrent()) setError((err as Error).message);
    }
  }, [nbId, sessionId]);

  useEffect(() => {
    // The mascot can write to the same session. Refresh its history when opening chat.
    if (conversationMode === "chat") void loadMessages();
  }, [loadMessages, conversationMode]);

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
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      await loadAll(false);
      if (!cancelled) timeout = setTimeout(refresh, 2000);
    };
    timeout = setTimeout(refresh, 2000);
    return () => { cancelled = true; clearTimeout(timeout); };
  }, [hasProcessing, loadAll]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send() {
    if (sending || uploadingAttachments || resettingChat || !attachmentsReady) return;
    const attachmentIds = pendingAttachments.map((file) => file.id);
    const content = draft.trim() || (attachmentIds.length ? "Ajută-mă să înțeleg materialul atașat." : "");
    if (!content || sessionId === null) return;
    setSending(true);
    setError(null);
    setChatMessage(null);
    const optimisticId = `tmp-u-${crypto.randomUUID()}`;
    // optimist: mesajul utilizatorului apare instant; serverul îl salvează
    // oricum în faza 1, deci rămâne vizibil și pe eșec (A26)
    setMessages((prev) => [
      ...prev,
      {
        id: optimisticId,
        clientId: optimisticId,
        attachments: pendingAttachments,
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
          body: JSON.stringify({ content, attachment_ids: attachmentIds }),
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
              user_message_id?: string;
            };
            if (ev.event === "user_saved" && ev.user_message_id) {
              const savedId = ev.user_message_id;
              setMessages((previous) => previous.map((message) =>
                message.id === optimisticId ? { ...message, id: savedId } : message
              ));
              setAttachmentRefresh((value) => value + 1);
            }
            if (ev.event === "token" && ev.text) {
              setStreaming((prev) => (prev ?? "") + ev.text);
            } else if (ev.event === "done") {
              done = true;
            } else if (ev.event === "error") {
              throw new ApiError(502, "provider", ev.message ?? "Eroare AI.");
            }
            // „ping" nu schimbă conținutul afișat.
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
      setChatMessage(message);
      await loadMessages().catch(() => undefined);
    } finally {
      window.clearTimeout(timeout);
      setStreaming(null);
      setSending(false);
      setAttachmentRefresh((value) => value + 1);
    }
  }

  async function transcribeRecording(blob: Blob, mimeType: string) {
    if (blob.size === 0) return;
    setTranscribing(true);
    setSpeechMessage(null);
    try {
      const form = new FormData();
      const extension = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "m4a" : "webm";
      form.append("file", blob, `inregistrare.${extension}`);
      const csrf = getCsrf();
      const response = await fetch(`${API_BASE}/api/v1/speech/transcriptions`, {
        method: "POST",
        credentials: "same-origin",
        headers: csrf ? { "X-Guguta-CSRF": csrf } : {},
        body: form,
      });
      const payload = (await response.json().catch(() => ({}))) as {
        text?: string;
        message?: string;
      };
      if (!response.ok) {
        throw new ApiError(
          response.status,
          "speech_transcription",
          payload.message ?? "Nu am putut transcrie înregistrarea.",
        );
      }
      const text = payload.text?.trim();
      if (text) {
        setDraft((current) => [current.trim(), text].filter(Boolean).join(" "));
      }
    } catch (err) {
      setSpeechMessage((err as Error).message || "Nu am putut transcrie înregistrarea.");
    } finally {
      setTranscribing(false);
    }
  }

  async function toggleRecording() {
    const current = mediaRecorderRef.current;
    if (current && current.state === "recording") {
      current.stop();
      setRecording(false);
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setSpeechMessage("Browserul tău nu permite înregistrarea audio.");
      return;
    }

    try {
      setSpeechMessage(null);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredTypes = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
      const mimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recordingStreamRef.current = stream;
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const actualType = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type: actualType });
        audioChunksRef.current = [];
        stream.getTracks().forEach((track) => track.stop());
        recordingStreamRef.current = null;
        mediaRecorderRef.current = null;
        if (componentAliveRef.current) {
          setRecording(false);
          void transcribeRecording(blob, actualType);
        }
      };
      recorder.start(250);
      setRecording(true);
    } catch (err) {
      recordingStreamRef.current?.getTracks().forEach((track) => track.stop());
      recordingStreamRef.current = null;
      mediaRecorderRef.current = null;
      setRecording(false);
      const denied = err instanceof DOMException && err.name === "NotAllowedError";
      setSpeechMessage(denied ? "Permite accesul la microfon pentru a dicta întrebarea." : "Microfonul nu a putut fi pornit.");
    }
  }

  async function newSession() {
    if (sending || uploadingAttachments || resettingChat) return;
    setResettingChat(true);
    let deleted = false;
    try {
      if (sessionId !== null) {
        await api("DELETE", `/api/v1/notebooks/${nbId}/sessions/${sessionId}`);
        deleted = true;
        setSessions((prev) => prev.filter((session) => session.id !== sessionId));
      }
      setMessages([]); setChatAttachments([]); setDraft("");
      setStreaming(null); setCitations({}); setChatMessage(null);
      const session = await api<ChatSession>("POST", `/api/v1/notebooks/${nbId}/sessions`, {});
      setSessions((prev) => [session, ...prev]);
      setSessionId(session.id);
    } catch (err) {
      if (deleted) setSessionId(null);
      setError((err as Error).message);
    } finally { setResettingChat(false); }
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
    setAudioInstructions("");
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
        {
          format: audioFormat,
          source_ids: audioSourceIds,
          instructions: audioInstructions.trim() || null,
        },
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
  async function openInPlayQuiz(consent:boolean) {
    if(!activeQuiz||playquizBusy) return;
    // Fereastra se deschide sincron, la click, altfel blocatoarele de popup o opresc;
    // primește URL-ul de handoff după răspunsul API-ului.
    const win=window.open("","_blank");
    if(win) win.opener=null;
    setPlayquizBusy(true);setPlayquizMessage(null);
    try {
      const result=await api<{url:string}>("POST",`/api/v1/notebooks/${nbId}/quizzes/${activeQuiz.id}/playquiz`,{consent});
      if(win) win.location.href=result.url; else window.open(result.url,"_blank");
      setPlayquizConsentOpen(false);
      setPlayquizStatus((s)=>s?{...s,consent_given:true,exported:true}:s);
    } catch(err) {
      win?.close();
      if(err instanceof ApiError&&err.code==="consent_required") setPlayquizConsentOpen(true);
      else setPlayquizMessage((err as Error).message);
    } finally { setPlayquizBusy(false); }
  }
  async function retryQuiz(id:string) { try { await api("POST",`/api/v1/notebooks/${nbId}/quizzes/${id}/retry`,{}); await loadAll(); } catch(err){setError((err as Error).message);} }
  async function openQuiz(id:string, retake=false) {
    try {
      const quiz=await api<QuizArtifact>("GET",`/api/v1/notebooks/${nbId}/quizzes/${id}`);
      // PlayQuiz currently supports complete quizzes made only of grid questions.
      // Check their actual types before creating an attempt or opening a local dialog.
      if (quiz.status === "ready" && quiz.questions?.length && quiz.questions.every(
        (question) => question.question_type === "multiple_choice" || question.question_type === "multiple_select"
      )) {
        window.location.assign(withBase(`/playquiz/quiz/categorized/${encodeURIComponent(quiz.id)}?notebook=${encodeURIComponent(nbId)}`));
        return;
      }
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
        <Link href="/app">← Înapoi la carnetele mele</Link>
      </>
    );
  }


  const conversationModeButton = (
    <button type="button" className="notebook-chat-toggle" onClick={toggleConversationMode}
      disabled={conversationMode === null || (conversationMode === "chat" && (sending || uploadingAttachments || resettingChat || recording || transcribing))}
      aria-controls="notebook-conversation"
      aria-label={conversationMode === "chat" ? "Activează Guguță" : "Deschide chatul"}
      title={conversationMode === "chat" ? "Revino la Guguță" : "Deconectează Guguță și deschide chatul"}>
      {conversationMode === "chat" ? <AudioIcon /> : <ChatIcon />}
      <span>{conversationMode === "chat" ? "Guguță" : "Chat"}</span>
    </button>
  );

  return (
    <div className="nb-shell" data-conversation-mode={conversationMode ?? "loading"}>
      <header className="nb-header">
        <Link href="/app" className="nb-brand wordmark" aria-label="Platforma educațională Guguță" title="Platforma educațională Guguță">
          <span>Platforma educațională Guguță</span>
        </Link>
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
          {conversationModeButton}
          <button
            className="pill share-btn"
            onClick={() => void openShareModal()}
            disabled={!sources?.some((s) => s.status === "ready")}
            title="Creează un pachet de partajare"
          >
            <ShareIcon />
            <span>Partajează</span>
          </button>
          <ThemeToggle />
          <LogoutButton />
        </div>
      </header>
      {error && <p className="error-text nb-error">{error}</p>}

      <nav className="mobile-workspace-nav" aria-label="Panourile carnetului">
        <button
          type="button"
          className={mobilePanel === "materials" ? "active" : ""}
          aria-pressed={mobilePanel === "materials"}
          aria-label="Materiale"
          onClick={() => setMobilePanel("materials")}
        >
          <MaterialsIcon />
          <span>Materiale</span>
        </button>
        <button
          type="button"
          className={mobilePanel === "chat" ? "active" : ""}
          aria-pressed={mobilePanel === "chat"}
          aria-label={conversationMode === "chat" ? "Chat" : "Guguță"}
          onClick={() => setMobilePanel("chat")}
        >
          <ChatIcon />
          <span>{conversationMode === "chat" ? "Chat" : "Guguță"}</span>
        </button>
        <button
          type="button"
          className={mobilePanel === "studio" ? "active" : ""}
          aria-pressed={mobilePanel === "studio"}
          aria-label="Studio"
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
                  <SourceTypeIcon source={source} />
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
                        ).then(() => loadAll())
                      }
                    />
                  </label>
                  <span className={`src-doc source-type-${sourceIconType(s)}`} title={sourceIconType(s) === "book" ? "Carte / PDF" : sourceIconType(s) === "quiz" ? "Test" : sourceIconType(s) === "audio" ? "Audio" : sourceIconType(s) === "video" ? "Video" : "Document"}>
                    {s.mime_type?.startsWith("image/") ? (
                      <button type="button" className="source-image-thumb" onClick={() => setImagePreview(s)} aria-label={`Afișează imaginea ${s.local_name}`}>
                        <img src={`${API_BASE}/api/v1/notebooks/${nbId}/sources/${s.id}/download`} alt={s.local_name} />
                      </button>
                    ) : <SourceTypeIcon source={s} />}
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

        {/* Unmounting the mascot closes voice, microphone capture and its chat requests. */}
        {conversationMode === "companion" ? (
          <section id="notebook-conversation" className={`panel notebook-companion ${mobilePanel === "chat" ? "mobile-active" : ""}`} aria-label="Guguță">
            <EducationCompanion
              assetBase={withBase("/guguta-companion")}
              context={{
                source: "opennotebook", notebookId: nbId, lessonTitle: nb?.title,
                subjectLabel: companionTemplate?.discipline ?? undefined, grade: companionTemplate?.class_level ?? undefined, locale: "ro-MD",
                selectedSourceIds: sources?.filter(source => source.selected_for_chat && source.status === "ready").map(source => source.id).slice(0, 200),
                activeCard: currentStudyCard && studySession && !studySession.completed_at ? { question: currentStudyCard.front } : undefined,
                quizId: activeQuiz?.id,
                activeQuestion: currentQuizQuestion && quizAttempt && !quizAttempt.completed_at ? { prompt: currentQuizQuestion.prompt, options: currentQuizQuestion.options.map(option => option.text), questionType: currentQuizQuestion.question_type } : undefined,
              }}
              sessionId={sessionId ?? undefined}
              activity={nb?.title ?? "Deschidem carnetul"}
              result={quizAttempt?.completed_at ? { correct: Object.values(quizAttempt.answers).filter(answer => answer.status === "correct").length, total: quizAttempt.question_order.length } : undefined}
            />
          </section>
        ) : conversationMode === "chat" ? (
          <section id="notebook-conversation" className={`panel chat ${mobilePanel === "chat" ? "mobile-active" : ""}`} aria-label="Conversație">
            <div className="panel-head">
              <div className="panel-heading-copy">
                <span className="panel-title">Conversație</span>
                <span className="panel-subtitle">Întreabă și explorează materialele selectate.</span>
              </div>
              <button
                className="icon-btn reset-chat-btn"
                onClick={() => void newSession()}
                disabled={sending || uploadingAttachments || resettingChat}
                aria-label="Resetează conversația"
                title="Șterge conversația și atașamentele, apoi începe una nouă"
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
                <div key={m.clientId ?? m.id} className={`msg ${m.role}`}>
                  {m.role === "assistant" ? (
                    <MarkdownContent content={answerText(m.content)} />
                  ) : (
                    m.content
                  )}
                  {m.role === "user" && sessionId && <AttachmentCards
                    attachments={m.attachments ?? chatAttachments.filter((file) => file.chat_message_id === m.id)}
                    notebookId={nbId} sessionId={sessionId}
                  />}
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
                  {streaming !== "" && (
                    <MarkdownContent content={answerText(streaming)} />
                  )}
                  {streaming === "" && (
                    <span className="muted">
                      {elapsed < 15 ? "Se generează…" : `Se generează… ${elapsed}s`}
                    </span>
                  )}
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            <div className="composer has-attachments">
              {sessionId && !resettingChat && <ChatAttachments key={sessionId} notebookId={nbId} sessionId={sessionId}
                disabled={sending || resettingChat} refreshToken={attachmentRefresh + messages.length}
                submittedAttachmentIds={submittedAttachmentIds}
                onChange={setChatAttachments} onBusy={setUploadingAttachments} />}
              {speechMessage || chatMessage ? (
                <p className="composer-notice" role="status" aria-live="polite">
                  {speechMessage ?? chatMessage}
                </p>
              ) : null}
              <textarea
                ref={draftInputRef}
                id="draft"
                className={speechMessage || chatMessage ? "has-composer-notice" : undefined}
                placeholder={
                  sessionId === null
                    ? "Se pregătește conversația…"
                    : "Pune o întrebare despre materiale…"
                }
                value={draft}
                disabled={sessionId === null || transcribing}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <button
                type="button"
                className={`mic-btn ${recording ? "recording" : ""}`}
                onClick={() => void toggleRecording()}
                disabled={!recording && (sending || transcribing || sessionId === null)}
                aria-label={recording ? "Oprește înregistrarea" : "Începe dictarea"}
                aria-pressed={recording}
                title={recording ? "Oprește și transcrie" : transcribing ? "Se transcrie…" : "Dictează întrebarea"}
              >
                {transcribing ? <span className="mic-loader" aria-hidden="true" /> : <MicrophoneIcon />}
              </button>
              <button
                className="send-btn"
                onClick={() => void send()}
                disabled={sending || uploadingAttachments || resettingChat || sessionId === null || !attachmentsReady || (!draft.trim() && !pendingAttachments.length)}
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
        ) : (
          <section id="notebook-conversation" className={`panel chat ${mobilePanel === "chat" ? "mobile-active" : ""}`} aria-label="Conversație">
            <p className="muted chat-hint" role="status">Se pregătește conversația…</p>
          </section>
        )}

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
            {(flashcardDecks?.length || quizzes?.length || audioOverviews?.length || notes?.length) ? (
              <div className="rail-created-list" aria-label="Materiale create">
                {flashcardDecks?.map((deck) => (
                  <button
                    type="button"
                    key={deck.id}
                    className={`rail-action rail-created rail-created-flashcards ${deck.status}`}
                    onClick={() => deck.status === "ready" && void openDeck(deck.id, "all")}
                    disabled={deck.status !== "ready"}
                    tabIndex={studioCollapsed ? 0 : -1}
                    aria-label={`Deschide ${deck.title || "setul de flashcards"}`}
                    title={deck.title || "Flashcards"}
                  >
                    <CardsIcon />
                  </button>
                ))}
                {quizzes?.map((quiz) => (
                  <button
                    type="button"
                    key={quiz.id}
                    className={`rail-action rail-created rail-created-quiz ${quiz.status}`}
                    onClick={() => quiz.status === "ready" && void openQuiz(quiz.id)}
                    disabled={quiz.status !== "ready"}
                    tabIndex={studioCollapsed ? 0 : -1}
                    aria-label={`Deschide ${quiz.title || "quiz-ul"}`}
                    title={quiz.title || "Quiz"}
                  >
                    <QuizIcon />
                  </button>
                ))}
                {audioOverviews?.map((overview) => (
                  <button
                    type="button"
                    key={overview.id}
                    className={`rail-action rail-created rail-created-audio ${overview.status}`}
                    onClick={() => setStudioCollapsed(false)}
                    tabIndex={studioCollapsed ? 0 : -1}
                    aria-label={`Arată ${overview.title || "rezumatul audio"}`}
                    title={overview.title || "Audio Overview"}
                  >
                    <AudioIcon />
                  </button>
                ))}
                {notes?.map((note) => (
                  <button
                    type="button"
                    key={note.id}
                    className="rail-action rail-created rail-created-note"
                    onClick={() => setStudioCollapsed(false)}
                    tabIndex={studioCollapsed ? 0 : -1}
                    aria-label={`Arată ${note.title || "notița"}`}
                    title={note.title || "Notiță"}
                  >
                    <PencilIcon />
                  </button>
                ))}
              </div>
            ) : null}
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
                    <span
                      className="flashcard-deck-icon created-material-icon created-material-icon-cards"
                      aria-hidden="true"
                    >
                      <CardsIcon />
                    </span>
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
                    <span
                      className="flashcard-deck-icon created-material-icon created-material-icon-quiz"
                      aria-hidden="true"
                    >
                      <QuizIcon />
                    </span>
                    <span><strong>{quiz.title||"Quiz"}</strong><small>{quiz.status==="ready"?`${quiz.question_count} întrebări · ${quiz.difficulty==="easy"?"Ușor":quiz.difficulty==="hard"?"Dificil":"Mediu"}`:quiz.status==="failed"?"Generarea a eșuat":"Se generează în fundal…"}</small></span>
                  </button>
                  <button type="button" className="audio-overview-delete" onClick={()=>void removeQuiz(quiz)} aria-label="Șterge quiz-ul"><TrashIcon /></button>
                  {quiz.status==="failed"&&<div className="flashcard-deck-error"><p className="error-text">{quiz.error_detail||"Generarea a eșuat."}</p><button className="pill small" onClick={()=>void retryQuiz(quiz.id)}>Reîncearcă</button></div>}
                </article>
              ))}

              {audioOverviews?.map((overview) => (
                <article className="audio-overview-card" key={overview.id}>
                  <div className="audio-overview-head">
                    <span
                      className="audio-overview-icon created-material-icon created-material-icon-audio"
                      aria-hidden="true"
                    >
                      <AudioIcon />
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
          <header><div><h2>{activeQuiz.title||"Quiz"}</h2><p>Întrebări din materialele selectate</p></div><div className="flashcard-study-actions">{playquizEnabled&&playquizStatus&&<button type="button" className="chip" data-testid="open-in-playquiz" disabled={playquizBusy||!playquizStatus.exportable} title={playquizStatus.exportable?"Se deschide într-o fereastră nouă, pe play-quiz.com":(playquizStatus.reason??"Doar quizurile cu întrebări grilă pot fi deschise în PlayQuiz.")} onClick={()=>playquizStatus.consent_given?void openInPlayQuiz(false):setPlayquizConsentOpen(true)}>{playquizBusy?"Se trimite…":"Deschide în PlayQuiz"}</button>}<button className="icon-btn" onClick={()=>{setActiveQuiz(null);setQuizAttempt(null)}} aria-label="Închide">×</button></div></header>
          {playquizMessage&&<p className="error-text" role="alert">{playquizMessage}</p>}
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
      {playquizConsentOpen&&activeQuiz&&(
        <div className="modal-overlay" role="presentation" onClick={()=>!playquizBusy&&setPlayquizConsentOpen(false)}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="playquiz-consent-title" onClick={(e)=>e.stopPropagation()}>
          <h2 id="playquiz-consent-title">Deschide în PlayQuiz</h2>
          <p>PlayQuiz (play-quiz.com) este o platformă parteneră, separată de Guguță. Ca să joci acolo, Guguță îți creează automat un cont și trimite către PlayQuiz <strong>numele tău afișat și adresa de e-mail</strong>, împreună cu întrebările acestui quiz.</p>
          <p className="muted">Acordul se cere o singură dată. Quizul rămâne oricând disponibil și aici, în Guguță.</p>
          <div className="modal-actions"><button className="chip" onClick={()=>setPlayquizConsentOpen(false)} disabled={playquizBusy}>Nu acum</button><button className="create-btn" data-testid="playquiz-consent-accept" onClick={()=>void openInPlayQuiz(true)} disabled={playquizBusy}>{playquizBusy?"Se trimite…":"Sunt de acord, deschide"}</button></div>
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
                <p className="muted">Explicația materialelor tale în limba română</p>
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

            <label className="flashcard-instructions">
              <span>Pe ce să se concentreze explicația?</span>
              <textarea
                value={audioInstructions}
                onChange={(event) => setAudioInstructions(event.target.value)}
                maxLength={4000}
                placeholder="Opțional: concepte-cheie, comparații, exemple sau întrebări de clarificat…"
              />
            </label>
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
      {imagePreview && <PrivateImagePreview
        url={`${API_BASE}/api/v1/notebooks/${nbId}/sources/${imagePreview.id}/download`}
        name={imagePreview.local_name} onClose={() => setImagePreview(null)} />}
    </div>
  );
}
