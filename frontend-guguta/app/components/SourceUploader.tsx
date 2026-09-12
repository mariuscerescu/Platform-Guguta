"use client";

/**
 * SourceUploader — adăugarea materialelor, redusă la minimum.
 *
 * Un buton deschide direct file manager-ul sistemului. Cât timp aplicația
 * lucrează la un fișier, acesta apare într-o singură linie: numele lui și
 * animația rotundă de încărcare. Nimic altceva — fără bară de progres, fără
 * procente, fără texte de status.
 *
 * Când serverul a primit fișierul, linia dispare și materialul preia ștafeta
 * în lista carnetului: dacă workerul îl mai procesează, în dreptul lui se
 * învârte același cerc; când procesarea se termină, cercul dispare și rămâne
 * doar fișierul. Un singur indicator de loading per material, niciodată două.
 *
 * Procentul de upload nu se mai afișează, dar `XMLHttpRequest` rămâne
 * folosit: spre deosebire de `fetch`, el nu are nevoie de corp citit manual
 * și semnalează erorile de rețea distinct.
 */

import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { getCsrf, type Source } from "../../lib/api";
import { API_BASE } from "../../lib/paths";

const ACCEPT = ".pdf,.docx,.pptx,.txt,.md";
const ALLOWED_EXT = ["pdf", "docx", "pptx", "txt", "md"];
const MAX_MIB = 25;
const MAX_BYTES = MAX_MIB * 1024 * 1024;

/** Linia există cât timp aplicația lucrează la fișier, sau când a eșuat. */
type Stage = "working" | "error";

interface UploadItem {
  key: string;
  name: string;
  stage: Stage;
  message: string | null;
}

