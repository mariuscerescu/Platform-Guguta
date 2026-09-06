# Raport de livrare L4 — căutare, chat și prima probă completă

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L4: toate elementele bifate; streaming SSE + anulare marcate **parțial**
  (ordonarea și retry-ul prin idempotency sunt implementate și testate;
  streamingul UI vine la L5).
- Poarta G2/G3: proba completă doi utilizatori (upload → procesare → căutare
  → chat/citare → izolare → restart) trece.
- Criterii: A12 (citări autorizate, reale), A13 (lipsa informației declarată),
  A17 (context nou după schimbarea surselor), A04/A11 fundament la nivel de
  chat/citări.

## 2. Fișiere create/modificate

- `api/services/guguta/search.py`: SearchService — text (ILIKE + tsvector
  'simple', OR-semantics pe tokeni sanitizați), vector (cosine `<=` prag
  configurabil), 404 pe carnet străin, merge intercalat.
- `open_notebook/ai/guguta/chat.py`: protocol ChatProvider + MockChatProvider
  determinist (citește doar din context; marker `[fără răspuns]` pentru A13);
  prompt de sistem educațional versionat.
- `api/services/guguta/chat.py`: sesiuni, mesaje cu seq per-sesiune (lock
  `FOR UPDATE` pe rândul sesiunii), citări validate (doar din setul trimis
  modelului, snapshot display_name/locator), idempotency în două faze
  (pending → chat_message), buget de context, context_revision pe fiecare
  mesaj; generarea rulată ÎN AFARA tranzacțiilor SQL.
- `api/routers/guguta_v1.py`: `/search`, `/sessions`, `/messages`,
  `/citations`. `api/guguta_app.py`: wiring + excepții noi (409/422).
- `open_notebook/jobs/guguta/embeddings.py`: mock cu semnătură de prezență a
  cuvintelor (vectori apropiați pentru vocabular comun).
- `alembic/versions/0004_chat_seq_per_session.py`: seq per-sesiune (idempotent).
- `open_notebook/database/guguta/config.py`: `chat_provider`,
  `vector_max_distance`.

## 3. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **35 passed** (14 L1 + 10 L2 + 7 L3 + 4 L4) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: 31 fișiere |
| `docker compose … up migrator` | `Running upgrade 0003 -> 0004` |

## 4. Probleme rezolvate

1. `seq` era UNIQUE global (drift model) — migrația 0004: UNIQUE(session_id, seq).
2. `plainto_tsquery` = AND stricat → recall zero pe întrebări naturale —
   OR-semantics cu tokeni sanitizați (allowlist, fără injecție).
3. Fixture PDF: UTF-8 în font WinAnsi → pypdf corupe diacriticele — textele
   PDF de test trecute pe ASCII (limitare de fixture documentată; validarea
   românei pe manuale reale la L9).
4. Vector search fără prag întorcea vecini irelevanți — `vector_max_distance`.
5. Faza de idempotency: replay întorcea ID-ul greșit — două faze (pending →
   done) cu result_id = mesajul asistent.

## 5. Teste neexecutate / limite

- Streaming SSE + anulare (L5, cu UI).
- Probele live cu furnizori AI reali (D-02/D-10 deschise) — payloadurile
  către model sunt construite doar din fragmente autorizate; logarea/
  măsurarea costurilor complete la L5/L9.
- Evaluarea calității răspunsurilor în română (L9, cu profesor).

## 6. Următoarea acțiune concretă

**L5 — Produs MVP, design și administrare:** DOCX/PPTX/TXT extracție, notițe
private, localizarea ro-MD completă, design tokens + pagina principală,
configurarea centrală AI cu criptarea cheilor, dezactivarea finală pe server
a funcțiilor amânate, raportarea conținutului problematic.
