"use client";

import { useEffect, useRef, useState } from "react";
import { api, Notebook } from "../../lib/api";

type NotebookMenuProps = {
  notebook: Notebook;
  /** Reîncarcă lista după o acțiune reușită. */
  onChanged: () => void | Promise<void>;
  /** Afișează eroarea în pagina care găzduiește cardul. */
  onError: (message: string) => void;
};

const IconPencil = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M4 20h4l10-10-4-4L4 16z" strokeLinejoin="round" />
    <path d="m14 6 4 4" strokeLinecap="round" />
  </svg>
);
const IconPin = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M9 4h6l-1 6 3 3H7l3-3z" strokeLinejoin="round" />
    <path d="M12 13v7" strokeLinecap="round" />
  </svg>
);
const IconTrash = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * Meniul unui carnet din listă: redenumire, fixare sus și ștergere.
 *
 * Butonul exista și înainte, dar nu avea nicio acțiune legată. Acțiunile stau
 * aici, în listă, ca să nu mai fie nevoie să intri în carnet pentru ele.
 */
export default function NotebookMenu({
  notebook,
  onChanged,
  onError,
}: NotebookMenuProps) {
  const [open, setOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(notebook.title);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Închidere la click în afară și la Escape; altfel meniul rămâne deschis
  // când utilizatorul apasă oriunde altundeva în pagină.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (renaming) inputRef.current?.focus();
  }, [renaming]);

  function close() {
    setOpen(false);
    setRenaming(false);
  }

  async function rename() {
    const next = title.trim();
    if (!next || next === notebook.title) {
      close();
      return;
    }
    setBusy(true);
    try {
      await api("PATCH", `/api/v1/notebooks/${notebook.id}`, { title: next });
      await onChanged();
      close();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function togglePin() {
    setBusy(true);
    try {
      await api("PATCH", `/api/v1/notebooks/${notebook.id}`, {
        pinned: !notebook.pinned,
      });
      await onChanged();
      close();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`Ștergi definitiv carnetul „${notebook.title}"?`)) return;
    setBusy(true);
    try {
      await api("DELETE", `/api/v1/notebooks/${notebook.id}`);
      await onChanged();
      close();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="nb-menu"
      ref={rootRef}
      // Cardul întreg e un link către carnet: fără oprire, orice click în meniu
      // ar deschide carnetul.
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        aria-label="Meniu carnet"
        aria-expanded={open}
        aria-haspopup="menu"
        title="Meniu carnet"
        onClick={() => (open ? close() : setOpen(true))}
      >
        ⋮
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          {renaming ? (
            <form
              className="menu-rename"
              onSubmit={(e) => {
                e.preventDefault();
                void rename();
              }}
            >
              <input
                ref={inputRef}
                value={title}
                aria-label="Titlul nou"
                maxLength={500}
                onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") close();
                }}
              />
              <div className="menu-rename-actions">
                <button type="submit" className="pill small" disabled={busy || !title.trim()}>
                  Salvează
                </button>
                <button type="button" className="pill small" onClick={close}>
                  Renunță
                </button>
              </div>
            </form>
          ) : (
            <>
              <button
                type="button"
                role="menuitem"
                disabled={busy}
                onClick={() => setRenaming(true)}
              >
                <IconPencil />
                <span>Redenumește</span>
              </button>
              <button type="button" role="menuitem" disabled={busy} onClick={togglePin}>
                <IconPin />
                <span>{notebook.pinned ? "Anulează fixarea" : "Fixează sus"}</span>
              </button>
              <button
                type="button"
                role="menuitem"
                className="danger"
                disabled={busy}
                onClick={remove}
              >
                <IconTrash />
                <span>Șterge</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
