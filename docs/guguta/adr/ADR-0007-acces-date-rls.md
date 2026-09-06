# ADR-0007: Acces la date — SQLAlchemy async, roluri DB separate, RLS ca apărare în profunzime

Stare: acceptat · Data: 6 septembrie 2026
Referințe: GHID_IMPLEMENTARE_LLM.md §3.1, §3.2, §1.2.

## Context

Upstream deschide o conexiune per apel `repo_*`, fără pool, pe un utilizator SurrealDB privilegiat, cu migrații rulate automat la pornirea API-ului. Guguță cere izolare verificabilă între utilizatori (A04/A11/A23) și privilegii minime pentru fiecare proces.

## Decizie

1. Strat de acces: **SQLAlchemy 2 async + psycopg 3**, pool dimensionat configurabil, tranzacții scurte; cererile LLM nu țin tranzacții SQL deschise.
2. **Roluri DB distincte**:
   - `guguta_migrator` — proprietarul schemei; rulează doar migrarea unică pe release (job de release / `alembic upgrade head`), nu runtime.
   - `guguta_api` — runtime API; fără superuser/BYPASSRLS, fără proprietate asupra tabelelor.
   - `guguta_worker` — runtime worker; acces controlat la coadă și la datele personale cu actor validat.
3. **RLS** pe tabelele personale ca apărare în profunzime; autorizarea primară rămâne în servicii și interogări (ActorContext obligatoriu în repository-uri, nu doar un ID).
4. Contextul actorului se setează server-side cu `SET LOCAL app.actor_id` **în tranzacție**; nu se persistă pe conexiunea reciclată de pool. Politicile folosesc `current_setting('app.actor_id', true)`; la lipsă, accesul e refuzat (NULL ≠ owner).
5. Tabelele comune (SourceAsset, MaterialVersion, artefacte, chunkuri, embeddinguri) NU au politică „orice utilizator autentificat citește tot”: citirea se dovedește printr-o asociere autorizată (EXISTS prin notebook_sources → digital_notebooks → owner).
6. Sortările/filtrele sunt allowlist; SQL parametrizat; repository-urile nu emit SQL arbitrar din parametri de client.
7. Migrațiile Alembic pornesc de la zero și se testează de la fiecare versiune Guguță anterioară; nu se rulează concurent din API/worker la pornire.
8. Testele de izolare rulează pe PostgreSQL real cu rolurile runtime reale, pe două conexiuni/actori, inclusiv după rollback și refolosirea conexiunii din pool.

## Consecințe

- Politicile RLS și actorii sunt parte a migrațiilor, nu fișiere SQL decorative; activarea se verifică în teste (`relrowsecurity`, `relforcerowsecurity`).
- Contradicția cu AGENTS.md upstream (fără pool, migrații la pornire, conexiune per apel) este consemnată în DIVERGENTE_UPSTREAM.md.
- Workerul setează `app.actor_id` la actorul validat al țintei când atinge date personale; pentru coadă (revendicare joburi) folosește politica sa de rol.
