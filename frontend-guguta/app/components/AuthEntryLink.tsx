"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { authMode, me } from "../../lib/api";
import { withBase, API_BASE } from "../../lib/paths";

type AuthUser = { display_name: string };

type AuthEntryLinkProps = {
  className?: string;
  /** Eticheta afișată când vizitatorul NU este autentificat. */
  children: ReactNode;
  next?: string;
  /**
   * Randat doar pentru vizitatori: după autentificare componenta nu mai
   * afișează nimic. Header-ul o cere așa — locul butonului „Intră în cont"
   * rămâne gol după login (fără buton și fără numele utilizatorului).
   *
   * Cât timp starea de autentificare nu e cunoscută, nu se randează nimic:
   * altfel „Intră în cont" ar apărea o clipă și pentru cine e deja autentificat.
   */
  hideWhenSignedIn?: boolean;
};

function safeNext(value: string): string {
  return value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}

function oidcLoginHref(next: string): string {
  return `${API_BASE}/api/v1/auth/oidc/login?next=${encodeURIComponent(withBase(safeNext(next)))}`;
}

export default function AuthEntryLink({
  className,
  children,
  next = "/app",
  hideWhenSignedIn = false,
}: AuthEntryLinkProps) {
  const [href, setHref] = useState(withBase("/login"));
  const [user, setUser] = useState<AuthUser | null>(null);
  const [resolved, setResolved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const found = await me();
      if (cancelled) return;
      if (found) {
        setUser(found);
        setHref(withBase(safeNext(next)));
        setResolved(true);
        return;
      }
      const mode = await authMode();
      if (cancelled) return;
      setHref(mode === "oidc" ? oidcLoginHref(next) : withBase("/login"));
      setResolved(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [next]);

  if (hideWhenSignedIn && (!resolved || user)) return null;

  return (
    <a href={href} className={className}>
      {children}
    </a>
  );
}
