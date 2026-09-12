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
   * Ce se afișează după autentificare. Proprietate simplă, nu funcție: link-ul
   * e randat și din layout-ul server, iar o funcție nu poate traversa granița
   * server → client (Next ar refuza randarea întregii pagini).
   *   "display_name" — numele utilizatorului; header-ul îl cere așa.
   */
  signedIn?: "display_name";
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
  signedIn,
}: AuthEntryLinkProps) {
  const [href, setHref] = useState(withBase("/login"));
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const found = await me();
      if (cancelled) return;
      if (found) {
        setUser(found);
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
      {user && signedIn === "display_name" ? user.display_name : children}
    </a>
  );
}