interface SourceUploaderProps {
  notebookId: string;
  /**
   * Materialul creat, livrat sincron în momentul în care serverul răspunde.
   * Lista îl primește în același render în care linia temporară dispare, deci
   * fișierul nu apare niciodată de două ori și nici nu clipește.
   */
  onUploaded: (source: Source) => void;
  /** Reconciliere în fundal (ordine, câmpuri complete) după upload. */
  onChanged: () => void | Promise<void>;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Trimite fișierul; rezolvă cu materialul creat de server. */
function postFile(notebookId: string, file: File): Promise<Source> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/v1/notebooks/${notebookId}/sources/file`);
    xhr.withCredentials = true;
    const csrf = getCsrf();
    if (csrf) xhr.setRequestHeader("X-Guguta-CSRF", csrf);
    xhr.onload = () => {
      let payload: {
        source?: Partial<Source>;
        message?: string;
        detail?: string;
      } = {};
      try {
        payload = JSON.parse(xhr.responseText) as typeof payload;
      } catch {
        payload = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        const created = payload.source;
        if (!created?.id) {
          reject(new Error("Răspuns neașteptat de la server."));
          return;
        }
        resolve({
          id: String(created.id),
          local_name: String(created.local_name ?? file.name),
          status: String(created.status ?? "processing"),
          status_detail: created.status_detail ?? null,
          selected_for_chat: created.selected_for_chat ?? true,
          material_version_id: String(created.material_version_id ?? ""),
        });
        return;
      }
      reject(
        new Error(
          payload.message ??
            payload.detail ??
            `Încărcarea a eșuat (cod ${xhr.status}).`,
        ),
      );
    };
    xhr.onerror = () =>
      reject(new Error("Conexiunea s-a întrerupt în timpul încărcării."));
    xhr.ontimeout = () => reject(new Error("Încărcarea a expirat."));
    xhr.send(form);
  });
}

export default function SourceUploader({
  notebookId,
  onUploaded,
  onChanged,
}: SourceUploaderProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const aliveRef = useRef(true);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  // ref, nu dependență: lanțul de upload pornit acum nu trebuie să țină
  // o versiune veche a callback-urilor părinte
  const onUploadedRef = useRef(onUploaded);
  const onChangedRef = useRef(onChanged);
  const [items, setItems] = useState<UploadItem[]>([]);

  useEffect(() => {
    onUploadedRef.current = onUploaded;
    onChangedRef.current = onChanged;
  }, [onUploaded, onChanged]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const patch = useCallback((key: string, next: Partial<UploadItem>) => {
    setItems((prev) =>
      prev.map((it) => (it.key === key ? { ...it, ...next } : it)),
    );
  }, []);

  const dismiss = useCallback((key: string) => {
    setItems((prev) => prev.filter((it) => it.key !== key));
  }, []);

  const processOne = useCallback(
    async (key: string, file: File) => {
      const alive = () => aliveRef.current;
      const fail = (message: string) =>
        patch(key, { stage: "error", message });

      // verificări locale: nu trimitem 25 MiB ca să aflăm că formatul e greșit
      if (file.size === 0) {
        fail("Fișierul este vid.");
        return;
      }
      if (file.size > MAX_BYTES) {
        fail(`Fișierul are ${formatSize(file.size)}, peste limita de ${MAX_MIB} MiB.`);
        return;
      }
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!ALLOWED_EXT.includes(ext)) {
        fail("Format neacceptat. Folosește PDF, DOCX, PPTX, TXT sau MD.");
        return;
      }

      let created: Source;
      try {
        created = await postFile(notebookId, file);
      } catch (err) {
        if (alive()) fail((err as Error).message);
        return;
      }
      if (!alive()) return;

      // Ambele actualizări se aplică în același render: materialul intră în
      // listă (cu cercul lui de procesare) exact când linia temporară iese.
      // Așa nu există nici o clipă cu două reprezentări ale aceluiași fișier.
      onUploadedRef.current(created);
      dismiss(key);
      // apoi reconciliem în fundal (ordine, câmpuri complete din server)
      void onChangedRef.current();
    },
    [notebookId, patch, dismiss],
  );

  const enqueue = useCallback(
    (files: File[]) => {
      const created: UploadItem[] = files.map((file, i) => ({
        key: `${Date.now()}-${i}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        stage: "working",
        message: null,
      }));
      setItems((prev) => [...created, ...prev]);
      // secvențial: upload-urile concurente se blochează oricum între ele pe
      // rândul de utilizator din bază (SELECT ... FOR UPDATE)
      created.forEach((item, i) => {
        const file = files[i];
        queueRef.current = queueRef.current
          .then(() => processOne(item.key, file))
          .catch(() => undefined);
      });
    },
    [processOne],
  );

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // permite re-alegerea aceluiași fișier
    if (files.length > 0) enqueue(files);
  }

  return (
    <div className="add-src">
      <button
        type="button"
        className="add-src-btn"
        onClick={() => inputRef.current?.click()}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
        </svg>
        Adaugă sursă
      </button>
      <input
        ref={inputRef}
        id="src-file-input"
        type="file"
        multiple
        accept={ACCEPT}
        className="file-input-hidden"
        aria-label="Alege fișierele din calculator"
        onChange={onPick}
      />

      {items.length > 0 && (
        <ul className="upload-list" aria-live="polite">
          {items.map((it) => (
            <li key={it.key} className={`upload-item ${it.stage}`}>
              {it.stage === "error" ? (
                <span className="upload-icon error" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <path d="M12 7v7M12 17.5v.5" strokeLinecap="round" />
                    <circle cx="12" cy="12" r="9" />
                  </svg>
                </span>
              ) : (
                <span className="upload-icon" aria-hidden="true">
                  <span className="spinner" />
                </span>
              )}

              <span className="upload-body">
                <span className="upload-name" title={it.name}>
                  {it.name}
                </span>
                {it.stage === "error" && (
                  <span className="upload-error">{it.message}</span>
                )}
              </span>

              {it.stage === "error" && (
                <button
                  type="button"
                  className="src-act"
                  onClick={() => dismiss(it.key)}
                  title="Elimină din listă"
                  aria-label={`Elimină ${it.name} din listă`}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
