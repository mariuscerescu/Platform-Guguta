"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { authMode, me } from "../../lib/api";
import { withBase, API_BASE } from "../../lib/paths";

type AuthUser = { display_name: string };

type AuthEntryLinkProps = {
  className?: string;
  /** Eticheta butonului (ex. „Accesează materialele din platformă"). */
  children: ReactNode;
  /** Unde ajunge utilizatorul autentificat. */
  next?: string;
};

function safeNext(value: string): string {
  return value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}

function oidcLoginHref(next: string): string {
  return `${API_BASE}/api/v1/auth/oidc/login?next=${encodeURIComponent(withBase(safeNext(next)))}`;
}

/**
 * Intrarea în cont. Se folosește **doar pe pagina de start** — header-ul nu are
 * buton de cont, ca să nu urmărească utilizatorul pe fiecare pagină.
 *
 * Vizitator: duce la autentificare (parolă sau OIDC, după cum e configurat
 * serverul). Autentificat: duce direct la carnetele lui.
 */
export default function AuthEntryLink({
  className,
  children,
  next = "/app",
}: AuthEntryLinkProps) {
  const [href, setHref] = useState(withBase("/login"));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const user: AuthUser | null = await me();
      if (cancelled) return;
      if (user) {
        setHref(withBase(safeNext(next)));
        return;
      }
      const mode = await authMode();
      if (cancelled) return;
      setHref(mode === "oidc" ? oidcLoginHref(next) : withBase("/login"));
    })();
    return () => {
      cancelled = true;
    };
  }, [next]);

  return (
    <a href={href} className={className}>
      {children}
    </a>
  );
}
