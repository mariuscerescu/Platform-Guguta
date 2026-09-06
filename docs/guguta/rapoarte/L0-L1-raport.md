# Raport de livrare L0 + L1 — fundația Guguță

Data: 6 septembrie 2026 · Ramură: `guguta/foundation` · Commituri: `e629abb` (L0), `5a23eef` (L1)
Bază: Open Notebook 1.14.0, commit `8297bb22e2eaeb0d8feafc0538f0d736453571d4`

## 1. Elemente de checklist acoperite

- L0: toate elementele bifate (vezi [GUGUTA_IMPLEMENTATION_CHECKLIST.md](../GUGUTA_IMPLEMENTATION_CHECKLIST.md) L0).
- L1: toate elementele bifate, cu o notă: testarea „upgrade între versiuni Guguță” devine executabilă abia la migrația 0002 (nu există încă o versiune Guguță anterioară).
- Criterii Axx cu fundament la acest nivel: A11 (izolarea la nivel de schemă/RLS — parțial; API-ul complet vine în L2), A23 (fundament: roluri separate, fără privilegii runtime).

## 2. Fișiere create/modificate

**L0:** `docs/guguta/` (5 documente canonice + checklist mutat + README + ADR-0001..0007 + DIVERGENTE_UPSTREAM.md + DECIZII_EXTERNE.md), `MIGRATION_INVENTORY.md`, `NOTICE`, remote-uri reconfigurate, ramura `guguta/foundation`.

**L1:** `pyproject.toml` + `uv.lock` (sqlalchemy[asyncio] <2.1, psycopg[binary,pool] <3.3, alembic <1.15, pgvector <0.4, pydantic-settings <3), `open_notebook/database/guguta/` (config.py, engine.py, models.py — 26 tabele), `alembic.ini` + `alembic/` (env async, migrația `0001` cu extensia `vector`, 77 politici RLS pe 26 tabele, triggere de integritate, roluri `guguta_api`/`guguta_worker`, granturi + default privileges), `docker-compose.guguta.yml` (pgvector/pgvector:0.8.0-pg17 @ digest fixat, volum numit `guguta_pg_data`, porturi doar pe 127.0.0.1), `docker/guguta/migrator.Dockerfile` + `bootstrap-roles.sh`, `.env.guguta.example`, `scripts/dev.ps1`, `scripts/check.ps1`, `.github/workflows/guguta-ci.yml`, `tests/guguta/` (conftest + 14 teste).

## 3. Comportament înainte/după

- **Înainte:** persistență exclusiv SurrealDB (BSL), model single-user, migrații `.surrealql` rulate la pornirea API-ului, memorie chat în SQLite.
- **După:** stiva Guguță PostgreSQL 17 + pgvector rulează separat (proiect Compose `guguta`, volum numit, volumele demo upstream neatinse); schema completă Guguță migrată de la zero printr-un migrator unic; RLS activă pe toate tabelele pentru rolurile runtime; contextul actorului este tranzacțional (`set_config(..., true)`) și nu supraviețuiește refolosirii conexiunii din pool; config de producție refuză auth de test/origini wildcard/URL-uri runtime lipsă.

## 4. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `docker compose -f docker-compose.guguta.yml --project-name guguta up -d db` | db healthy (pgvector/pgvector:0.8.0-pg17, digest `sha256:40b40496…`) |
| `... run --rm migrator` (de 2×: imagine inițială + reconstruită cu modelele finale) | `Running upgrade -> 0001` · 27 tabele, 77 politici, 26 tabele RLS |
| `uv run ruff check open_notebook/database/guguta alembic tests/guguta` | All checks passed |
| `uv run mypy open_notebook/database/guguta tests/guguta` | Success: no issues in 7 files |
| `uv run pytest tests/guguta -q` | **14 passed** (PostgreSQL real, roluri runtime reale) |
| `uv run pytest tests/ -q --ignore=tests/guguta` | 651 passed, 5 failed — eșecurile sunt **preexistente pe Windows** (`test_podcast_path` compară căi POSIX, `test_proxy` e dependent de mediul local); nu afectate de fundație |
| Backup + restaurare date demo | 18/18 hash-uri SHA256 identice (`backups/pre-migration-20260906-112923/`) |

