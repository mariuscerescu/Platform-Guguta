"use client";

import { useEffect, useRef } from "react";

export default function PrivateImagePreview({ url, name, onClose }: {
  url: string; name: string; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return (
    <dialog ref={dialog} className="private-image-preview" onCancel={onClose} onClose={onClose}>
      <div className="image-preview-head"><span>{name}</span>
        <button type="button" onClick={onClose} aria-label="Închide imaginea">×</button>
      </div>
      <img src={url} alt={name} />
    </dialog>
  );
}
