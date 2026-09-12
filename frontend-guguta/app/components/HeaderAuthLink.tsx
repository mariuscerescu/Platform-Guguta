"use client";

import { usePathname } from "next/navigation";
import AuthEntryLink from "./AuthEntryLink";
import { withBase } from "../../lib/paths";

/**
 * Butonul „Intră în cont" din header — apare **doar pe pagina de start**.
 *
 * Pe celelalte pagini header-ul nu are buton de cont (decizie de produs), așa
 * că aici se ascunde singur. Butonul e prezent mereu pe landing, indiferent de
 * sesiune; destinația o hotărăște `AuthEntryLink`: vizitator → logare,
 * autentificat → carnetele lui.
 */
export default function HeaderAuthLink() {
  const pathname = usePathname();
  // `usePathname()` poate include sau nu `basePath` (depinde de versiune), așa
  // că acceptăm ambele forme — altfel butonul ar dispărea exact în producție.
  const isLanding =
    pathname === "/" || pathname === "" || pathname === withBase("/");

  if (!isLanding) return null;

  return (
    <div className="header-actions">
      <AuthEntryLink className="header-login" next="/app">
        Intră în cont
      </AuthEntryLink>
    </div>
  );
}
