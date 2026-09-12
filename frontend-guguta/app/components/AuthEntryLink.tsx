"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { authMode, me } from "../../lib/api";
import { withBase, API_BASE } from "../../lib/paths";

type AuthEntryLinkProps = {
  className?: string;
  children: ReactNode;
  next?: string;
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
}: AuthEntryLinkProps) {
  const [href, setHref] = useState(withBase("/login"));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const user = await me();
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
