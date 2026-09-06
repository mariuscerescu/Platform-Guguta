# Raport de livrare L8 — eliminare legacy și build propriu

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L8: 7/9 elemente bifate cu dovezi; transferul datelor demo rămâne deschis
  prin **D-08** (nu a fost mandatat; volumele sunt păstrate + inventariate).
- Build-ul țintă (imaginile Guguță) este legacy-free și verificat de o gardă
  automată care rulează la fiecare commit.

## 2. Fișiere create/modificate

- `tests/guguta/test_no_legacy_imports.py`: gardă AST pe toate modulele
  Guguță (database/auth/storage/jobs/ai + api services/routers/app +
  alembic) — interzice `surrealdb`, `surreal_commands`, `sqlite3`,
  `langgraph_checkpoint_sqlite`, `podcast_creator`, `content_core`;
  verifică și absența fișierelor SQLite din căile Guguță. Rulează în CI.
- `docker/guguta/api.Dockerfile`: imaginea proprie API+worker din commit
  (non-root uid 10001, dependențe doar stiva PostgreSQL/FastAPI — fără
  SurrealDB/podcast-uri/SQLite, GUGUTA_COMMIT build-arg, /versionz).
- `docker-compose.guguta.yml`: serviciile `api` (port 127.0.0.1:5056) și
  `worker` (aceeași imagine, comandă diferită), volum stocare privat
  `guguta_storage`, dependențe pe migrator completat cu succes.
- `api/guguta_app.py`: endpoint `/versionz` (commit fără secrete).
- `scripts/smoke.py`: smoke sintetic 2 conturi (healthz/versionz/login/
  carnet+sursă/izolare 404).
- `docs/guguta/RUNBOOK_CUTOVER.md`: ordin deployment, migrare unică,
  rollback fără downgrade destructiv, verificări 24h, date neportate.

## 3. Verificări executate

| Verificare | Rezultat |
| --- | --- |
| Gardă AST (imports legacy) | PASS (30+ fișiere scanate) |
| `uv run pytest tests/guguta -q` | **54 passed** (51 + 3 L8) |
| `docker compose build api` | imagine construită |
| `docker compose up -d api worker` | ambele pornite, non-root |
| `GET /healthz` `GET /versionz` `GET /readyz` (în container) | 200 / commit expus / schema 0007 |
| `scripts/smoke.py` contra containerului | **SMOKE PASS 4/4** (login, carnet, sursă, izolare 404) |
| `uv run ruff check` + `uv run mypy` | clean |

## 4. Probleme rezolvate

1. **uvicorn + lazy app**: un `app = None` la nivel de modul îl umbrea pe
   `__getattr__` — uvicorn primea None (ASGI2 detection) → 500. Fix:
   atributul `app` se construiește exclusiv prin `__getattr__` (PEP 562).
2. Configurația containerului refuza dev-login pe DB-ul principal —
   cauza reală: baza principală nu avea noile DB-defaults (model drift) —
   migrația **0008** sincronează toate coloanele (lista generată din modele).

## 5. Limite / deschise

- D-08 (transfer date demo) — decizie umană; până atunci nimic nu e migrat
  și volumele rămân în backup.
- Frontend Guguță (L5) și proba OIDC cu issuer fals — livrări deschise.
- SBOM-ul complet de release + scanarea vulnerabilităților se generează la
  primul release construit din CI (L9).

## 6. Următoarea acțiune concretă

**L9/L10 (restant) + L5 frontend:** interfața Next.js Guguță, proba OIDC
completă, restaurare backup în mediu separat, evaluarea pedagogică a
românei/citărilor, deployment readiness cu dovezi — lansarea cere GO-ul
responsabililor (R98/R101).
