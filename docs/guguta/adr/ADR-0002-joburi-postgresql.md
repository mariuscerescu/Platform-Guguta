# ADR-0002: Joburi durabile în PostgreSQL, fără broker extern

Stare: acceptat · Data: 6 septembrie 2026
Referințe: GHID_IMPLEMENTARE_LLM.md §6.3, EVALUARE §4.4.

## Context

Upstream rulează ingestia, embeddingurile și podcasturile prin `surreal-commands`, o coadă construită pe SurrealDB. Guguță are nevoie de procesare asincronă reluabilă (upload → extracție → segmentare → embedding → publicare atomică) care să supraviețuiască restarturilor și să nu dubleze efecte externe (costuri AI) la retry.

## Decizie

1. Coada Guguță este tabelul **`processing_jobs`** în PostgreSQL, cu livrare *cel puțin o dată* și efecte idempotente pe handler.
2. Revendicare în tranzacție scurtă cu `FOR UPDATE SKIP LOCKED`, apoi commit; câmpuri `lease_owner`, `lease_token`, `lease_until`, `heartbeat_at`, `attempts`, `max_attempts`, `deadline`, `last_error`.
3. Workerul execută handlerul **fără tranzacție SQL deschisă**; completarea verifică `lease_token` și revizia țintei (`target_revision`) — un worker expirat sau o țintă ștearsă/revizuită nu pot publica.
4. Backoff cu jitter, limită de încercări, stare `failed` inspectabilă; anularea joburilor pentru ținte șterse; jobul și obiectele de domeniu se creează **în aceeași tranzacție** cu ținta.
5. Fără Redis, RabbitMQ sau alt broker în MVP. Dacă ulterior se introduce un broker, publicarea se face prin outbox; nu se presupune atomicitate PostgreSQL–broker.
6. Workerul Guguță este un proces separat care rulează aceeași imagine API cu altă comandă; nu se rulează migrații la pornirea workerului sau a API-ului — migratorul este unic pe release.

## Consecințe

- Efectele externe AI pot produce costuri repetate chiar dacă scrierea DB este idempotentă: se înregistrează încercările și se folosește idempotency furnizorului când există.
- Heartbeat și vârsta celui mai vechi job devin metrici operator; lease-ul expirat face jobul reeligibil.
- Refuzul publicării pentru revizii vechi protejează invariantul A21 din specificații.
