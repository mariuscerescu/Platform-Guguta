"use client";

import { usePathname } from "next/navigation";
import AuthEntryLink from "./AuthEntryLink";
import { withBase } from "../../lib/paths";

/**
 * Header-ul platformei.
 *
 * Două lucruri depind de rută, de aceea header-ul e componentă de client:
 *
 * 1. Culoarea. Pe rutele al căror conținut începe cu un card alb lipit de
 *    header (pagina de start, logare, înregistrare) header-ul e alb, cu același
 *    chenar ca cardul, ca să se citească drept o singură suprafață; pe celelalte
 *    pagini ia nuanța de fundal a paginii, ca să nu se vadă o bandă străină
 *    deasupra conținutului. Pe logare și înregistrare cardul are și un gradient,
 *    iar header-ul pictează aceeași imagine (`.header-auth`), decupată cu
 *    înălțimea lui mai sus: gradientul continuă din pagină în header, fără
 *    muchie la îmbinare.
 * 2. Butonul „Intră în cont", care apare doar pe pagina de start: vizitator →
 *    logare, autentificat → carnetele lui. Pe celelalte pagini header-ul rămâne
 *    fără buton de cont.
 *
 * `usePathname()` poate include sau nu `basePath` (depinde de versiune), așa că
 * potrivirea acceptă ambele forme — altfel ambele particularități ar dispărea
 * exact în producție, unde platforma e servită sub `/edu-platform`.
 */

/** Rute al căror prim bloc e un card alb, lipit de marginea de jos a header-ului. */
const CARD_ROUTES = ["/", "/login", "/register"];

/** Rute la care header-ul și cardul pictează aceeași imagine de fundal. */
const AUTH_ROUTES = ["/login", "/register"];

function matchesRoute(pathname: string, route: string): boolean {
  if (pathname === route || pathname === withBase(route)) return true;
  // pagina de start poate apărea și ca șir vid
  return route === "/" && pathname === "";
}

export default function SiteHeader() {
  const pathname = usePathname();
  const isLanding = matchesRoute(pathname, "/");
  const isLibraryPage = matchesRoute(pathname, "/app");
  const isImportPage = matchesRoute(pathname, "/import");
  // Cardul de logare/înregistrare are exact același chenar ca header-ul: dacă
  // header-ul ar lua fundalul paginii, s-ar vedea o dungă albastră între ele.
  const isCardPage = CARD_ROUTES.some((route) => matchesRoute(pathname, route));
  const isAuthPage = AUTH_ROUTES.some((route) => matchesRoute(pathname, route));
  const isProductPage =
    isLibraryPage ||
    isImportPage ||
    pathname.startsWith("/notebook/") ||
    pathname.startsWith(`${withBase("")}/notebook/`);
  const headerClass = [
    "header",
    isCardPage ? "header-card" : "header-inner",
    isAuthPage ? "header-auth" : null,
    isProductPage ? "header-product" : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <header className={headerClass}>
      <a href={withBase("/")} className="wordmark" aria-label="Platforma educațională Guguță" title="Platforma educațională Guguță">
        <span>Platforma educațională Guguță</span>
      </a>
      <nav className="top-nav" aria-label="Navigare principală">
        {isProductPage && (
          <a href={withBase("/app")} aria-current={isLibraryPage ? "page" : undefined}>
            Carnetele mele
          </a>
        )}
        <a href={withBase("/import")} aria-current={isImportPage ? "page" : undefined}>
          Importă
        </a>
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
