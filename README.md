<div align="center">
  <p><strong>Platformă educațională bazată pe inteligență artificială pentru elevii din Republica Moldova</strong></p>
  <p>
    <a href="https://tineri.math.md/edu-platform">Instanța publică</a>
    ·
    <a href="https://tineri.math.md">Pagina proiectului</a>
    ·
    <a href="docs/guguta/SPECIFICATII_GUGUTA.md">Specificații</a>
    ·
    <a href="docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md">Starea implementării</a>
    ·
    <a href="deploy/edu-platform/README.md">Instalare pe server</a>
  </p>
</div>

Elevul își construiește *carnete digitale* din materialele de studiu — manuale,
notițe, prezentări, fotografii — și învață din ele prin conversație cu Guguță,
un tutore care ghidează pas cu pas, cu citări exacte din paginile selectate,
prin text sau prin voce, în limba română.

## Despre proiect

Platforma este dezvoltată în cadrul proiectului de cercetare **„Platformă
Educațională bazată pe Inteligența Artificială «Guguță»”**, finanțat prin
programul **Tineri Cercetători**, cifrul **25.80012.0807.21TC**, perioada
**2025–2026**.

| | |
| --- | --- |
| Instituții | Universitatea de Stat din Moldova; Institutul de Matematică și Informatică „Vladimir Andrunachievici” |
| Conducător | Bumbu Tudor |
| Executori | Cerescu Marius, Caftanatov Olesea, Degteariov Nichita, Parahonco Alexandru, Bostan Ion, Ciala Iurie, Bumbu Dan |
| Pagina proiectului | <https://tineri.math.md> — rezumat, echipă, rezultate, diseminare |

Proiectul dezvoltă, pe lângă platformă, resurse lingvistice deschise pentru
limba română: modele de recunoaștere vocală, sinteză vocală și un corpus audio
de peste 1 000 de ore (200 înregistrate în studio). Platforma este rezultatul
aplicativ în care aceste resurse se întâlnesc cu manualele școlare.

