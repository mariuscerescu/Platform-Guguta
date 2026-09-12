/**
 * Căile publice ale aplicației, într-un singur loc (F26 — publicare sub subcale).
 *
 * În producție platforma e servită sub `https://tineri.math.md/edu-platform`,
 * deci fiecare cale absolută din browser trebuie să includă acel prefix:
 * linkuri simple (`<a>`, nu `<Link>`), `window.location`, imagini din `/public`
 * și apelurile către API. `next/link` și `useRouter()` primesc prefixul
 * automat din `basePath`, de aceea nu apar aici.
 *
 * `NEXT_PUBLIC_BASE_PATH` se citește la BUILD (Next o inline-uiește în
 * bundle-ul clientului), deci valoarea din imaginea construită este cea care
 * contează. Gol (`""`) = servit pe rădăcină, cum e în dezvoltare locală.
 */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Prefixul proxy-ului same-origin către API (`next.config.ts` → rewrites). */
export const API_BASE = `${BASE_PATH}/guguta-api`;

/**
 * Prefixează o cale absolută a aplicației cu `basePath`.
 *
 * `withBase("/")` întoarce exact rădăcina publicată, fără slash final, ca să
 * nu depindem de redirectul Next pentru `/edu-platform/`.
 */
export function withBase(path: string): string {
  if (path === "/") return BASE_PATH === "" ? "/" : BASE_PATH;
  return `${BASE_PATH}${path}`;
}
