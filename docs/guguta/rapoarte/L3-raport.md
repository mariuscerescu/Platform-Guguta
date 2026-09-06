# Raport de livrare L3 — materiale și worker

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L3: toate elementele bifate cu dovezi (vezi checklist); criterii A24 (PDF
  scanat respins explicit) și fundament A21 (lease/revizie) + A04 (izolare
  pe surse/joburi/download) testate.
- Migrația secvențială 0001→0002→0003 pe baza principală validează și nota
  „upgrade între versiuni Guguță" din L1.

## 2. Fișiere create/modificate

- `open_notebook/storage/guguta/`: `base.py` (interfață + erori),
  `filesystem.py` (chei UUID șarduite, root privat, `O_EXCL`, respingere
  traversal/backslash/absolut, verificare rămânere în root).
- `open_notebook/jobs/guguta/`: `queue.py` (claim `FOR UPDATE SKIP LOCKED`,
  lease_token/lease_until/heartbeat, complete/fail cu verificare lease +
  target_revision, backoff exponențial cu jitter în SQL, retry manual,
  cancel_for_target), `parsing.py` (detectare tip real prin magic bytes,
  extracție PDF per-pagină cu locatori, A24 pentru scanate, segmentare cu
  offseturi), `embeddings.py` (interfață provider + mock determinist până la
  D-02), `handlers.py` (pipeline publicat atomic: artefact+chunks+embeddings+
  sursă „Gata"; verificare spațiu vectorial activ, A27), `worker.py` (buclă
  proces, oprire grațioasă, `python -m open_notebook.jobs.guguta.worker`).
- `alembic/versions/0003_chunk_offsets_artifact_dedup.py`: offseturi chunk,
  index unic anti-dublare artefacte (retry-safe), politici worker pentru
  embedding_spaces + citire creator pentru assets/versions (INSERT…
  RETURNING cere și politică SELECT pe rândul nou).
- `api/services/guguta/sources.py`: upload (fișier/text) cu validare, cotă
  logică per utilizator, limită materiale/carnet, listare/detaliu/redenumire/
  selecție/ștergere (bump `context_revision`), download proxy autorizat,
  retry manual.
- `api/routers/guguta_v1.py` + `api/guguta_app.py`: rute `/sources…`,
  `/jobs/{id}`, mapare excepții (422/429/404).
- `open_notebook/database/guguta/config.py`: parametri chunk/lease/poll/
  provider embedding. `pyproject.toml`: pypdf, python-multipart.

## 3. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **31 passed** (14 L1 + 10 L2 + 7 L3) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: 26 fișiere |
| `docker compose … up migrator` (imagine reconstruită) | `Running upgrade 0001 -> 0002 -> 0003`, exit 0 |

## 4. Probleme rezolvate

1. `INSERT … RETURNING` + RLS: rândul nou avea politică doar de INSERT —
   adăugate politicile de citire pentru creator.
2. `str(engine.url)` maschează parola — lecția aplicată sistematic (DSN-uri
   pre-randate în fixturi).
3. `::float8` în text() SQL → eroare psycopg; înlocuit cu `CAST(x AS float8)`.
4. Index parțial unic pe `embedding_spaces.is_active` — testele care creează
   spații proprii folosesc `is_active=false`.
5. Dependințe de ordine între teste (job reîncerat rămas în coadă) — coada se
   golește înainte de testul de lease.
6. `ExtractionError` (tip de fișier neacceptat) era mapată la 500 — handler
   dedicat → 422.

## 5. Teste neexecutate / limite

- `cancel_for_target` nu are test direct (traseul „sursă ștearsă cât timp
  jobul e în coadă" — test dedicat la L4 odată cu context_revision).
- DOCX/PPTX: detectate valid, extracția respinsă explicit până la L5.
- Providerul de embedding este mock determinist (D-02 deschisă); schimbarea
  modelului = spațiu nou (A27) — fluxul de reindexare e la L9.
- Scanarea malware pentru pilot (R44) — rămâne de configurat la găzduire.

## 6. Următoarea acțiune concretă

**L4 — Căutare, chat și prima probă completă:** căutare textuală+semantică pe
setul autorizat, ChatSession/ChatMessage/Citation, context_revision la
generare, streaming tipizat cu anulare, testul „doi utilizatori → carnet →
PDF → căutare → chat/citare → restart".
