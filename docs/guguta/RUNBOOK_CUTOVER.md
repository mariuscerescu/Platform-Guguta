# Runbook — cutover și rollback Guguță (L8)

Public: responsabilul tehnic de intervenție. Acest runbook descrie trecerea
pe stiva Guguță și revenirea, pentru mediul staging/pilot. Lansarea în
producție cere GO explicit (R98) — execuția acestui document NU este
autorizare.

## 1. Premize

- Commitul release-ului este tag-at în fork și imaginile se construiesc din
  acel commit cu `--build-arg GUGUTA_COMMIT=<sha>` (R01/R02).
- Backup pre-release verificat (PostgreSQL dump + directorul de stocare) —
  `scripts/backup.ps1` sau echivalent (R99).
- Migrațiile au fost testate pe staging de la zero și din versiunea anterioară.
- Secretele sunt în secrets manager / .env protejat, nu în Git (R08).

## 2. Ordine de deployment (fereastră de mentenanță)

1. `docker compose --project-name guguta pull` (imagini cu digest fixat).
2. `docker compose --project-name guguta stop api worker` — scrierile se opresc;
   durata ferestrei = suma pașilor de mai jos.
3. Backup final PostgreSQL (`pg_dump`) — punct de rollback coerent.
4. `docker compose --project-name guguta run --rm migrator` — migrare unică
   (alembic upgrade head). Se rulează o singură dată pe release (R09/R10).
5. `docker compose --project-name guguta up -d db api worker`.
6. Verificări post-release:
   - `GET /healthz` → 200 (liveness);
   - `GET /readyz` → 200 + `schema` = versiunea așteptată;
   - `GET /versionz` → commitul așteptat;
   - smoke sintetic: `scripts/smoke.ps1` (doi conturi sintetice, carnet,
     izolare) — fără documente ale elevilor reali (R103).

## 3. Rollback

- **Schema compatibilă** (migrații additive, cazul curent): revenim la
  imaginea anterioară (`docker compose up -d api worker` cu digestul vechi)
  fără downgrade de schemă. Scrierile noi rămân în tabele și sunt compatibile
  cu imaginea anterioară (migrațiile noastre sunt additive până la contraindicație).
- **Migrare incompatibilă** (viitor): nu rulăm niciodată downgrade destructiv
  (R17). Rollback = restaurarea backupului din pasul 3 + imaginea anterioară;
  scrierile din fereastră se pierd conform RPO convenit — fereastra se
  anunță înainte (R100).
- Secretele/cheile noi: rotația cheilor de criptare păstrează cheile vechi în
  `GUGUTA_CREDENTIAL_ENCRYPTION_KEYS` — rollback-ul cifrează/decriptează cu
  ambele (MultiFernet).

## 4. Date neportate / decizii (D-08)

- Volumele demo upstream (`surreal_data/`, `notebook_data/`) NU sunt migrate
  implicit. Transferul lor cere: proprietar desemnat, export controlat,
  dry-run, reconciliere (MIGRATION_INVENTORY.md §4).
- Podcasturi, transformări, chat istoric SQLite — nu se transferă în MVP.

## 5. Verificări în primele 24h

- Alerte active: API erori 5xx, worker coadă veche, spațiu stocare, backup
  eșuat (R83).
- Costurile AI și încercările eșuate în `chat_messages` / `processing_jobs`.
-Observația post-release se consemnează în deployment readiness (R108).