Testele RLS acoperă: A vede doar carnetele sale; B nu citește/nu modifică/nu șterge carnetul lui A nici prin ID ghicit; fără actor → zero rânduri; contextul actorului nu supraviețuiește rollback+refolosirii conexiunii (pool de mărime 1); B nu poate scrie mesaje în sesiunea lui A; workerul ajunge la coadă fără actor dar nu la datele personale, și le vede doar cu actorul validat.

## 5. Probleme rezolvate în timpul livrării

1. `roles <@ text[]` vs `varchar[]` — CHECK invalid pe Postgres; fix cu cast `::varchar[]`.
2. `CREATE POLICY ... AS all` — sintaxă invalidă; clauza `AS` acceptă doar PERMISSIVE/RESTRICTIVE.
3. **Parola `***`**: `str(url.set(...))` în SQLAlchemy maschează parola; DSN-urile se randează cu `render_as_string(hide_password=False)`.
4. `ProactorEventLoop` incompatibil cu psycopg async pe Windows — `SelectorEventLoop` în `alembic/env.py` și politica de event loop în conftest.
5. Testele rulau contra bazei `guguta` (migrată de imaginea Docker veche) în loc de `guguta_test` — fixtura acum migrează și testează exclusiv baza efemeră.
6. Coloanele cu default doar client-side au primit `server_default` (32 coloane) — INSERT-urile raw (worker) rămân valide.

## 6. Teste neexecutate

- CI pe runner GitHub (push la fork pendinte de mandat/acces); local echivalentele trec.
- „Upgrade între versiuni Guguță” — se execută la prima migrație incrementală (0002).
- Suitele Vitest/Playwright — nu se aplică L1 (fără modificări frontend).

## 7. Migrații, impact date, revenire

- Migrația `0001` pornește de la zero; `downgrade()` face `DROP SCHEMA public CASCADE` — doar development/test (R17: rollback-ul de release nu folosește downgrade destructiv).
- Volumele demo (`surreal_data/`, `notebook_data/`) și containerele upstream nu au fost modificate; backup-ul lor verificat rămâne în `Platforma Guguta/backups/`.

## 8. Secrete/configurații necesare (fără valori)

- `GUGUTA_DATABASE_URL_{MIGRATOR,API,WORKER}` — furnizate; parolele dev sunt doar locale.
- Pentru L2: `GUGUTA_OIDC_{ISSUER,CLIENT_ID,CLIENT_SECRET,REDIRECT_URI}` (D-01) și cheia de criptare a sesiunilor/cheilor.
- Pentru L4 live: chei furnizori AI (D-02/D-10).

## 9. Limite și riscuri rămase

- CI-ul nu a rulat încă pe runner; gitleaks nu a scanat istoricul complet local.
- Pe mașina curentă, `localhost` (IPv6) blochează conexiunile — DSN-urile folosesc `127.0.0.1`; de documentat pentru operatori.
- RLS nu e FORCED (migratorul, ca owner, rămâne capabil să migreze); compensat prin roluri runtime fără proprietate — testat.
- 5 teste upstream eșuează pe Windows preexistent (podcast/proxy) — de raportat separat upstream-ului sau ignorate în CI prin marker.

## 10. Următoarea acțiune concretă

**L2 — Identitate și CRUD autorizat:** adaptor OIDC (Authorization Code + PKCE, issuer fals pentru teste), sesiuni opace cu token hashuit, ActorContext obligatoriu în servicii, rute `/api/v1/notebooks` cu proprietate pe server, dezactivarea rutelor upstream neportate, teste A04/A11/A23 și două conturi sintetice.
