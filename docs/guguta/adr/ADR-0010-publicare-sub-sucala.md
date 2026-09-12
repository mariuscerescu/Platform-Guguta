# ADR-0010: Publicare sub subcale (`/edu-platform`) și stack de producție în Docker

Stare: acceptat · Data: 12 septembrie 2026
Referințe: ADR-0007 (roluri de bază de date), GHID §10.2–§10.3; checklist F26.

## Context

Platforma trebuie să ruleze pe serverul instituțional, la
`https://tineri.math.md/edu-platform`, în containere Docker, alături de
aplicațiile existente (`/datasetBuilder/`, `/voiceRecording/` — stack-ul
`ttsdatasetbuilder`). Serverul are deja un nginx care termină TLS pentru domeniu
și aplicațiile existente își taie prefixul de cale cu un nginx intern, pentru că
sunt aplicații montate pe `root_path`.

Pentru un frontend Next.js, tăierea prefixului nu funcționează: rutele
clientului, activele și linkurile ar pierde prefixul. Varianta corectă este
`basePath`, care cere însă ca fiecare cale scrisă manual în browser să fie
prefixată.

Constrângeri de configurație care contează în producție: în afara
`development`/`ci`, `GugutaConfig` refuză secretele implicite, originile `http`,
furnizorii simulați și cere ca ambele roluri de runtime ale bazei de date să fie
declarate.

## Decizie

1. **Un singur punct public: frontend-ul.** Doar containerul `frontend` este
   publicat, pe `127.0.0.1:8300`. API-ul, worker-ul și baza de date nu au port
   pe gazdă. Browserul vorbește cu o singură origine, deci cookie-ul de sesiune
   (`SameSite=Lax`) circulă fără CORS; API-ul rămâne accesibil prin proxy-ul
   same-origin `/edu-platform/guguta-api/*` (`next rewrites`).
2. **`basePath` din `NEXT_PUBLIC_BASE_PATH`**, citit în `next.config.ts`. Toate
   căile absolute din browser trec prin `frontend-guguta/lib/paths.ts`
   (`withBase()`, `API_BASE`). `next/link` și `useRouter()` primesc prefixul
   automat și rămân neatinse.
3. **`basePath` se declară în AMBELE stagii ale imaginii de frontend.** `next
   start` recitește `next.config.ts` la pornire: dacă `ENV`-ul există doar în
   stagiul de build, build-ul are prefixul (active, surse de rewrites), iar
   serverul caută rutele fără el și răspunde 404 la tot.
4. **Fără nginx intern în stack.** Prefixul nu se taie, deci nu e nevoie de un
   al doilea nivel de proxy; gazda trimite calea întreagă către `127.0.0.1:8300`.
5. **Un singur fișier `.env`**, în `deploy/edu-platform/`, folosit și pentru
   interpolarea din compose, și ca `env_file` al containerelor. DSN-urile se
   compun în compose (nume de gazdă Docker), nu în `.env`.
6. **Toate cele trei DSN-uri se dau API-ului și worker-ului.** Validarea de
   producție cere ca ambele roluri de runtime să fie declarate; fiecare proces se
   conectează oricum doar cu rolul lui (ADR-0007).

## Consecințe

- **Cod nou care atinge browserul trebuie să folosească `withBase()` sau
  `API_BASE`.** Un `<a href="/app">`, un `window.location.href = "/app"`, un
  `<img src="/assets/...">` sau un `fetch("/guguta-api/...")` scris direct duc
  utilizatorul în afara aplicației pe server, chiar dacă local par corecte
  (local `basePath` este gol). Selectorii CSS care depind de valoarea exactă a
  unui `href` trebuie scriși relativ (`a[href$="/import"]`).
- Schimbarea prefixului cere **rebuild** (`docker compose build frontend`), nu
  doar restart: valoarea intră în bundle-ul de client.
- `GUGUTA_PUBLIC_ORIGIN` este originea fără cale (`https://tineri.math.md`).
  Antetul `Origin` trimis de browser nu conține niciodată calea; cu calea
  inclusă, fiecare mutație cu cookie este respinsă cu 403 `origin_rejected`.
- Gazda trebuie să seteze `client_max_body_size` (implicit 1 MiB taie
  materialele de până la 25 MiB) și `proxy_buffering off` (altfel răspunsul de
  chat, trimis în flux, apare dintr-o dată la final).
- `.dockerignore` exclude `frontend-guguta/node_modules` și `.next`: altfel
  modulele de pe gazdă (Windows) ajung, prin `COPY frontend-guguta ./`, peste
  cele instalate în container.
- Publicarea pe un alt server/subcale cere doar `GUGUTA_BASE_PATH`,
  `GUGUTA_PUBLIC_ORIGIN`, `GUGUTA_CORS_ORIGINS` și blocul `location`
  corespunzător — fără modificări de cod.
