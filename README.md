<div align="center">
  <img src="frontend-guguta/public/assets/guguta-mascot.png" alt="Guguță" width="150">
  <h1>Guguță</h1>
  <p><strong>Platformă educațională pentru elevii din Republica Moldova</strong></p>
  <p>
    <a href="https://tineri.math.md/edu-platform">Instanța publică</a>
    ·
    <a href="docs/guguta/SPECIFICATII_GUGUTA.md">Specificații</a>
    ·
    <a href="docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md">Starea implementării</a>
    ·
    <a href="deploy/edu-platform/README.md">Instalare pe server</a>
  </p>
</div>

Elevul își construiește *carnete digitale* din materialele de studiu — manuale,
notițe, prezentări — și învață din ele prin conversație, cu citări din materialele
selectate.

Proiectul este un fork al [Open Notebook](https://github.com/lfnovo/open-notebook)
(licență MIT), cu fundația tehnică înlocuită: PostgreSQL + pgvector în loc de
SurrealDB, identitate proprie și izolare pe utilizator.

## Ce face produsul

- **Carnete digitale** — un carnet pornește dintr-un șablon pregătit de echipa
  Guguță (de exemplu „Clasa a V-a", cu manualele relevante) sau de la zero.
  Pornirea dintr-un șablon creează o **copie personală**: elevul poate adăuga și
  elimina materiale, inclusiv cele inițiale.
- **Materiale** — PDF cu text, DOCX, PPTX, TXT/Markdown și text introdus direct.
  Extragerea textului și indexarea vectorială rulează în fundal, într-un worker;
  materialul apare ca „se procesează" până devine utilizabil.
- **Conversație** — întrebări despre materialele selectate ale carnetului, cu
  răspuns trimis în flux (SSE). Afișarea listei de referințe sub răspuns este
  momentan dezactivată în interfață, prin decizie
  ([ADR-0009](docs/guguta/adr/ADR-0009-referinte-dezactivate-in-raspuns.md));
  marcajele și validarea citărilor din pipeline rămân active.
- **Partajare** — prin link sau cod, ca pachet fix. Destinatarul primește o
  copie independentă, pe care o stăpânește; autorul nu vede activitatea
  destinatarilor, iar revocarea blochează doar importurile viitoare.
- **Catalog și roluri** — catalog de șabloane administrat de echipă; roluri de
  utilizator, editor de catalog și administrator.
- **Interfață în română** (`ro-MD`), fără chei sau furnizori aleși de elev:
  configurarea AI este centrală.

## Stare

**MVP în dezvoltare, nu pregătit pentru elevi reali.** Progresul pe etape
(L0–L10) și dovezile sunt în
[checklistul de implementare](docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md).

Verificat funcțional pe stack-ul containerizat (12 septembrie 2026): cont nou din
interfață, sesiune pe cookie de server, creare de carnet, urcare de material
procesat de worker până la starea `ready`, răspuns real al modelului afișat în
interfață și publicare sub subcale prin nginx.

Limite cunoscute, în lucru:

- auditul din 6 septembrie 2026 a dat **NO-GO pentru pilot**, cu constatări
  deschise (o parte rezolvate ulterior) —
  [raportul de audit](docs/guguta/AUDIT_IMPLEMENTARE_2026-09-06.md);
- panourile nu sunt utilizabile pe ecrane mici (sub 1024px);
- flashcard-urile, quiz-urile și prezentarea audio sunt etape ulterioare;
- importul din URL, YouTube, audio/video și OCR nu sunt incluse în MVP.

## Arhitectură

```
browser
  └── frontend-guguta     Next.js 15 (App Router), română — port 3001
        └── /guguta-api/*     proxy same-origin (next.config.ts)
              └── api         FastAPI — port 5055, rute sub /api/v1
                    ├── PostgreSQL 17 + pgvector   date, căutare vectorială,
                    │                              joburi, migrări (Alembic)
                    └── worker   python -m open_notebook.jobs.guguta.worker
                          └── stocare fișiere (volum) + furnizor LLM
```

| Componentă | Rol | Porturi |
| --- | --- | --- |
| `frontend-guguta/` | Interfața produsului (Next.js) | 3001 în dezvoltare · 3101 → 3001 în stack-ul local |
| `api/` + `open_notebook/` | API-ul FastAPI și logica de domeniu | 5055; 5056 → 5055 în dezvoltare |
| `open_notebook/jobs/guguta/` | Worker-ul de procesare (materiale, indexare) | — |
| PostgreSQL + pgvector | Date, vectori, coada de joburi, migrări | 5433 → 5432 în dezvoltare |
| `deploy/edu-platform/` | Stack-ul de producție pentru server | 8300 (doar loopback) |

Browserul vorbește doar cu frontend-ul; cookie-ul de sesiune (`SameSite=Lax`)
circulă fără CORS, iar API-ul este accesat prin proxy-ul same-origin
`/guguta-api/*`. Rutele API: `/api/v1/auth`, `/api/v1/notebooks` (cu `/sources`,
`/sessions`, `/notes`, `/search`), `/api/v1/jobs`, `/api/v1/catalog/templates`,
`/api/v1/imports`, `/api/v1/admin`. Pentru operare: `/healthz`, `/readyz`
(verifică și schema) și `/versionz`.

Componentele din upstream care **nu** fac parte din produs: `frontend/`
(interfața originală Open Notebook) și SurrealDB. Deciziile de arhitectură sunt
consemnate în [docs/guguta/adr/](docs/guguta/adr/).

## Pornire locală

Nevoie: Docker, Python 3.11+ cu [uv](https://docs.astral.sh/uv/), Node.js 20+.

### 1. Configurarea

```bash
cp .env.guguta.example .env.guguta.local
```

Fișierul `.env.guguta.local` este ignorat de git. Completează acolo furnizorul
AI: `GUGUTA_OPENROUTER_API_KEY` și modelele (`GUGUTA_OPENROUTER_CHAT_MODEL`,
`..._EMBEDDING_MODEL`, `..._RERANK_MODEL`). Modelele de embedding Nemotron cer
`GUGUTA_EMBEDDING_DIMENSION=2048`.

### 2. Baza de date și migrările

```bash
docker compose -f docker-compose.guguta.yml --project-name guguta up -d db
docker compose -f docker-compose.guguta.yml --project-name guguta run --rm migrator
```

Migrările rulează **doar** prin serviciul `migrator` ([ADR-0007](docs/guguta/adr/ADR-0007-acces-date-rls.md));
API-ul și worker-ul nu ating niciodată schema la pornire.

### 3. API-ul și worker-ul

```bash
docker compose -f docker-compose.guguta.yml --project-name guguta up -d api worker
curl -s http://127.0.0.1:5056/readyz
```

Worker-ul este obligatoriu: fără el, materialele rămân pentru totdeauna în starea
„se procesează".

### 4. Interfața

```bash
cd frontend-guguta
npm install
npm run dev
```

Se deschide <http://localhost:3001>. În dezvoltare, interfața proxează
`/guguta-api/*` către `http://localhost:5056`; se schimbă cu `GUGUTA_API_URL`.

### Alternativa: tot stack-ul în containere

```bash
docker compose -f docker-compose.guguta.yml --project-name guguta up -d --build
```

Aceeași aplicație, interfața pe <http://127.0.0.1:3101>.

## Teste

```bash
docker compose -f docker-compose.guguta.yml --project-name guguta up -d db
uv run pytest tests/guguta        # 93 trecute, 1 sărită (12 septembrie 2026)
```

Testele de integrare folosesc PostgreSQL real (roluri separate, izolare pe rând,
migrări) și se sar singure dacă baza de date nu este accesibilă. Restul suitei:
`uv run pytest tests/`. Verificări statice: `uv run ruff check .`,
`uv run python -m mypy .`.

## Publicare pe server

Stack-ul de producție este în
[deploy/edu-platform/](deploy/edu-platform/README.md): compose complet (interfață,
API, worker, migrator, PostgreSQL + pgvector), `.env` de producție, blocul
`location` pentru nginx-ul gazdă și ghidul de instalare, verificare și depanare.

```bash
cd deploy/edu-platform
cp .env.example .env      # completează secretele; fișierul este ignorat de git
docker compose up -d --build
```

## Structura proiectului

| Cale | Conținut |
| --- | --- |
| `frontend-guguta/` | Interfața Guguță (Next.js, App Router) |
| `open_notebook/` | Domeniu, acces la date, AI, autentificare, joburi |
| `api/` | API-ul FastAPI (`api/routers/guguta_v1.py`) |
| `alembic/` | Migrările de schemă (revizia curentă: `0013`) |
| `docker/guguta/` | Dockerfile-urile stack-ului (API, migrator, interfață) |
| `deploy/edu-platform/` | Stack-ul de producție și ghidul de instalare |
| `tests/guguta/` | Testele de integrare Guguță |
| `docs/guguta/` | Documentația canonică: specificații, ADR-uri, audituri, rapoarte |

## Documentație

Setul canonic este [docs/guguta/](docs/guguta/README.md):

| Document | Rol |
| --- | --- |
| [SPECIFICATII_GUGUTA.md](docs/guguta/SPECIFICATII_GUGUTA.md) | Comportamentul produsului; autoritatea principală. |
| [GHID_IMPLEMENTARE_LLM.md](docs/guguta/GHID_IMPLEMENTARE_LLM.md) | Design, infrastructură, securitate, teste. |
| [GUGUTA_IMPLEMENTATION_CHECKLIST.md](docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md) | Progresul pe etapele L0–L10. |
| [adr/](docs/guguta/adr/) | Deciziile de arhitectură (ADR-0001 … ADR-0010). |
| [DEPLOYMENT_READINESS_CHECKLIST.md](docs/guguta/DEPLOYMENT_READINESS_CHECKLIST.md) | Dovezile necesare lansării. |
| [DIVERGENTE_UPSTREAM.md](docs/guguta/DIVERGENTE_UPSTREAM.md) | Unde direcția Guguță contrazice regulile upstream. |

## Licență

MIT. Proiectul este un fork al
[Open Notebook](https://github.com/lfnovo/open-notebook) și păstrează
[LICENSE](LICENSE) original (Copyright © 2024 Luis Novo); codul adăugat pentru
Guguță este distribuit sub aceeași licență. Componentele terțe își păstrează
licențele.