Codul pornește de la [Open Notebook](https://github.com/lfnovo/open-notebook)
(licență MIT), cu fundația tehnică înlocuită: PostgreSQL + pgvector în loc de
SurrealDB, identitate proprie, izolare pe utilizator la nivel de rând și
servicii AI private rulate pe serverul proiectului.

## Ce oferă platforma

**Carnete și materiale**

- **Carnete digitale** — un carnet pornește dintr-un șablon pregătit de echipă
  (de exemplu „Clasa a V-a”, cu manualele relevante) sau de la zero. Pornirea
  dintr-un șablon creează o copie personală pe care elevul o poate modifica.
- **Materiale** — PDF (text și scanat), DOCX, PPTX, TXT/Markdown, imagini și
  text introdus direct. Procesarea rulează într-un worker: extragere de text,
  OCR pe fiecare pagină (PP-OCRv5), indexare vectorială și păstrarea paginii ca
  dovadă vizuală, astfel încât răspunsurile pot cita pagina exactă.
- **Partajare** — prin link sau cod, ca pachet fix; destinatarul primește o
  copie independentă. Catalogul de șabloane este administrat de echipă, cu
  roluri de utilizator, editor de catalog și administrator.

**Conversația cu Guguță**

- **Tutore, nu răspunsuri gata** — Guguță ghidează elevul prin exerciții în
  loc să livreze soluția ([ADR-017](docs/7-DEVELOPMENT/decisions/ADR-017-source-aware-educational-tutor.md))
  și poate preda noțiuni generale când pagina nu le conține.
- **Citări verificate** — recuperare hibridă (text + vectori Qwen3 + reranking),
  un agent mărginit care poate inspecta paginile ca imagine
  ([ADR-016](docs/7-DEVELOPMENT/decisions/ADR-016-agentic-page-inspection.md))
  și citări randate pe server, validate înainte de afișare.
- **Atașamente în conversație** — fotografii și documente adăugate la un mesaj,
  căutabile și private, șterse împreună cu conversația
  ([ADR-019](docs/7-DEVELOPMENT/decisions/ADR-019-private-images-and-chat-attachments.md)).
- **Voce** — dictare în română printr-un serviciu local Parakeet
  ([ADR-009](docs/7-DEVELOPMENT/decisions/ADR-009-private-local-asr-service.md))
  și conversație vorbită în timp real, cu context din carnetul curent
  ([ADR-022](docs/7-DEVELOPMENT/decisions/ADR-022-elevenlabs-notebook-voice.md)).
- **Însoțitorul Guguță** — mascota este prezentă pe toate paginile, își
  adaptează contextul la pagina sau carnetul deschis și poate fi ascunsă.

**Studio**

- **Prezentări audio** — rezumate vorbite ale materialelor selectate, generate
  asincron cu sinteză vocală românească privată (MOSS-TTS), cu instrucțiuni de
  focalizare.
- **Flashcard-uri** și **quiz-uri** — generate din materiale, cu citări; quiz-urile
  cu întrebări grilă au butonul **„Deschide în PlayQuiz”**: cu acordul elevului,
  quizul și contul se creează automat pe platforma parteneră play-quiz.com
  ([ADR-023](docs/7-DEVELOPMENT/decisions/ADR-023-playquiz-extern-export.md);
  activ când instanța are cheia de partener). Integrarea locală anterioară
  ([ADR-021](docs/7-DEVELOPMENT/decisions/ADR-021-playquiz-integration.md)) este deprecată.

**Cont, confidențialitate**

- **Înregistrarea ca o conversație cu Guguță**: întreabă numele, școala, clasa și
  e-mailul, cere acordurile (politica de confidențialitate; pentru clasele
  I–VIII și acordul unui părinte), recapitulează și abia apoi cere parola
  ([ADR-024](docs/7-DEVELOPMENT/decisions/ADR-024-inregistrare-conversationala-consimtaminte.md)).
- **Drepturile elevului**: pagina „Contul meu” pentru acces, corectare și
  ștergerea contului; informare despre cookie-uri (doar strict necesare),
  politică de confidențialitate și termeni în platformă.

**Interfață**

- În română (`ro-MD`), în stilul unui caiet de lucru cu trei panouri
  (materiale, conversație, Studio), temă deschisă și întunecată, utilizabilă pe
  telefon.
- Configurarea AI este centrală: elevul nu alege furnizori și nu introduce chei.
  Furnizorii externi sunt restrânși la rutare fără păstrarea datelor
  ([ADR-018](docs/7-DEVELOPMENT/decisions/ADR-018-openrouter-private-performance-routing.md)).

## Stare

Platforma este **în dezvoltare activă**, cu o instanță publică de test la
<https://tineri.math.md/edu-platform>. Nu este încă lansată oficial pentru
elevi reali; lansarea urmează regulile din
[DEPLOYMENT_READINESS_CHECKLIST.md](docs/guguta/DEPLOYMENT_READINESS_CHECKLIST.md).

Etape parcurse (detalii în [checklistul de implementare](docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md)):

| Perioadă | Realizări |
| --- | --- |
| septembrie 2026, prima săptămână | Fundația: PostgreSQL + pgvector, RLS, identitate și sesiuni, materiale și worker, căutare și chat cu citări, catalog și șabloane, partajare, interfață Next.js; două audituri (interfață și backend) cu constatările închise. |
| septembrie 2026 | Streaming SSE, suită E2E Playwright, autentificare cu parolă, publicare sub subcale prin nginx, redesign în stilul caietului de lucru, Studio (prezentări audio cu TTS românesc, flashcard-uri, quiz-uri), coduri de partajare, ingestie locală. |
| octombrie 2026 | Recuperare românească îmbunătățită, OCR și dovezi vizuale pe pagină, agent de inspecție a paginilor, tutore pedagogic, imagini și atașamente private, confidențialitate la rutarea OpenRouter, teme deschisă/întunecată, însoțitorul Guguță cu voce, integrarea PlayQuiz. |

Direcții de lucru deschise: interfață adaptată vârstei și o „scenă vie” care
reacționează la conversație — vezi
[IDEI_UI_ADAPTIV.md](docs/guguta/IDEI_UI_ADAPTIV.md); organizarea pe clase și
discipline; evaluarea pedagogică a flashcard-urilor și quiz-urilor.

## Arhitectură

```
browser
  └── frontend-guguta     Next.js 15 (App Router), română — port 3001
        └── /guguta-api/*     proxy same-origin (next.config.ts)
              └── api         FastAPI — port 5055, rute sub /api/v1
                    ├── PostgreSQL 17 + pgvector   date, vectori, coada de joburi,
                    │                              migrări (Alembic, revizia 0022)
                    ├── parakeet-asr   dictare românească (GPU, rețea privată)
                    ├── qwen-retrieval embeddings + reranking (GPU, rețea privată)
                    └── worker   materiale, OCR, rezumate audio
                          ├── ppocr      PP-OCRv5 pentru pagini PDF (GPU)
                          ├── moss-tts   sinteză vocală românească (GPU)
                          └── stocare fișiere (volum) + furnizor LLM
```

| Componentă | Rol | Porturi |
| --- | --- | --- |
| `frontend-guguta/` | Interfața platformei (Next.js) | 3001 în dezvoltare · 8300 pe server (doar loopback) |
| `api/` + `open_notebook/` | API-ul FastAPI și logica de domeniu | 5055; 5056 → 5055 în dezvoltare |
| `open_notebook/jobs/guguta/` | Worker-ul de procesare | — |
| PostgreSQL + pgvector | Date, vectori, coada de joburi, migrări | 5433 → 5432 în dezvoltare |
| `moss-tts`, `parakeet-asr`, `qwen-retrieval`, `ppocr` | Servicii AI private, pe GPU | doar în rețeaua Docker |
| `deploy/edu-platform/` | Stack-ul de producție pentru server | 8300 (doar loopback) |

Browserul vorbește doar cu frontend-ul; cookie-ul de sesiune (`SameSite=Lax`)
circulă fără CORS, iar API-ul este accesat prin proxy-ul same-origin
`/guguta-api/*`. Rutele API: `/api/v1/auth`, `/api/v1/notebooks` (cu `/sources`,
`/sessions`, `/notes`, `/search`, `/audio-overviews`, `/flashcards`, `/quizzes`),
`/api/v1/jobs`, `/api/v1/catalog/templates`, `/api/v1/imports`, `/api/v1/admin`,
`/api/v1/speech` (dictare), `/api/v1/voice/elevenlabs` (conversație vorbită).
Pentru operare: `/healthz`, `/readyz` (verifică și schema) și
`/versionz`. Serviciile AI și baza de date nu sunt publicate pe gazdă.

Componentele din upstream care **nu** fac parte din platformă: `frontend/`
(interfața originală Open Notebook) și SurrealDB. Deciziile de arhitectură sunt
consemnate în [docs/guguta/adr/](docs/guguta/adr/) (fundația, ADR-0001 … 0013)
și în [docs/7-DEVELOPMENT/decisions/](docs/7-DEVELOPMENT/decisions/) (ADR-008 …
022, funcțiile din septembrie–octombrie 2026).

## Pornire locală

Nevoie: Docker, Python 3.11+ cu [uv](https://docs.astral.sh/uv/), Node.js 20+.
Serviciile GPU (ASR, TTS, OCR, retrieval) sunt opționale în dezvoltare; fără ele,
dictarea, prezentările audio și OCR-ul sunt indisponibile, restul funcționează.

### 1. Configurarea

```bash
cp .env.guguta.example .env.guguta.local
```

Fișierul `.env.guguta.local` este ignorat de git. Completează acolo furnizorul
AI: `GUGUTA_OPENROUTER_API_KEY` și modelele (`GUGUTA_OPENROUTER_CHAT_MODEL`,
`..._EMBEDDING_MODEL`, `..._RERANK_MODEL`).

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
„se procesează”.

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
uv run pytest tests/guguta
```

Testele de integrare folosesc PostgreSQL real (roluri separate, izolare pe rând,
migrări) și se sar singure dacă baza de date nu este accesibilă. Testele
serviciilor GPU se sar fără serviciul respectiv. Restul suitei:
`uv run pytest tests/`. Verificări statice: `uv run ruff check .`,
`uv run python -m mypy .`. Fluxurile de interfață: `cd frontend-guguta && npx playwright test`.

## Publicare pe server

Stack-ul de producție este în
[deploy/edu-platform/](deploy/edu-platform/README.md): compose complet (interfață,
API, worker, migrator, PostgreSQL + pgvector, serviciile GPU), `.env` de
producție, blocul `location` pentru nginx-ul gazdă și ghidul de instalare,
verificare și depanare.

```bash
cd deploy/edu-platform
cp .env.example .env      # completează secretele; fișierul este ignorat de git
docker compose up -d --build
```

## Structura proiectului

| Cale | Conținut |
| --- | --- |
| `frontend-guguta/` | Interfața Guguță (Next.js, App Router), însoțitorul și temele |
| `open_notebook/` | Domeniu, acces la date, AI, autentificare, joburi |
| `api/` | API-ul FastAPI (`api/routers/guguta_v1.py`, `guguta_voice.py`, `api/services/guguta/`) |
| `alembic/` | Migrările de schemă (revizia curentă: `0022`) |
| `docker/guguta/` | Dockerfile-urile stack-ului (API, migrator, interfață, servicii GPU) |
| `deploy/edu-platform/` | Stack-ul de producție și ghidul de instalare |
| `tests/guguta/` | Testele de integrare Guguță |
| `docs/guguta/` | Documentația canonică: specificații, ADR-uri, audituri, rapoarte, idei |

## Documentație

Setul canonic este [docs/guguta/](docs/guguta/README.md):

| Document | Rol |
| --- | --- |
| [SPECIFICATII_GUGUTA.md](docs/guguta/SPECIFICATII_GUGUTA.md) | Comportamentul platformei; autoritatea principală. |
| [GHID_IMPLEMENTARE_LLM.md](docs/guguta/GHID_IMPLEMENTARE_LLM.md) | Design, infrastructură, securitate, teste. |
| [GUGUTA_IMPLEMENTATION_CHECKLIST.md](docs/guguta/GUGUTA_IMPLEMENTATION_CHECKLIST.md) | Progresul pe etapele L0–L10. |
| [IDEI_UI_ADAPTIV.md](docs/guguta/IDEI_UI_ADAPTIV.md) | Direcții noi: interfață adaptată vârstei și scena vie din carnet. |
| [adr/](docs/guguta/adr/) · [decisions/](docs/7-DEVELOPMENT/decisions/) | Deciziile de arhitectură. |
| [DEPLOYMENT_READINESS_CHECKLIST.md](docs/guguta/DEPLOYMENT_READINESS_CHECKLIST.md) | Dovezile necesare lansării. |
| [DIVERGENTE_UPSTREAM.md](docs/guguta/DIVERGENTE_UPSTREAM.md) | Unde direcția Guguță contrazice regulile upstream. |

## Licență

MIT. Codul pornește de la
[Open Notebook](https://github.com/lfnovo/open-notebook) și păstrează
[LICENSE](LICENSE) original (Copyright © 2024 Luis Novo); codul adăugat pentru
Guguță este distribuit sub aceeași licență. Componentele terțe își păstrează
licențele.
