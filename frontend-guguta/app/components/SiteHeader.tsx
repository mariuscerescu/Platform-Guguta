"use client";

import { usePathname } from "next/navigation";
import AuthEntryLink from "./AuthEntryLink";
import { withBase } from "../../lib/paths";

/**
 * Header-ul platformei.
 *
 * Două lucruri depind de rută, de aceea header-ul e componentă de client:
 *
 * 1. Culoarea. Pe pagina de start e alb și se lipește de cardul alb al
 *    landing-ului; pe celelalte pagini ia nuanța de fundal a paginii, ca să nu
 *    se vadă o bandă albă deasupra conținutului.
 * 2. Butonul „Intră în cont", care apare doar pe pagina de start: vizitator →
 *    logare, autentificat → carnetele lui. Pe celelalte pagini header-ul rămâne
 *    fără buton de cont.
 *
 * `usePathname()` poate include sau nu `basePath` (depinde de versiune), așa că
 * potrivirea acceptă ambele forme — altfel ambele particularități ar dispărea
 * exact în producție, unde platforma e servită sub `/edu-platform`.
 */
export default function SiteHeader() {
  const pathname = usePathname();
  const isLanding =
    pathname === "/" || pathname === "" || pathname === withBase("/");

  return (
    <header className={isLanding ? "header header-landing" : "header header-inner"}>
      <a href={withBase("/")} className="wordmark" aria-label="Guguță">
        <span>Guguță</span>
      </a>
      <nav className="top-nav" aria-label="Navigare principală">
        <a href={withBase("/import")}>Importă</a>
      </nav>
      {isLanding && (
        <div className="header-actions">
          <AuthEntryLink className="header-login" next="/app">
            Intră în cont
          </AuthEntryLink>
        </div>
      )}
    </header>
  );
}
